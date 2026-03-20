# AI GC START
from __future__ import annotations

import json
import re
from typing import Any

from app import db
from app.agent.exceptions import PlanningError
from app.agent.prompts import build_planner_system_prompt, build_planner_user_prompt
from app.agent.types import AgentSession, PlanDecision, ToolCall, ToolSpec, WorkingContext
from app.services.llm import OpenAICompatibleLLM


class AgentPlanner:
    async def decide_next_action(
        self,
        session: AgentSession,
        working_context: WorkingContext,
        available_tools: list[ToolSpec],
    ) -> PlanDecision:
        llm_decision = await self._try_llm_planning(session, working_context, available_tools)
        if llm_decision is not None:
            return llm_decision
        return self._fallback_plan(session, working_context, available_tools)

    async def _try_llm_planning(
        self,
        session: AgentSession,
        working_context: WorkingContext,
        available_tools: list[ToolSpec],
    ) -> PlanDecision | None:
        service = db.get_service(session.service_id)
        if not service:
            return None
        llm = OpenAICompatibleLLM(service)
        if not hasattr(llm, "chat_completion_text"):
            return None
        try:
            response_text = await llm.chat_completion_text(
                messages=[
                    {"role": "system", "content": build_planner_system_prompt()},
                    {
                        "role": "user",
                        "content": build_planner_user_prompt(
                            session=session,
                            working_context=working_context,
                            available_tools=available_tools,
                        ),
                    },
                ],
                temperature=0.1,
            )
            parsed = self._parse_json_object(response_text)
            if parsed is None:
                return None
            decision = PlanDecision.model_validate(parsed)
            return self._validate_llm_decision(decision, available_tools)
        except Exception:
            return None

    def _fallback_plan(
        self,
        session: AgentSession,
        working_context: WorkingContext,
        available_tools: list[ToolSpec],
    ) -> PlanDecision:
        available_tool_names = {tool.name for tool in available_tools}
        last_observation = self._last_observation(working_context)
        latest_summary = str(session.working_memory.get("latest_summary") or "").strip()
        latest_answer = str(session.working_memory.get("latest_answer") or "").strip()

        if session.working_memory.get("message_sent"):
            final_answer = latest_summary or latest_answer or "消息已发送。"
            return PlanDecision(
                action_type="finish",
                reasoning_summary="目标中的发送动作已完成，结束本次会话。",
                updated_plan=session.current_plan or ["任务已完成"],
                final_answer=final_answer,
                done=True,
            )

        retry_decision = self._build_retry_decision(session, available_tool_names)
        if retry_decision is not None:
            return retry_decision

        missing_context_decision = self._build_missing_context_decision(session)
        if missing_context_decision is not None:
            return missing_context_decision

        if latest_summary:
            if self._goal_mentions_send(session.goal):
                receive_id, receive_id_type = self._resolve_send_target(session)
                if receive_id and "send_feishu_message" in available_tool_names:
                    if not self._recent_failed_tool("send_feishu_message", working_context):
                        return PlanDecision(
                            action_type="tool_call",
                            reasoning_summary="已经有摘要结果，下一步把内容发送到目标飞书会话。",
                            updated_plan=["生成摘要", "发送结果"],
                            next_tool_call=ToolCall(
                                tool_name="send_feishu_message",
                                arguments={
                                    "receive_id": receive_id,
                                    "receive_id_type": receive_id_type,
                                    "text": latest_summary,
                                },
                                rationale="将已生成的摘要回发到目标会话。",
                            ),
                        )
            return PlanDecision(
                action_type="finish",
                reasoning_summary="摘要已生成，当前目标不要求继续执行副作用动作。",
                updated_plan=["生成摘要"],
                final_answer=latest_summary,
                done=True,
            )

        if latest_answer and not self._goal_mentions_send(session.goal):
            return PlanDecision(
                action_type="finish",
                reasoning_summary="已经得到可直接返回的回答，结束当前会话。",
                updated_plan=session.current_plan or ["知识检索增强回答"],
                final_answer=latest_answer,
                done=True,
            )

        if last_observation and last_observation.get("tool_name") == "search_knowledge":
            knowledge_count = len(((last_observation.get("result") or {}).get("results") or []))
            if "ask_llm_question" in available_tool_names:
                return PlanDecision(
                    action_type="tool_call",
                    reasoning_summary="已显式检索知识库，下一步用问答工具综合结果并组织回答。",
                    updated_plan=["检索知识", "组织回答"],
                    next_tool_call=ToolCall(
                        tool_name="ask_llm_question",
                        arguments={
                            "question": session.goal,
                            "use_knowledge_base": knowledge_count > 0,
                            "knowledge_limit": int(session.constraints.get("knowledge_limit", 5)),
                        },
                        rationale="根据检索结果决定是否启用知识库增强回答。",
                    ),
                )

        if self._goal_mentions_image_analysis(session.goal):
            image_args = self._resolve_image_arguments(session)
            if image_args and "analyze_image_with_llm" in available_tool_names:
                return PlanDecision(
                    action_type="tool_call",
                    reasoning_summary="目标涉及图像分析，先调用多模态分析工具。",
                    updated_plan=["分析图片", "输出结果"],
                    next_tool_call=ToolCall(
                        tool_name="analyze_image_with_llm",
                        arguments={
                            "prompt": session.goal,
                            **image_args,
                            "use_knowledge_base": False,
                        },
                        rationale="先拿到图像分析结果，再判断是否结束。",
                    ),
                )

        if self._goal_mentions_import_document(session.goal):
            document = self._resolve_document_reference(session)
            if document and "import_feishu_document" in available_tool_names:
                return PlanDecision(
                    action_type="tool_call",
                    reasoning_summary="目标需要抓取文档，先把文档导入知识库。",
                    updated_plan=["导入文档", "按需要继续总结或回答"],
                    next_tool_call=ToolCall(
                        tool_name="import_feishu_document",
                        arguments={"document": document},
                        rationale="当前上下文已提供文档标识，可以直接导入。",
                    ),
                )

        if self._goal_mentions_import_chat(session.goal):
            chat_id = session.context.get("chat_id")
            if chat_id and "import_feishu_chat" in available_tool_names:
                return PlanDecision(
                    action_type="tool_call",
                    reasoning_summary="目标需要先抓取群聊，先把聊天记录导入知识库。",
                    updated_plan=["导入群聊", "按需要继续总结或回答"],
                    next_tool_call=ToolCall(
                        tool_name="import_feishu_chat",
                        arguments={
                            "chat_id": chat_id,
                            "limit": int(session.constraints.get("chat_limit", 100)),
                        },
                        rationale="补充后续分析所需上下文。",
                    ),
                )

        if self._goal_mentions_summary(session.goal):
            chat_id = session.context.get("chat_id")
            if chat_id and "summarize_feishu_chat" in available_tool_names:
                return PlanDecision(
                    action_type="tool_call",
                    reasoning_summary="目标涉及群聊总结，优先调用现成的群聊总结能力。",
                    updated_plan=["总结群聊", "按需要发送结果"],
                    next_tool_call=ToolCall(
                        tool_name="summarize_feishu_chat",
                        arguments={
                            "chat_id": chat_id,
                            "limit": int(session.constraints.get("chat_limit", 100)),
                            "use_knowledge_base": True,
                            "knowledge_query": session.goal,
                            "knowledge_limit": int(session.constraints.get("knowledge_limit", 5)),
                            "save_summary_to_knowledge_base": True,
                        },
                        rationale="利用现有摘要接口快速得到结构化总结。",
                    ),
                )

        if "search_knowledge" in available_tool_names and not self._has_recent_tool("search_knowledge", working_context):
            return PlanDecision(
                action_type="tool_call",
                reasoning_summary="先显式检索知识库，收集与当前目标最相关的上下文。",
                updated_plan=["检索知识", "组织回答"],
                next_tool_call=ToolCall(
                    tool_name="search_knowledge",
                    arguments={
                        "query": session.goal,
                        "limit": int(session.constraints.get("knowledge_limit", 5)),
                    },
                    rationale="先观察知识命中情况，再决定后续推理动作。",
                ),
            )

        if "ask_llm_question" in available_tool_names:
            return PlanDecision(
                action_type="tool_call",
                reasoning_summary="当前目标更适合走知识增强问答，调用问答工具生成回答。",
                updated_plan=["组织回答"],
                next_tool_call=ToolCall(
                    tool_name="ask_llm_question",
                    arguments={
                        "question": session.goal,
                        "use_knowledge_base": bool(working_context.knowledge_results),
                        "knowledge_limit": int(session.constraints.get("knowledge_limit", 5)),
                    },
                    rationale="在当前知识和上下文基础上生成结果。",
                ),
            )

        raise PlanningError("Planner could not determine a valid next action.")

    def _validate_llm_decision(self, decision: PlanDecision, available_tools: list[ToolSpec]) -> PlanDecision | None:
        available_tool_names = {tool.name for tool in available_tools}
        if decision.action_type == "tool_call":
            if not decision.next_tool_call:
                return None
            if decision.next_tool_call.tool_name not in available_tool_names:
                return None
        return decision

    def _parse_json_object(self, text: str) -> dict[str, Any] | None:
        stripped = text.strip()
        candidates = [stripped]
        fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL)
        if fenced_match:
            candidates.append(fenced_match.group(1))
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidates.append(stripped[start : end + 1])
        for candidate in candidates:
            try:
                return json.loads(candidate)
            except Exception:
                continue
        return None

    def _build_retry_decision(self, session: AgentSession, available_tool_names: set[str]) -> PlanDecision | None:
        retry_pending_call = session.working_memory.get("retry_pending_call") or {}
        if not retry_pending_call:
            return None
        tool_name = str(retry_pending_call.get("tool_name") or "").strip()
        if not tool_name or tool_name not in available_tool_names:
            return None
        retry_attempts = dict(session.working_memory.get("retry_attempt_counts") or {})
        max_retries = int(session.constraints.get("max_action_retries", 1))
        if int(retry_attempts.get(tool_name, 0)) > max_retries:
            return None
        return PlanDecision(
            action_type="tool_call",
            reasoning_summary=str(session.working_memory.get("retry_reason") or f"重试工具 {tool_name}。"),
            updated_plan=session.current_plan or ["重试上一步动作"],
            next_tool_call=ToolCall.model_validate(retry_pending_call),
        )

    def _build_missing_context_decision(self, session: AgentSession) -> PlanDecision | None:
        if self._goal_mentions_image_analysis(session.goal) and not self._resolve_image_arguments(session):
            return PlanDecision(
                action_type="ask_user",
                reasoning_summary="目标涉及图片或图像分析，但当前上下文里没有可用图片输入。",
                updated_plan=["获取图片上下文", "执行图像分析"],
                ask_user_message="请补充 image_url、image_key、message_id 或直接发送图片后重试。",
            )

        if self._goal_mentions_summary(session.goal) and not session.context.get("chat_id"):
            return PlanDecision(
                action_type="ask_user",
                reasoning_summary="目标涉及群聊总结，但当前没有 chat_id。",
                updated_plan=["获取目标群上下文", "总结群聊", "按需要发送结果"],
                ask_user_message="请告诉我要处理的 chat_id，或者直接在目标群里向机器人发起这个请求。",
            )

        if self._goal_mentions_send(session.goal):
            receive_id, _ = self._resolve_send_target(session)
            if not receive_id:
                return PlanDecision(
                    action_type="ask_user",
                    reasoning_summary="目标涉及发送动作，但当前没有可用的 receive_id。",
                    updated_plan=["获取发送目标", "生成内容", "发送结果"],
                    ask_user_message="请补充要发送到的 chat_id 或其他 receive_id。",
                )

        if self._goal_mentions_import_document(session.goal) and not self._resolve_document_reference(session):
            return PlanDecision(
                action_type="ask_user",
                reasoning_summary="目标涉及抓取文档，但当前没有提供文档链接或 token。",
                updated_plan=["获取文档标识", "导入文档", "继续处理文档内容"],
                ask_user_message="请补充飞书文档链接或文档 token。",
            )

        return None

    def _goal_mentions_send(self, goal: str) -> bool:
        return any(keyword in goal for keyword in ("发送", "发到", "回发", "send"))

    def _goal_mentions_summary(self, goal: str) -> bool:
        return any(keyword in goal for keyword in ("总结", "汇总", "纪要", "summary"))

    def _goal_mentions_import_chat(self, goal: str) -> bool:
        return any(keyword in goal for keyword in ("抓取群聊", "导入群聊", "同步群聊", "抓取当前群"))

    def _goal_mentions_import_document(self, goal: str) -> bool:
        return any(keyword in goal for keyword in ("抓取文档", "导入文档", "同步文档"))

    def _goal_mentions_image_analysis(self, goal: str) -> bool:
        lowered = goal.lower()
        return "图片" in goal or "图像" in goal or "image" in lowered

    def _resolve_send_target(self, session: AgentSession) -> tuple[str | None, str]:
        if session.context.get("receive_id"):
            return str(session.context["receive_id"]), str(session.context.get("receive_id_type", "chat_id"))
        if session.context.get("chat_id"):
            return str(session.context["chat_id"]), "chat_id"
        return None, "chat_id"

    def _resolve_image_arguments(self, session: AgentSession) -> dict[str, Any]:
        for key in ("image_url", "image_key", "message_id", "image_base64"):
            if session.context.get(key):
                arguments = {key: session.context[key]}
                if key == "image_base64":
                    arguments["image_mime_type"] = session.context.get("image_mime_type", "image/png")
                return arguments
        return {}

    def _resolve_document_reference(self, session: AgentSession) -> str | None:
        if session.context.get("document"):
            return str(session.context["document"])
        match = re.search(r"https?://\S+", session.goal)
        if match:
            return match.group(0)
        return None

    def _has_recent_tool(self, tool_name: str, working_context: WorkingContext) -> bool:
        return any(item.get("tool_name") == tool_name for item in working_context.recent_observations)

    def _recent_failed_tool(self, tool_name: str, working_context: WorkingContext) -> bool:
        for item in reversed(working_context.recent_observations):
            if item.get("tool_name") != tool_name:
                continue
            return not bool(item.get("success"))
        return False

    def _last_observation(self, working_context: WorkingContext) -> dict[str, Any] | None:
        if not working_context.recent_observations:
            return None
        return dict(working_context.recent_observations[-1])
# AI GC END

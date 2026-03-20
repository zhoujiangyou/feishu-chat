# AI GC START
from __future__ import annotations

import json
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
            return PlanDecision.model_validate(json.loads(response_text))
        except Exception:
            return None

    def _fallback_plan(
        self,
        session: AgentSession,
        working_context: WorkingContext,
        available_tools: list[ToolSpec],
    ) -> PlanDecision:
        if session.working_memory.get("message_sent"):
            final_answer = str(session.working_memory.get("latest_summary") or "消息已发送。")
            return PlanDecision(
                action_type="finish",
                reasoning_summary="目标中的发送动作已完成，结束本次会话。",
                updated_plan=session.current_plan or ["任务已完成"],
                final_answer=final_answer,
                done=True,
            )

        latest_summary = str(session.working_memory.get("latest_summary") or "").strip()
        latest_answer = str(session.working_memory.get("latest_answer") or "").strip()
        if latest_summary:
            if self._goal_mentions_send(session.goal):
                receive_id, receive_id_type = self._resolve_send_target(session)
                if receive_id:
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

        if latest_answer:
            return PlanDecision(
                action_type="finish",
                reasoning_summary="已经得到可直接返回的回答，结束当前会话。",
                updated_plan=session.current_plan or ["知识增强回答"],
                final_answer=latest_answer,
                done=True,
            )

        if self._goal_mentions_image_analysis(session.goal):
            image_args = self._resolve_image_arguments(session)
            if image_args:
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
            document = session.context.get("document")
            if document:
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
            if chat_id:
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
            if chat_id:
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

        if any(tool.name == "ask_llm_question" for tool in available_tools):
            return PlanDecision(
                action_type="tool_call",
                reasoning_summary="当前目标更适合走知识增强问答，先调用问答工具。",
                updated_plan=["知识检索增强问答"],
                next_tool_call=ToolCall(
                    tool_name="ask_llm_question",
                    arguments={
                        "question": session.goal,
                        "use_knowledge_base": True,
                        "knowledge_limit": int(session.constraints.get("knowledge_limit", 5)),
                    },
                    rationale="优先使用当前项目已有的问答链路。",
                ),
            )

        raise PlanningError("Planner could not determine a valid next action.")

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
# AI GC END

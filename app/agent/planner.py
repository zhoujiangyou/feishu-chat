# AI GC START
from __future__ import annotations

import json
import re
from typing import Any

from app import db
from app.agent.exceptions import PlanningError
from app.agent.prompts import build_planner_system_prompt, build_planner_user_prompt
from app.agent.subgoal_planner import SubgoalPlanner
from app.agent.task_classifier import TaskClassifier
from app.agent.types import (
    AgentSession,
    PlanDecision,
    SubgoalItem,
    SubgoalPlan,
    TaskClassification,
    ToolCall,
    ToolSpec,
    WorkingContext,
)
from app.services.llm import OpenAICompatibleLLM


class AgentPlanner:
    def __init__(
        self,
        *,
        task_classifier: TaskClassifier | None = None,
        subgoal_planner: SubgoalPlanner | None = None,
    ) -> None:
        self.task_classifier = task_classifier or TaskClassifier()
        self.subgoal_planner = subgoal_planner or SubgoalPlanner()

    async def decide_next_action(
        self,
        session: AgentSession,
        working_context: WorkingContext,
        available_tools: list[ToolSpec],
    ) -> PlanDecision:
        classification = self.task_classifier.classify(session, working_context, available_tools)
        subgoal_plan = self.subgoal_planner.build_plan(session, classification, working_context, available_tools)
        working_context.task_classification = classification
        working_context.subgoal_plan = subgoal_plan
        self._persist_planning_state(session, classification, subgoal_plan)

        available_tool_names = {tool.name for tool in available_tools}
        active_subgoal = self._get_active_subgoal(subgoal_plan)

        if session.working_memory.get("message_sent"):
            final_answer = self._resolve_final_content(session) or "消息已发送。"
            return PlanDecision(
                action_type="finish",
                reasoning_summary="目标中的发送动作已完成，结束本次会话。",
                updated_plan=session.current_plan,
                final_answer=final_answer,
                done=True,
            )

        retry_decision = self._build_retry_decision(session, available_tool_names)
        if retry_decision is not None:
            return retry_decision

        if active_subgoal and active_subgoal.status == "blocked":
            return PlanDecision(
                action_type="ask_user",
                reasoning_summary=f"当前活跃子目标被阻塞：{active_subgoal.title}",
                updated_plan=session.current_plan,
                ask_user_message=active_subgoal.ask_user_message or "当前缺少必要上下文，请补充后重试。",
            )

        llm_decision = await self._try_llm_planning(session, working_context, available_tools)
        if llm_decision is not None:
            return llm_decision

        if active_subgoal is not None:
            decision = self._build_decision_from_subgoal(session, active_subgoal, classification, working_context, available_tool_names)
            if decision is not None:
                return decision

        raise PlanningError("Planner could not determine a valid next action.")

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

    def _build_decision_from_subgoal(
        self,
        session: AgentSession,
        active_subgoal: SubgoalItem,
        classification: TaskClassification,
        working_context: WorkingContext,
        available_tool_names: set[str],
    ) -> PlanDecision | None:
        if active_subgoal.id == "search_knowledge" and "search_knowledge" in available_tool_names:
            latest_query = self._resolve_search_query(session, classification)
            session.working_memory["latest_query"] = latest_query
            return PlanDecision(
                action_type="tool_call",
                reasoning_summary="先围绕当前活跃子目标检索知识库，补充后续推理所需上下文。",
                updated_plan=session.current_plan,
                next_tool_call=ToolCall(
                    tool_name="search_knowledge",
                    arguments={
                        "query": latest_query,
                        "limit": int(session.constraints.get("knowledge_limit", 5)),
                    },
                    rationale=f"完成子目标：{active_subgoal.title}",
                ),
            )

        if active_subgoal.id == "compose_answer" and "ask_llm_question" in available_tool_names:
            question = self._resolve_compose_question(session, classification)
            return PlanDecision(
                action_type="tool_call",
                reasoning_summary="当前活跃子目标是整理回答，调用问答工具组织内容。",
                updated_plan=session.current_plan,
                next_tool_call=ToolCall(
                    tool_name="ask_llm_question",
                    arguments={
                        "question": question,
                        "use_knowledge_base": bool(working_context.knowledge_results or session.working_memory.get("latest_source")),
                        "knowledge_limit": int(session.constraints.get("knowledge_limit", 5)),
                    },
                    rationale=f"完成子目标：{active_subgoal.title}",
                ),
            )

        if active_subgoal.id == "summarize_chat" and "summarize_feishu_chat" in available_tool_names:
            chat_id = session.context.get("chat_id")
            if not chat_id:
                return PlanDecision(
                    action_type="ask_user",
                    reasoning_summary="当前活跃子目标需要 chat_id，但上下文中缺失。",
                    updated_plan=session.current_plan,
                    ask_user_message="请告诉我要处理的 chat_id，或者直接在目标群里向机器人发起这个请求。",
                )
            return PlanDecision(
                action_type="tool_call",
                reasoning_summary="当前活跃子目标是生成群聊总结，调用群聊总结工具。",
                updated_plan=session.current_plan,
                next_tool_call=ToolCall(
                    tool_name="summarize_feishu_chat",
                    arguments={
                        "chat_id": chat_id,
                        "limit": int(session.constraints.get("chat_limit", 100)),
                        "use_knowledge_base": True,
                        "knowledge_query": self._resolve_search_query(session, classification),
                        "knowledge_limit": int(session.constraints.get("knowledge_limit", 5)),
                        "save_summary_to_knowledge_base": True,
                    },
                    rationale=f"完成子目标：{active_subgoal.title}",
                ),
            )

        if active_subgoal.id == "send_message" and "send_feishu_message" in available_tool_names:
            receive_id, receive_id_type = self._resolve_send_target(session)
            if not receive_id:
                return PlanDecision(
                    action_type="ask_user",
                    reasoning_summary="当前活跃子目标需要发送目标，但上下文中缺失。",
                    updated_plan=session.current_plan,
                    ask_user_message="请补充要发送到的 chat_id 或其他 receive_id。",
                )
            text = self._resolve_send_text(session, classification)
            if not text:
                if "ask_llm_question" in available_tool_names:
                    question = self._resolve_compose_question(session, classification)
                    return PlanDecision(
                        action_type="tool_call",
                        reasoning_summary="发送前尚未得到可发送文本，先组织一段内容。",
                        updated_plan=session.current_plan,
                        next_tool_call=ToolCall(
                            tool_name="ask_llm_question",
                            arguments={
                                "question": question,
                                "use_knowledge_base": bool(working_context.knowledge_results),
                                "knowledge_limit": int(session.constraints.get("knowledge_limit", 5)),
                            },
                            rationale="为发送动作准备内容。",
                        ),
                    )
                return PlanDecision(
                    action_type="ask_user",
                    reasoning_summary="当前尚无可发送内容，需要用户补充更多上下文。",
                    updated_plan=session.current_plan,
                    ask_user_message="当前还没有可发送的内容，请补充更多说明后再试。",
                )
            return PlanDecision(
                action_type="tool_call",
                reasoning_summary="当前活跃子目标是发送结果，调用发送消息工具。",
                updated_plan=session.current_plan,
                next_tool_call=ToolCall(
                    tool_name="send_feishu_message",
                    arguments={"receive_id": receive_id, "receive_id_type": receive_id_type, "text": text},
                    rationale=f"完成子目标：{active_subgoal.title}",
                ),
            )

        if active_subgoal.id == "ingest_knowledge":
            ingest_tool = self._preferred_ingest_tool(classification)
            if ingest_tool and ingest_tool in available_tool_names:
                args = self._resolve_ingest_arguments(session, ingest_tool)
                if args is None:
                    return PlanDecision(
                        action_type="ask_user",
                        reasoning_summary="当前活跃子目标是导入知识，但缺少必要的导入参数。",
                        updated_plan=session.current_plan,
                        ask_user_message="请补充要导入的文档、群聊或图片标识。",
                    )
                return PlanDecision(
                    action_type="tool_call",
                    reasoning_summary="当前活跃子目标是导入知识，调用对应导入工具。",
                    updated_plan=session.current_plan,
                    next_tool_call=ToolCall(
                        tool_name=ingest_tool,
                        arguments=args,
                        rationale=f"完成子目标：{active_subgoal.title}",
                    ),
                )

        if active_subgoal.id == "analyze_image" and "analyze_image_with_llm" in available_tool_names:
            image_args = self._resolve_image_arguments(session)
            if not image_args:
                return PlanDecision(
                    action_type="ask_user",
                    reasoning_summary="当前活跃子目标需要图片输入，但上下文中缺失。",
                    updated_plan=session.current_plan,
                    ask_user_message="请补充 image_url、image_key、message_id 或直接发送图片。",
                )
            return PlanDecision(
                action_type="tool_call",
                reasoning_summary="当前活跃子目标是图像分析，调用多模态分析工具。",
                updated_plan=session.current_plan,
                next_tool_call=ToolCall(
                    tool_name="analyze_image_with_llm",
                    arguments={
                        "prompt": self._resolve_compose_question(session, classification),
                        **image_args,
                        "use_knowledge_base": False,
                    },
                    rationale=f"完成子目标：{active_subgoal.title}",
                ),
            )

        if active_subgoal.id == "finalize_answer":
            final_answer = self._resolve_final_content(session)
            if final_answer:
                return PlanDecision(
                    action_type="finish",
                    reasoning_summary="已完成所有关键子目标，结束当前会话。",
                    updated_plan=session.current_plan,
                    final_answer=final_answer,
                    done=True,
                )

        return None

    def _persist_planning_state(
        self,
        session: AgentSession,
        classification: TaskClassification,
        subgoal_plan: SubgoalPlan,
    ) -> None:
        session.working_memory["task_classification"] = classification.model_dump()
        session.working_memory["subgoal_plan"] = subgoal_plan.model_dump()
        session.current_plan = [item.title for item in subgoal_plan.items]

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

    def _resolve_search_query(self, session: AgentSession, classification: TaskClassification) -> str:
        if classification.task_type == "chat_summary":
            return str(session.context.get("chat_id") or session.goal)
        if classification.task_type == "knowledge_ingestion" and session.working_memory.get("latest_source"):
            source = session.working_memory["latest_source"] or {}
            return str(source.get("title") or session.goal)
        return str(session.goal)

    def _resolve_compose_question(self, session: AgentSession, classification: TaskClassification) -> str:
        if classification.task_type == "message_send":
            return f"请基于下面目标生成一段适合直接发送给飞书群或用户的中文消息：\n{session.goal}"
        if classification.task_type == "knowledge_ingestion" and session.working_memory.get("latest_source"):
            source = session.working_memory["latest_source"] or {}
            title = source.get("title") or "最新导入内容"
            return f"请基于知识库中刚导入的内容“{title}”完成下面目标：\n{session.goal}"
        return session.goal

    def _resolve_send_text(self, session: AgentSession, classification: TaskClassification) -> str:
        return str(session.working_memory.get("latest_summary") or session.working_memory.get("latest_answer") or "").strip()

    def _resolve_final_content(self, session: AgentSession) -> str:
        return str(session.final_answer or session.working_memory.get("latest_summary") or session.working_memory.get("latest_answer") or "").strip()

    def _preferred_ingest_tool(self, classification: TaskClassification) -> str | None:
        for tool_name in classification.preferred_tool_sequence:
            if tool_name.startswith("import_feishu_"):
                return tool_name
        return None

    def _resolve_ingest_arguments(self, session: AgentSession, tool_name: str) -> dict[str, Any] | None:
        if tool_name == "import_feishu_document":
            document = self._resolve_document_reference(session)
            return {"document": document} if document else None
        if tool_name == "import_feishu_chat":
            chat_id = session.context.get("chat_id")
            if not chat_id:
                return None
            return {"chat_id": chat_id, "limit": int(session.constraints.get("chat_limit", 100))}
        if tool_name == "import_feishu_image":
            image_args = self._resolve_image_arguments(session)
            return image_args or None
        return None

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

    def _get_active_subgoal(self, subgoal_plan: SubgoalPlan) -> SubgoalItem | None:
        if not subgoal_plan.active_subgoal_id:
            return None
        for item in subgoal_plan.items:
            if item.id == subgoal_plan.active_subgoal_id:
                return item
        return None
# AI GC END

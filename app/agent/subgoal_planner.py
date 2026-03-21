# AI GC START
from __future__ import annotations

import re

from app.agent.types import AgentSession, SubgoalItem, SubgoalPlan, TaskClassification, ToolSpec, WorkingContext


class SubgoalPlanner:
    def build_plan(
        self,
        session: AgentSession,
        classification: TaskClassification,
        working_context: WorkingContext,
        available_tools: list[ToolSpec],
    ) -> SubgoalPlan:
        if classification.task_type == "chat_summary":
            items = self._build_chat_summary_subgoals(session, classification)
        elif classification.task_type == "knowledge_ingestion":
            items = self._build_ingestion_subgoals(session, classification)
        elif classification.task_type == "image_analysis":
            items = self._build_image_subgoals(session, classification)
        elif classification.task_type == "message_send":
            items = self._build_message_send_subgoals(session, classification)
        else:
            items = self._build_qa_subgoals(session, classification, working_context)

        active_subgoal_id = None
        for item in items:
            if item.status in {"blocked", "active", "pending"}:
                active_subgoal_id = item.id
                if item.status == "pending":
                    item.status = "active"
                break

        return SubgoalPlan(
            task_type=classification.task_type,
            summary=classification.summary,
            items=items,
            active_subgoal_id=active_subgoal_id,
        )

    def _build_chat_summary_subgoals(
        self,
        session: AgentSession,
        classification: TaskClassification,
    ) -> list[SubgoalItem]:
        items: list[SubgoalItem] = []
        if "delegate_explore" in classification.secondary_intents:
            items.append(
                SubgoalItem(
                    id="explore_context",
                    title="探索上下文",
                    description="先用只读子 agent 梳理与当前任务相关的资料和上下文。",
                    preferred_tool="run_subagent",
                    status="completed" if session.working_memory.get("latest_subagent_summary") else "pending",
                    completion_hint="working_memory.latest_subagent_summary",
                )
            )
        items.extend(
            [
                SubgoalItem(
                id="collect_chat_context",
                title="确定目标群聊",
                description="确认用于总结的 chat_id。",
                status="completed" if session.context.get("chat_id") else "blocked",
                ask_user_message=None
                if session.context.get("chat_id")
                else "请告诉我要处理的 chat_id，或者直接在目标群里向机器人发起这个请求。",
                ),
                SubgoalItem(
                id="summarize_chat",
                title="总结群聊",
                description="调用群聊总结能力生成结构化结果。",
                preferred_tool="summarize_feishu_chat",
                status="completed" if session.working_memory.get("latest_summary") else "pending",
                completion_hint="working_memory.latest_summary",
                ),
            ]
        )
        if "send_message" in classification.secondary_intents:
            items.append(
                SubgoalItem(
                    id="send_message",
                    title="发送总结结果",
                    description="把总结结果发送到目标飞书会话。",
                    preferred_tool="send_feishu_message",
                    status="completed" if session.working_memory.get("message_sent") else "pending",
                    completion_hint="working_memory.message_sent",
                )
            )
        items.append(
            SubgoalItem(
                id="finalize_answer",
                title="整理最终回复",
                description="把当前任务整理成最终返回内容。",
                status="completed" if session.final_answer else "pending",
            )
        )
        return items

    def _build_ingestion_subgoals(
        self,
        session: AgentSession,
        classification: TaskClassification,
    ) -> list[SubgoalItem]:
        items: list[SubgoalItem] = []
        if "delegate_explore" in classification.secondary_intents:
            items.append(
                SubgoalItem(
                    id="explore_context",
                    title="探索上下文",
                    description="先用只读子 agent 梳理文档或知识背景。",
                    preferred_tool="run_subagent",
                    status="completed" if session.working_memory.get("latest_subagent_summary") else "pending",
                    completion_hint="working_memory.latest_subagent_summary",
                )
            )

        collect_item = SubgoalItem(
            id="collect_ingestion_context",
            title="确定导入对象",
            description="确认要导入的文档、群聊或图片标识。",
            status="completed",
        )
        ingest_tool = next((tool for tool in classification.preferred_tool_sequence if tool.startswith("import_feishu_")), None)
        if ingest_tool == "import_feishu_document" and not self._resolve_document_reference(session):
            collect_item.status = "blocked"
            collect_item.ask_user_message = "请补充飞书文档链接或文档 token。"
        elif ingest_tool == "import_feishu_chat" and not session.context.get("chat_id"):
            collect_item.status = "blocked"
            collect_item.ask_user_message = "请补充要导入的 chat_id，或者直接在目标群中发起请求。"
        elif ingest_tool == "import_feishu_image" and not self._has_image_input(session):
            collect_item.status = "blocked"
            collect_item.ask_user_message = "请补充 image_key、message_id、image_url 或直接发送图片。"

        items.append(collect_item)
        if ingest_tool:
            items.append(
                SubgoalItem(
                    id="ingest_knowledge",
                    title="导入知识",
                    description="把目标内容导入知识库。",
                    preferred_tool=ingest_tool,
                    status="completed" if session.working_memory.get("latest_source") else "pending",
                    completion_hint="working_memory.latest_source",
                )
            )

        if "compose_answer" in classification.secondary_intents:
            items.append(
                SubgoalItem(
                    id="compose_answer",
                    title="整理导入结果",
                    description="基于导入后的知识组织一段回答或总结。",
                    preferred_tool="ask_llm_question",
                    status="completed" if self._has_final_content(session) else "pending",
                    completion_hint="working_memory.latest_answer/latest_summary",
                )
            )

        if "send_message" in classification.secondary_intents:
            items.append(
                SubgoalItem(
                    id="send_message",
                    title="发送结果",
                    description="把整理好的内容发送到目标会话。",
                    preferred_tool="send_feishu_message",
                    status="completed" if session.working_memory.get("message_sent") else "pending",
                    completion_hint="working_memory.message_sent",
                )
            )

        items.append(
            SubgoalItem(
                id="finalize_answer",
                title="整理最终回复",
                description="把导入或后续处理结果整理成最终返回内容。",
                status="completed" if session.final_answer else "pending",
            )
        )
        return items

    def _build_image_subgoals(
        self,
        session: AgentSession,
        classification: TaskClassification,
    ) -> list[SubgoalItem]:
        items = [
            SubgoalItem(
                id="collect_image_context",
                title="确定图片输入",
                description="确认图片来源，例如 image_url、image_key、message_id 或直接图片消息。",
                status="completed" if self._has_image_input(session) else "blocked",
                ask_user_message=None
                if self._has_image_input(session)
                else "请补充 image_url、image_key、message_id 或直接发送图片。",
            ),
            SubgoalItem(
                id="analyze_image",
                title="分析图片",
                description="调用图像分析能力。",
                preferred_tool="analyze_image_with_llm",
                status="completed" if self._has_final_content(session) else "pending",
                completion_hint="working_memory.latest_answer/latest_summary",
            ),
        ]
        if "send_message" in classification.secondary_intents:
            items.append(
                SubgoalItem(
                    id="send_message",
                    title="发送分析结果",
                    description="把图片分析结果发送到目标会话。",
                    preferred_tool="send_feishu_message",
                    status="completed" if session.working_memory.get("message_sent") else "pending",
                )
            )
        items.append(
            SubgoalItem(
                id="finalize_answer",
                title="整理最终回复",
                description="把图片分析结果整理为最终输出。",
                status="completed" if session.final_answer else "pending",
            )
        )
        return items

    def _build_message_send_subgoals(
        self,
        session: AgentSession,
        classification: TaskClassification,
    ) -> list[SubgoalItem]:
        return [
            SubgoalItem(
                id="collect_send_target",
                title="确定发送目标",
                description="确认要发送到的 receive_id 或当前 chat_id。",
                status="completed" if self._has_send_target(session) else "blocked",
                ask_user_message=None if self._has_send_target(session) else "请补充要发送到的 chat_id 或其他 receive_id。",
            ),
            SubgoalItem(
                id="compose_answer",
                title="生成待发送内容",
                description="先组织一段待发送的内容。",
                preferred_tool="ask_llm_question",
                status="completed" if self._has_final_content(session) else "pending",
            ),
            SubgoalItem(
                id="send_message",
                title="发送消息",
                description="把内容发送到目标飞书会话。",
                preferred_tool="send_feishu_message",
                status="completed" if session.working_memory.get("message_sent") else "pending",
            ),
            SubgoalItem(
                id="finalize_answer",
                title="整理最终回复",
                description="把执行结果整理成最终输出。",
                status="completed" if session.final_answer else "pending",
            ),
        ]

    def _build_qa_subgoals(
        self,
        session: AgentSession,
        classification: TaskClassification,
        working_context: WorkingContext,
    ) -> list[SubgoalItem]:
        has_searched = any(item.get("tool_name") == "search_knowledge" for item in working_context.recent_observations)
        items: list[SubgoalItem] = []
        if "delegate_explore" in classification.secondary_intents:
            items.append(
                SubgoalItem(
                    id="explore_context",
                    title="探索上下文",
                    description="先用只读子 agent 搜索知识源并梳理相关上下文。",
                    preferred_tool="run_subagent",
                    status="completed" if session.working_memory.get("latest_subagent_summary") else "pending",
                    completion_hint="working_memory.latest_subagent_summary",
                )
            )
        items.extend(
            [
                SubgoalItem(
                id="search_knowledge",
                title="检索知识",
                description="先检索当前知识库中的相关上下文。",
                preferred_tool="search_knowledge",
                status="completed" if has_searched else "pending",
                completion_hint="search_knowledge observation",
                ),
                SubgoalItem(
                id="compose_answer",
                title="组织回答",
                description="基于知识检索结果和模型能力生成回答。",
                preferred_tool="ask_llm_question",
                status="completed" if self._has_final_content(session) else "pending",
                ),
            ]
        )
        if "send_message" in classification.secondary_intents:
            items.append(
                SubgoalItem(
                    id="send_message",
                    title="发送结果",
                    description="把回答内容发送到目标飞书会话。",
                    preferred_tool="send_feishu_message",
                    status="completed" if session.working_memory.get("message_sent") else "pending",
                )
            )
        items.append(
            SubgoalItem(
                id="finalize_answer",
                title="整理最终回复",
                description="整理任务最终输出。",
                status="completed" if session.final_answer else "pending",
            )
        )
        return items

    def _resolve_document_reference(self, session: AgentSession) -> str | None:
        if session.context.get("document"):
            return str(session.context["document"])
        match = re.search(r"https?://\S+", session.goal)
        if match:
            return match.group(0)
        return None

    def _has_image_input(self, session: AgentSession) -> bool:
        return any(session.context.get(key) for key in ("image_url", "image_key", "message_id", "image_base64"))

    def _has_send_target(self, session: AgentSession) -> bool:
        return bool(session.context.get("receive_id") or session.context.get("chat_id"))

    def _has_final_content(self, session: AgentSession) -> bool:
        return bool(session.working_memory.get("latest_answer") or session.working_memory.get("latest_summary"))
# AI GC END

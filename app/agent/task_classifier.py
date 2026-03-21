# AI GC START
from __future__ import annotations

from app.agent.types import AgentSession, TaskClassification, ToolSpec, WorkingContext


class TaskClassifier:
    def classify(
        self,
        session: AgentSession,
        working_context: WorkingContext,
        available_tools: list[ToolSpec],
    ) -> TaskClassification:
        goal = session.goal.strip()
        lowered = goal.lower()
        secondary_intents: list[str] = []
        required_context: list[str] = []
        preferred_tool_sequence: list[str] = []

        mentions_send = any(keyword in goal for keyword in ("发送", "发到", "回发", "send"))
        mentions_summary = any(keyword in goal for keyword in ("总结", "汇总", "纪要", "summary"))
        mentions_image = "图片" in goal or "图像" in goal or "image" in lowered
        mentions_document = any(keyword in goal for keyword in ("文档", "doc", "wiki"))
        mentions_chat_import = any(keyword in goal for keyword in ("抓取群聊", "导入群聊", "同步群聊", "抓取当前群"))
        mentions_import = any(keyword in goal for keyword in ("抓取", "导入", "同步"))
        mentions_research = any(keyword in goal for keyword in ("研究", "分析一下", "梳理一下", "看看", "调研", "explore"))

        if mentions_send:
            secondary_intents.append("send_message")
            required_context.append("send_target")

        if mentions_summary and (session.context.get("chat_id") or "群" in goal or "chat" in lowered):
            required_context.append("chat_id")
            preferred_tool_sequence.extend(["summarize_feishu_chat"])
            if mentions_send:
                preferred_tool_sequence.append("send_feishu_message")
            if mentions_research:
                secondary_intents.append("delegate_explore")
            return TaskClassification(
                task_type="chat_summary",
                summary="需要围绕飞书群聊生成总结，并按需发送结果。",
                confidence=0.9,
                secondary_intents=self._dedupe(secondary_intents),
                required_context=self._dedupe(required_context),
                preferred_tool_sequence=self._dedupe(preferred_tool_sequence),
            )

        if mentions_image:
            required_context.append("image_input")
            preferred_tool_sequence.extend(["analyze_image_with_llm"])
            if mentions_send:
                preferred_tool_sequence.append("send_feishu_message")
            return TaskClassification(
                task_type="image_analysis",
                summary="需要基于图片或图像输入进行分析。",
                confidence=0.9,
                secondary_intents=self._dedupe(secondary_intents),
                required_context=self._dedupe(required_context),
                preferred_tool_sequence=self._dedupe(preferred_tool_sequence),
            )

        if mentions_import:
            preferred_tool_sequence.append(self._choose_ingestion_tool(goal, mentions_document, mentions_chat_import, mentions_image))
            if mentions_summary or any(keyword in goal for keyword in ("分析", "回答", "说明", "提炼", "梳理")):
                secondary_intents.append("compose_answer")
                preferred_tool_sequence.append("ask_llm_question")
            if mentions_send:
                preferred_tool_sequence.append("send_feishu_message")
            if mentions_document:
                required_context.append("document")
                secondary_intents.append("delegate_explore")
            elif mentions_chat_import:
                required_context.append("chat_id")
            elif mentions_image:
                required_context.append("image_input")
            return TaskClassification(
                task_type="knowledge_ingestion",
                summary="需要先把外部内容导入知识库，再按需继续推理或发送。",
                confidence=0.85,
                secondary_intents=self._dedupe(secondary_intents),
                required_context=self._dedupe(required_context),
                preferred_tool_sequence=self._dedupe(preferred_tool_sequence),
            )

        if mentions_send and not mentions_summary:
            preferred_tool_sequence.extend(["ask_llm_question", "send_feishu_message"])
            return TaskClassification(
                task_type="message_send",
                summary="需要先生成一段待发送内容，再发送到目标会话。",
                confidence=0.8,
                secondary_intents=self._dedupe(secondary_intents),
                required_context=self._dedupe(required_context),
                preferred_tool_sequence=self._dedupe(preferred_tool_sequence),
            )

        preferred_tool_sequence.extend(["search_knowledge", "ask_llm_question"])
        if mentions_research or mentions_document:
            secondary_intents.append("delegate_explore")
        return TaskClassification(
            task_type="knowledge_qa",
            summary="优先检索知识库，再结合模型生成回答。",
            confidence=0.75,
            secondary_intents=self._dedupe(secondary_intents),
            required_context=self._dedupe(required_context),
            preferred_tool_sequence=self._dedupe(preferred_tool_sequence),
        )

    def _choose_ingestion_tool(
        self,
        goal: str,
        mentions_document: bool,
        mentions_chat_import: bool,
        mentions_image: bool,
    ) -> str:
        if mentions_document:
            return "import_feishu_document"
        if mentions_chat_import:
            return "import_feishu_chat"
        if mentions_image:
            return "import_feishu_image"
        if "群" in goal:
            return "import_feishu_chat"
        return "import_feishu_document"

    def _dedupe(self, items: list[str]) -> list[str]:
        ordered: list[str] = []
        for item in items:
            if item not in ordered:
                ordered.append(item)
        return ordered
# AI GC END

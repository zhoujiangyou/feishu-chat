# AI GC START
from __future__ import annotations

from typing import Any

from app import db
from app.agent.exceptions import ToolExecutionError
from app.agent.types import AgentSession, Observation, ToolCall, ToolSpec
from app.services.service_api import FeishuChatServiceApiClient


TOOL_REGISTRY: list[ToolSpec] = [
    ToolSpec(
        name="search_knowledge",
        description="Search the service knowledge base for relevant chunks.",
        category="knowledge",
        risk_level="read_only",
        input_schema={"query": "str", "limit": "int"},
        idempotent=True,
    ),
    ToolSpec(
        name="list_knowledge_sources",
        description="List imported knowledge sources.",
        category="knowledge",
        risk_level="read_only",
        input_schema={},
        idempotent=True,
    ),
    ToolSpec(
        name="import_feishu_chat",
        description="Import Feishu chat history into the knowledge base.",
        category="knowledge_ingestion",
        risk_level="write",
        input_schema={"chat_id": "str", "limit": "int"},
    ),
    ToolSpec(
        name="import_feishu_document",
        description="Import a Feishu document into the knowledge base.",
        category="knowledge_ingestion",
        risk_level="write",
        input_schema={"document": "str", "title": "str?"},
    ),
    ToolSpec(
        name="import_feishu_image",
        description="Import a Feishu image into the knowledge base.",
        category="knowledge_ingestion",
        risk_level="write",
        input_schema={"image_key": "str?", "message_id": "str?", "title": "str?"},
    ),
    ToolSpec(
        name="ask_llm_question",
        description="Ask the configured model with optional knowledge-base retrieval.",
        category="reasoning",
        risk_level="read_only",
        input_schema={"question": "str", "use_knowledge_base": "bool", "knowledge_limit": "int"},
    ),
    ToolSpec(
        name="analyze_image_with_llm",
        description="Analyze an image with the configured multimodal model.",
        category="reasoning",
        risk_level="read_only",
        input_schema={"prompt": "str", "image_url": "str?", "image_key": "str?", "message_id": "str?"},
    ),
    ToolSpec(
        name="summarize_feishu_chat",
        description="Summarize a Feishu group chat through the configured model.",
        category="reasoning",
        risk_level="read_only",
        input_schema={"chat_id": "str", "limit": "int"},
    ),
    ToolSpec(
        name="send_feishu_message",
        description="Send a text message to a Feishu group or user.",
        category="action",
        risk_level="side_effect",
        input_schema={"receive_id": "str", "text": "str", "receive_id_type": "str?"},
        side_effect=True,
    ),
]


class AgentToolBridge:
    def __init__(self, api_client: FeishuChatServiceApiClient | None = None) -> None:
        self.api_client = api_client or FeishuChatServiceApiClient()

    def list_available_tools(self, session: AgentSession) -> list[ToolSpec]:
        if session.policy_config.get("allow_send_feishu_message", False):
            return TOOL_REGISTRY
        return [tool for tool in TOOL_REGISTRY if tool.name != "send_feishu_message"]

    def get_tool_spec(self, tool_name: str) -> ToolSpec:
        for tool in TOOL_REGISTRY:
            if tool.name == tool_name:
                return tool
        raise ToolExecutionError(f"Unsupported tool: {tool_name}")

    async def execute(self, session: AgentSession, call: ToolCall, step_index: int) -> Observation:
        try:
            result = await self._dispatch(session=session, call=call)
            return Observation(
                step_index=step_index,
                tool_name=call.tool_name,
                arguments=call.arguments,
                success=True,
                result=result,
                error=None,
                summary=self._summarize_result(call.tool_name, result),
                created_at=db.utcnow(),
            )
        except Exception as exc:
            return Observation(
                step_index=step_index,
                tool_name=call.tool_name,
                arguments=call.arguments,
                success=False,
                result=None,
                error=str(exc),
                summary=f"Tool '{call.tool_name}' execution failed: {exc}",
                created_at=db.utcnow(),
            )

    async def _dispatch(self, *, session: AgentSession, call: ToolCall) -> dict[str, Any]:
        args = dict(call.arguments)
        if call.tool_name == "search_knowledge":
            return await self.api_client.search_knowledge(service_id=session.service_id, **args)
        if call.tool_name == "list_knowledge_sources":
            return await self.api_client.list_knowledge_sources(session.service_id)
        if call.tool_name == "import_feishu_chat":
            return await self.api_client.import_feishu_chat(service_id=session.service_id, **args)
        if call.tool_name == "import_feishu_document":
            return await self.api_client.import_feishu_document(service_id=session.service_id, **args)
        if call.tool_name == "import_feishu_image":
            return await self.api_client.import_feishu_image(service_id=session.service_id, **args)
        if call.tool_name == "ask_llm_question":
            return await self.api_client.ask_with_llm(service_id=session.service_id, **args)
        if call.tool_name == "analyze_image_with_llm":
            return await self.api_client.analyze_image_with_llm(service_id=session.service_id, **args)
        if call.tool_name == "summarize_feishu_chat":
            return await self.api_client.summarize_feishu_chat(service_id=session.service_id, **args)
        if call.tool_name == "send_feishu_message":
            return await self.api_client.send_feishu_message(service_id=session.service_id, **args)
        raise ToolExecutionError(f"Unsupported tool: {call.tool_name}")

    def _summarize_result(self, tool_name: str, result: dict[str, Any]) -> str:
        if tool_name == "search_knowledge":
            return f"Knowledge search returned {len(result.get('results', []))} results."
        if tool_name == "list_knowledge_sources":
            return f"Listed {len(result.get('items', []))} knowledge sources."
        if tool_name == "ask_llm_question":
            return "LLM question answered successfully."
        if tool_name == "analyze_image_with_llm":
            return "Image analysis completed successfully."
        if tool_name == "summarize_feishu_chat":
            return "Chat summary generated successfully."
        if tool_name == "send_feishu_message":
            return "Feishu message sent successfully."
        if tool_name.startswith("import_feishu_"):
            source = result.get("source", {})
            title = source.get("title") or tool_name
            return f"Knowledge source imported successfully: {title}."
        return f"Tool '{tool_name}' executed successfully."
# AI GC END

# AI GC START
from __future__ import annotations

from app.agent.exceptions import PolicyDeniedError
from app.agent.types import AgentSession, ToolSpec


DEFAULT_ALLOWED_TOOLS = {
    "search_knowledge",
    "list_knowledge_sources",
    "import_feishu_chat",
    "import_feishu_document",
    "import_feishu_image",
    "ask_llm_question",
    "analyze_image_with_llm",
    "summarize_feishu_chat",
}


class AgentExecutionPolicy:
    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}

    def is_tool_visible(self, session: AgentSession, tool: ToolSpec) -> bool:
        if tool.name == "send_feishu_message":
            return bool(self._merged_config(session).get("allow_send_feishu_message", False))
        return tool.name in DEFAULT_ALLOWED_TOOLS

    def ensure_tool_allowed(self, session: AgentSession, tool: ToolSpec) -> None:
        merged = self._merged_config(session)
        if tool.risk_level == "dangerous":
            raise PolicyDeniedError(f"Tool '{tool.name}' is denied by default.")
        if tool.name == "send_feishu_message" and not merged.get("allow_send_feishu_message", False):
            raise PolicyDeniedError("send_feishu_message is not allowed for this session.")

    def ensure_step_budget(self, session: AgentSession) -> None:
        if session.step_count >= session.max_steps:
            raise PolicyDeniedError("Session exceeded max_steps.")

    def _merged_config(self, session: AgentSession) -> dict:
        merged = dict(self.config)
        merged.update(session.policy_config)
        return merged
# AI GC END

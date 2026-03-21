# AI GC START
from __future__ import annotations

from app.agent.exceptions import PolicyDeniedError
from app.agent.permission_engine import PermissionEngine
from app.agent.types import AgentSession, PermissionRule, ToolCall, ToolSpec


DEFAULT_ALLOWED_TOOLS = {
    "search_knowledge",
    "list_knowledge_sources",
    "import_feishu_chat",
    "import_feishu_document",
    "import_feishu_image",
    "ask_llm_question",
    "analyze_image_with_llm",
    "summarize_feishu_chat",
    "run_subagent",
}


class AgentExecutionPolicy:
    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}
        self.permission_engine = PermissionEngine()

    def is_tool_visible(self, session: AgentSession, tool: ToolSpec) -> bool:
        try:
            action = self.evaluate_tool_action(session=session, tool=tool, pattern=self._tool_pattern(session, tool.name))
        except PolicyDeniedError:
            return False
        return action != "deny"

    def ensure_tool_allowed(self, session: AgentSession, tool: ToolSpec) -> None:
        action = self.evaluate_tool_action(session=session, tool=tool, pattern=self._tool_pattern(session, tool.name))
        if action == "deny":
            raise PolicyDeniedError(f"Tool '{tool.name}' is denied by policy.")

    def ensure_step_budget(self, session: AgentSession) -> None:
        if session.step_count >= session.max_steps:
            raise PolicyDeniedError("Session exceeded max_steps.")

    def ensure_tool_call_allowed(self, session: AgentSession, call: ToolCall, tool: ToolSpec) -> None:
        pattern = self._tool_pattern(session, call.tool_name, call.arguments)
        action = self.evaluate_tool_action(session=session, tool=tool, pattern=pattern)
        if action == "deny":
            raise PolicyDeniedError(f"Tool call '{call.tool_name}' is denied for pattern '{pattern}'.")

    def evaluate_tool_action(self, *, session: AgentSession, tool: ToolSpec, pattern: str) -> str:
        merged = self._merged_config(session)
        rulesets = [self._default_rules(session), self._config_rules(merged)]
        decision = self.permission_engine.evaluate(
            permission=tool.name,
            pattern=pattern,
            rulesets=rulesets,
        )
        if tool.risk_level == "dangerous" and decision.action != "allow":
            raise PolicyDeniedError(f"Tool '{tool.name}' requires explicit allow.")
        return decision.action

    def _merged_config(self, session: AgentSession) -> dict:
        merged = dict(self.config)
        merged.update(session.policy_config)
        return merged

    def _default_rules(self, session: AgentSession) -> list[PermissionRule]:
        rules: list[PermissionRule] = [
            PermissionRule(permission="*", pattern="*", action="deny"),
        ]
        rules.extend(PermissionRule(permission=tool_name, pattern="*", action="allow") for tool_name in DEFAULT_ALLOWED_TOOLS)
        if self._merged_config(session).get("allow_send_feishu_message", False):
            rules.append(PermissionRule(permission="send_feishu_message", pattern="*", action="allow"))
        else:
            rules.append(PermissionRule(permission="send_feishu_message", pattern="*", action="deny"))
        return rules

    def _config_rules(self, merged: dict) -> list[PermissionRule]:
        raw_rules = merged.get("permission_rules") or []
        rules: list[PermissionRule] = []
        for raw_rule in raw_rules:
            try:
                rules.append(PermissionRule.model_validate(raw_rule))
            except Exception:
                continue
        return rules

    def _tool_pattern(self, session: AgentSession, tool_name: str, arguments: dict | None = None) -> str:
        args = arguments or {}
        if tool_name == "send_feishu_message":
            receive_id = args.get("receive_id") or session.context.get("receive_id") or session.context.get("chat_id") or "*"
            return f"receive_id:{receive_id}"
        if tool_name in {"summarize_feishu_chat", "import_feishu_chat"}:
            chat_id = args.get("chat_id") or session.context.get("chat_id") or "*"
            return f"chat_id:{chat_id}"
        if tool_name == "import_feishu_document":
            document = args.get("document") or session.context.get("document") or "*"
            return f"document:{document}"
        if tool_name in {"analyze_image_with_llm", "import_feishu_image"}:
            image_ref = (
                args.get("image_key")
                or args.get("message_id")
                or session.context.get("image_key")
                or session.context.get("message_id")
                or "*"
            )
            return f"image:{image_ref}"
        return "*"
# AI GC END

# AI GC START
from __future__ import annotations

from app.agent.session_store import AgentSessionStore
from app.agent.subagent_registry import SubagentRegistry
from app.agent.types import AgentRunResult, SubagentRunRequest, SubagentRunResult


class SubagentManager:
    def __init__(
        self,
        *,
        runtime_factory=None,
        session_store: AgentSessionStore | None = None,
        registry: SubagentRegistry | None = None,
    ) -> None:
        self.runtime_factory = runtime_factory
        self.session_store = session_store or AgentSessionStore()
        self.registry = registry or SubagentRegistry()

    async def run(self, request: SubagentRunRequest) -> SubagentRunResult:
        spec = self.registry.get(request.subagent_name)
        if not spec:
            raise ValueError(f"Unknown subagent: {request.subagent_name}")
        child_session = self.session_store.create_session(
            service_id=request.service_id,
            goal=request.goal,
            parent_session_id=request.parent_session_id,
            agent_type=spec.name,
            context=request.context,
            constraints=request.constraints,
            policy_config={
                "subagent_name": spec.name,
                "readonly": spec.readonly,
                "allowed_tool_names": spec.preferred_tool_names,
                "allow_send_feishu_message": False if spec.readonly else request.context.get("allow_send_feishu_message", False),
            },
        )

        runtime = self.runtime_factory() if self.runtime_factory else self._default_runtime()
        result: AgentRunResult = await runtime.resume(child_session.id)
        summary = self._build_summary(result)
        return SubagentRunResult(session=result.session, summary=summary, logs=result.logs)

    def _build_summary(self, result: AgentRunResult) -> str:
        session = result.session
        if session.final_answer:
            return session.final_answer
        if session.working_memory.get("latest_answer"):
            return str(session.working_memory["latest_answer"])
        if session.working_memory.get("latest_summary"):
            return str(session.working_memory["latest_summary"])
        if result.logs and result.logs[-1].observation:
            return str(result.logs[-1].observation.get("summary") or "Subagent completed.")
        return "Subagent completed."

    def _default_runtime(self):
        from app.agent.runtime import AgentRuntime

        return AgentRuntime()
# AI GC END

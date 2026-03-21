# AI GC START
from __future__ import annotations

import json

from app import db
from app.agent.exceptions import DoomLoopDetectedError
from app.agent.policy import AgentExecutionPolicy
from app.agent.tool_bridge import AgentToolBridge
from app.agent.types import AgentSession, AgentStepLog, Observation, PlanDecision, ToolCall, VerificationResult
from app.agent.verifier import AgentVerifier


class SessionProcessor:
    DOOM_LOOP_THRESHOLD = 3

    def __init__(
        self,
        *,
        tool_bridge: AgentToolBridge,
        verifier: AgentVerifier,
        policy: AgentExecutionPolicy,
    ) -> None:
        self.tool_bridge = tool_bridge
        self.verifier = verifier
        self.policy = policy

    async def process_step(
        self,
        *,
        session: AgentSession,
        decision: PlanDecision,
        step_index: int,
        previous_logs: list[AgentStepLog],
    ) -> tuple[AgentStepLog, Observation | None, VerificationResult | None]:
        step_log = AgentStepLog(
            session_id=session.id,
            step_index=step_index,
            plan_decision=decision.model_dump(),
            observation=None,
            verification=None,
            processor_state={"status": "planned"},
            created_at=db.utcnow(),
        )

        if decision.action_type != "tool_call" or not decision.next_tool_call:
            step_log.processor_state = {"status": "no_tool_execution"}
            return step_log, None, None

        tool_spec = self.tool_bridge.get_tool_spec(decision.next_tool_call.tool_name)
        self.policy.ensure_tool_allowed(session, tool_spec)
        self.policy.ensure_tool_call_allowed(session, decision.next_tool_call, tool_spec)
        self._guard_doom_loop(previous_logs=previous_logs, call=decision.next_tool_call)

        step_log.processor_state = {"status": "running", "tool_name": decision.next_tool_call.tool_name}
        observation = await self.tool_bridge.execute(
            session=session,
            call=decision.next_tool_call,
            step_index=step_index,
        )
        verification = await self.verifier.verify_step(session=session, observation=observation)

        step_log.observation = observation.model_dump()
        step_log.verification = verification.model_dump()
        step_log.processor_state = {
            "status": "completed" if observation.success else "error",
            "tool_name": observation.tool_name,
            "doom_loop_checked": True,
            "verification_outcome": self._verification_outcome(verification),
        }
        return step_log, observation, verification

    def _guard_doom_loop(self, *, previous_logs: list[AgentStepLog], call: ToolCall) -> None:
        recent_tool_logs = [log for log in previous_logs if log.observation][-self.DOOM_LOOP_THRESHOLD :]
        if len(recent_tool_logs) < self.DOOM_LOOP_THRESHOLD:
            return

        serialized_call = self._serialize_call(call)
        for log in recent_tool_logs:
            observation = log.observation or {}
            if observation.get("tool_name") != call.tool_name:
                return
            if self._serialize_arguments(observation.get("arguments") or {}) != serialized_call[1]:
                return
        raise DoomLoopDetectedError(
            f"Detected repeated tool call doom loop for '{call.tool_name}' with identical arguments."
        )

    def _serialize_call(self, call: ToolCall) -> tuple[str, str]:
        return call.tool_name, self._serialize_arguments(call.arguments)

    def _serialize_arguments(self, arguments: dict) -> str:
        return json.dumps(arguments, ensure_ascii=False, sort_keys=True)

    def _verification_outcome(self, verification: VerificationResult) -> str:
        if verification.goal_completed:
            return "goal_completed"
        if verification.should_wait_for_input:
            return "waiting_input"
        if verification.should_retry:
            return "retry"
        if verification.should_abort:
            return "abort"
        if verification.should_replan:
            return "replan"
        return "continue"
# AI GC END

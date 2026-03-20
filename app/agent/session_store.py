# AI GC START
from __future__ import annotations

from typing import Any

from app import db
from app.agent.exceptions import AgentSessionNotFoundError
from app.agent.types import AgentSession, AgentStepLog


class AgentSessionStore:
    def create_session(
        self,
        *,
        service_id: str,
        goal: str,
        context: dict[str, Any] | None = None,
        constraints: dict[str, Any] | None = None,
        policy_config: dict[str, Any] | None = None,
    ) -> AgentSession:
        constraints = constraints or {}
        session = db.create_agent_session(
            service_id=service_id,
            goal=goal,
            status="created",
            step_count=0,
            max_steps=int(constraints.get("max_steps", 6)),
            context=context or {},
            constraints=constraints,
            policy_config=policy_config or {},
            current_plan=[],
            working_memory={},
        )
        return AgentSession.model_validate(session)

    def get_session(self, session_id: str) -> AgentSession:
        session = db.get_agent_session(session_id)
        if not session:
            raise AgentSessionNotFoundError(f"Agent session not found: {session_id}")
        return AgentSession.model_validate(session)

    def update_session(self, session: AgentSession) -> AgentSession:
        updated = db.update_agent_session(
            session.id,
            status=session.status,
            step_count=session.step_count,
            max_steps=session.max_steps,
            context=session.context,
            constraints=session.constraints,
            policy_config=session.policy_config,
            current_plan=session.current_plan,
            working_memory=session.working_memory,
            final_answer=session.final_answer,
            failure_reason=session.failure_reason,
        )
        return AgentSession.model_validate(updated)

    def append_step_log(self, step_log: AgentStepLog) -> AgentStepLog:
        created = db.create_agent_step_log(
            session_id=step_log.session_id,
            step_index=step_log.step_index,
            plan_decision=step_log.plan_decision,
            observation=step_log.observation,
            verification=step_log.verification,
        )
        return AgentStepLog.model_validate(created)

    def list_step_logs(self, session_id: str) -> list[AgentStepLog]:
        return [AgentStepLog.model_validate(item) for item in db.list_agent_step_logs(session_id)]

    def mark_completed(self, session: AgentSession, final_answer: str) -> AgentSession:
        session.status = "completed"
        session.final_answer = final_answer
        session.failure_reason = None
        return self.update_session(session)

    def mark_failed(self, session: AgentSession, reason: str) -> AgentSession:
        session.status = "failed"
        session.failure_reason = reason
        return self.update_session(session)

    def mark_cancelled(self, session: AgentSession) -> AgentSession:
        session.status = "cancelled"
        return self.update_session(session)
# AI GC END

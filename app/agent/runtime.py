# AI GC START
from __future__ import annotations

from app import db
from app.agent.exceptions import AgentRuntimeError, PolicyDeniedError
from app.agent.memory import AgentMemoryManager
from app.agent.planner import AgentPlanner
from app.agent.policy import AgentExecutionPolicy
from app.agent.session_store import AgentSessionStore
from app.agent.tool_bridge import AgentToolBridge
from app.agent.types import AgentRunResult, AgentSession, AgentStepLog, Observation
from app.agent.verifier import AgentVerifier


class AgentRuntime:
    def __init__(
        self,
        *,
        session_store: AgentSessionStore | None = None,
        planner: AgentPlanner | None = None,
        verifier: AgentVerifier | None = None,
        tool_bridge: AgentToolBridge | None = None,
        memory_manager: AgentMemoryManager | None = None,
        policy: AgentExecutionPolicy | None = None,
    ) -> None:
        self.session_store = session_store or AgentSessionStore()
        self.planner = planner or AgentPlanner()
        self.verifier = verifier or AgentVerifier()
        self.tool_bridge = tool_bridge or AgentToolBridge()
        self.memory_manager = memory_manager or AgentMemoryManager()
        self.policy = policy or AgentExecutionPolicy()

    async def run(
        self,
        *,
        service_id: str,
        goal: str,
        context: dict | None = None,
        constraints: dict | None = None,
        policy_config: dict | None = None,
    ) -> AgentRunResult:
        session = self.session_store.create_session(
            service_id=service_id,
            goal=goal,
            context=context or {},
            constraints=constraints or {},
            policy_config=policy_config or {},
        )
        return await self._run_session(session.id)

    async def resume(self, session_id: str) -> AgentRunResult:
        return await self._run_session(session_id)

    def get_session(self, session_id: str) -> AgentSession:
        return self.session_store.get_session(session_id)

    def get_logs(self, session_id: str) -> list[AgentStepLog]:
        return self.session_store.list_step_logs(session_id)

    def cancel(self, session_id: str) -> AgentSession:
        session = self.session_store.get_session(session_id)
        return self.session_store.mark_cancelled(session)

    async def _run_session(self, session_id: str) -> AgentRunResult:
        session = self.session_store.get_session(session_id)
        if session.status in {"completed", "failed", "cancelled"}:
            return AgentRunResult(session=session, logs=self.session_store.list_step_logs(session.id))

        session.status = "running"
        session = self.session_store.update_session(session)

        try:
            while session.step_count < session.max_steps:
                self.policy.ensure_step_budget(session)
                step_logs = self.session_store.list_step_logs(session.id)
                recent_observations = self._extract_recent_observations(step_logs)
                working_context = self.memory_manager.build_working_context(session, recent_observations)
                available_tools = self.tool_bridge.list_available_tools(session)
                decision = await self.planner.decide_next_action(session, working_context, available_tools)
                if decision.updated_plan:
                    session.current_plan = decision.updated_plan
                session = self.session_store.update_session(session)

                step_log = AgentStepLog(
                    session_id=session.id,
                    step_index=session.step_count,
                    plan_decision=decision.model_dump(),
                    observation=None,
                    verification=None,
                    created_at=db.utcnow(),
                )

                if decision.action_type == "finish":
                    self.session_store.append_step_log(step_log)
                    session = self.session_store.mark_completed(
                        session,
                        decision.final_answer or session.final_answer or "Task completed.",
                    )
                    return self._finalize(session)

                if decision.action_type == "ask_user":
                    session.working_memory["pending_user_prompt"] = decision.ask_user_message or decision.reasoning_summary
                    session.status = "waiting_input"
                    session = self.session_store.update_session(session)
                    self.session_store.append_step_log(step_log)
                    return AgentRunResult(session=session, logs=self.session_store.list_step_logs(session.id))

                if decision.action_type == "wait":
                    session.status = "paused"
                    session = self.session_store.update_session(session)
                    self.session_store.append_step_log(step_log)
                    return AgentRunResult(session=session, logs=self.session_store.list_step_logs(session.id))

                if decision.action_type == "fail" or not decision.next_tool_call:
                    self.session_store.append_step_log(step_log)
                    session = self.session_store.mark_failed(session, decision.reasoning_summary)
                    return AgentRunResult(session=session, logs=self.session_store.list_step_logs(session.id))

                tool_spec = self.tool_bridge.get_tool_spec(decision.next_tool_call.tool_name)
                self.policy.ensure_tool_allowed(session, tool_spec)

                observation = await self.tool_bridge.execute(
                    session=session,
                    call=decision.next_tool_call,
                    step_index=session.step_count,
                )
                verification = await self.verifier.verify_step(session=session, observation=observation)
                step_log.observation = observation.model_dump()
                step_log.verification = verification.model_dump()
                self.session_store.append_step_log(step_log)

                session = self.memory_manager.merge_observation(session, observation)
                session.step_count += 1

                if verification.goal_completed:
                    session.working_memory.pop("pending_user_prompt", None)
                    session = self.session_store.mark_completed(
                        session,
                        verification.final_answer or self._build_final_answer(session, observation),
                    )
                    return self._finalize(session)

                if verification.should_wait_for_input:
                    session.working_memory["pending_user_prompt"] = (
                        verification.ask_user_message or verification.verifier_summary
                    )
                    session.status = "waiting_input"
                    session = self.session_store.update_session(session)
                    return AgentRunResult(session=session, logs=self.session_store.list_step_logs(session.id))

                if verification.should_retry and decision.next_tool_call:
                    session.working_memory["retry_pending_call"] = decision.next_tool_call.model_dump()
                    session.working_memory["retry_reason"] = verification.verifier_summary
                    session = self.session_store.update_session(session)
                    continue

                if verification.should_abort:
                    session = self.session_store.mark_failed(session, verification.verifier_summary)
                    return AgentRunResult(session=session, logs=self.session_store.list_step_logs(session.id))

                session.working_memory.pop("pending_user_prompt", None)
                session = self.session_store.update_session(session)

            session = self.session_store.mark_failed(session, "Session exceeded max_steps without completion.")
            return AgentRunResult(session=session, logs=self.session_store.list_step_logs(session.id))
        except PolicyDeniedError as exc:
            session = self.session_store.mark_failed(session, str(exc))
            return AgentRunResult(session=session, logs=self.session_store.list_step_logs(session.id))
        except AgentRuntimeError:
            raise
        except Exception as exc:
            session = self.session_store.mark_failed(session, str(exc))
            return AgentRunResult(session=session, logs=self.session_store.list_step_logs(session.id))

    def _finalize(self, session: AgentSession) -> AgentRunResult:
        logs = self.session_store.list_step_logs(session.id)
        try:
            if session.policy_config.get("persist_agent_episode", True):
                self.memory_manager.persist_episode_summary(session, logs)
        except Exception:
            pass
        return AgentRunResult(session=session, logs=logs)

    def _extract_recent_observations(self, step_logs: list[AgentStepLog]) -> list[Observation]:
        observations: list[Observation] = []
        for step_log in step_logs:
            if step_log.observation:
                observations.append(Observation.model_validate(step_log.observation))
        return observations

    def _build_final_answer(self, session: AgentSession, observation: Observation) -> str:
        return str(
            session.working_memory.get("latest_summary")
            or session.working_memory.get("latest_answer")
            or observation.summary
        )
# AI GC END

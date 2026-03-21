# AI GC START
from __future__ import annotations

from app.agent.types import AgentSession, AgentStepLog, Observation, SubgoalPlan, TaskClassification, WorkingContext
from app.services.knowledge_base import KnowledgeBaseService


class AgentMemoryManager:
    def __init__(self) -> None:
        self.kb = KnowledgeBaseService()

    def retrieve_goal_knowledge(self, session: AgentSession, limit: int | None = None) -> list[dict]:
        knowledge_limit = limit or int(session.constraints.get("knowledge_limit", 5))
        query = str(session.working_memory.get("latest_query") or session.goal).strip()
        if not query:
            return []
        return self.kb.search(service_id=session.service_id, query=query, limit=knowledge_limit)

    def build_working_context(
        self,
        session: AgentSession,
        recent_observations: list[Observation],
    ) -> WorkingContext:
        task_classification = None
        subgoal_plan = None
        if session.working_memory.get("task_classification"):
            task_classification = TaskClassification.model_validate(session.working_memory["task_classification"])
        if session.working_memory.get("subgoal_plan"):
            subgoal_plan = SubgoalPlan.model_validate(session.working_memory["subgoal_plan"])
        return WorkingContext(
            knowledge_results=self.retrieve_goal_knowledge(session),
            recent_observations=[item.model_dump() for item in recent_observations[-5:]],
            working_memory=dict(session.working_memory),
            task_classification=task_classification,
            subgoal_plan=subgoal_plan,
        )

    def merge_observation(self, session: AgentSession, observation: Observation) -> AgentSession:
        working_memory = dict(session.working_memory)
        tool_history = list(working_memory.get("tool_history") or [])
        tool_history.append(
            {
                "tool_name": observation.tool_name,
                "success": observation.success,
                "error": observation.error,
                "step_index": observation.step_index,
            }
        )
        working_memory["tool_history"] = tool_history[-10:]
        working_memory["last_tool_name"] = observation.tool_name
        working_memory["last_tool_success"] = observation.success
        working_memory["last_tool_summary"] = observation.summary
        working_memory["last_tool_result"] = observation.result
        working_memory["last_error"] = observation.error

        failure_counts = dict(working_memory.get("tool_failure_counts") or {})
        success_counts = dict(working_memory.get("tool_success_counts") or {})
        if observation.success:
            success_counts[observation.tool_name] = int(success_counts.get(observation.tool_name, 0)) + 1
            failure_counts.setdefault(observation.tool_name, 0)
        else:
            failure_counts[observation.tool_name] = int(failure_counts.get(observation.tool_name, 0)) + 1
        working_memory["tool_failure_counts"] = failure_counts
        working_memory["tool_success_counts"] = success_counts

        if observation.tool_name == "ask_llm_question" and observation.result:
            answer = observation.result.get("answer")
            if answer:
                working_memory["latest_answer"] = answer

        if observation.tool_name == "analyze_image_with_llm" and observation.result:
            answer = observation.result.get("answer")
            if answer:
                working_memory["latest_answer"] = answer

        if observation.tool_name == "summarize_feishu_chat" and observation.result:
            summary = observation.result.get("summary")
            if summary:
                working_memory["latest_summary"] = summary

        if observation.tool_name == "search_knowledge":
            working_memory["latest_knowledge_query"] = observation.arguments.get("query")
            if observation.result:
                working_memory["latest_knowledge_count"] = len(observation.result.get("results", []))

        if observation.tool_name.startswith("import_feishu_") and observation.result:
            source = observation.result.get("source")
            if source:
                working_memory["latest_source"] = source

        if observation.tool_name == "send_feishu_message" and observation.success:
            working_memory["message_sent"] = True
            if observation.result:
                working_memory["send_result"] = observation.result

        if observation.tool_name == "run_subagent" and observation.result:
            summary = observation.result.get("summary")
            child_session_id = observation.result.get("session_id")
            child_agent_type = observation.result.get("subagent_name")
            if summary:
                working_memory["latest_subagent_summary"] = summary
            if child_session_id:
                working_memory["latest_subagent_session_id"] = child_session_id
            if child_agent_type:
                working_memory["latest_subagent_type"] = child_agent_type

        retry_attempts = dict(working_memory.get("retry_attempt_counts") or {})
        if observation.success:
            retry_attempts.pop(observation.tool_name, None)
            if (
                working_memory.get("retry_pending_call")
                and (working_memory["retry_pending_call"] or {}).get("tool_name") == observation.tool_name
            ):
                working_memory.pop("retry_pending_call", None)
                working_memory.pop("retry_reason", None)
        else:
            retry_attempts[observation.tool_name] = int(retry_attempts.get(observation.tool_name, 0)) + 1
        working_memory["retry_attempt_counts"] = retry_attempts

        session.working_memory = working_memory
        return session

    def persist_episode_summary(self, session: AgentSession, step_logs: list[AgentStepLog]) -> None:
        if not session.final_answer:
            return
        lines = [
            f"目标：{session.goal}",
            f"状态：{session.status}",
            f"最终结果：{session.final_answer}",
            "",
            "执行步骤：",
        ]
        for step_log in step_logs:
            decision = step_log.plan_decision
            action_type = decision.get("action_type", "unknown")
            reasoning = decision.get("reasoning_summary", "")
            observation = step_log.observation or {}
            tool_name = observation.get("tool_name")
            summary = observation.get("summary")
            lines.append(
                f"- step={step_log.step_index} action={action_type} reasoning={reasoning}"
                + (f" tool={tool_name}" if tool_name else "")
                + (f" summary={summary}" if summary else "")
            )
        self.kb.ingest_generated_artifact(
            service_id=session.service_id,
            title=f"Agent Episode {session.id}",
            content="\n".join(lines),
            source_type="agent_episode",
            external_id=session.id,
            metadata={"goal": session.goal, "status": session.status},
        )
# AI GC END

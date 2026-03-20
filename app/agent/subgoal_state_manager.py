# AI GC START
from __future__ import annotations

from app.agent.types import AgentSession, Observation, SubgoalItem, SubgoalPlan, VerificationResult


class SubgoalStateManager:
    def refresh_plan(self, session: AgentSession, template_plan: SubgoalPlan, existing_plan: SubgoalPlan | None = None) -> SubgoalPlan:
        existing_by_id = {item.id: item for item in (existing_plan.items if existing_plan else [])}
        refreshed_items: list[SubgoalItem] = []

        for template_item in template_plan.items:
            item = template_item.model_copy(deep=True)
            existing_item = existing_by_id.get(item.id)
            if existing_item and existing_item.status == "completed":
                item.status = "completed"
                if existing_item.ask_user_message and not item.ask_user_message:
                    item.ask_user_message = existing_item.ask_user_message
            refreshed_items.append(self._apply_session_state(session, item))

        active_subgoal_id = None
        for item in refreshed_items:
            if item.status in {"blocked", "pending", "active"}:
                active_subgoal_id = item.id
                if item.status == "pending":
                    item.status = "active"
                break

        return SubgoalPlan(
            task_type=template_plan.task_type,
            summary=template_plan.summary,
            items=refreshed_items,
            active_subgoal_id=active_subgoal_id,
        )

    def advance_after_step(
        self,
        session: AgentSession,
        *,
        observation: Observation | None,
        verification: VerificationResult | None,
    ) -> AgentSession:
        existing_plan_raw = session.working_memory.get("subgoal_plan")
        if not existing_plan_raw:
            return session

        plan = SubgoalPlan.model_validate(existing_plan_raw)
        plan = self.refresh_plan(session, plan, existing_plan=plan)

        active_item = self._get_active_item(plan)
        if active_item and observation and observation.success and active_item.preferred_tool == observation.tool_name:
            active_item.status = "completed"
            session.working_memory["last_completed_subgoal_id"] = active_item.id

        if active_item and verification and verification.should_wait_for_input:
            active_item.status = "blocked"
            if verification.ask_user_message:
                active_item.ask_user_message = verification.ask_user_message
            session.working_memory["last_blocked_subgoal_id"] = active_item.id

        if verification and verification.goal_completed:
            for item in plan.items:
                if item.id == "finalize_answer":
                    item.status = "completed"
            session.working_memory["last_completed_subgoal_id"] = "finalize_answer"

        active_subgoal_id = None
        for item in plan.items:
            if item.status in {"blocked", "pending", "active"}:
                active_subgoal_id = item.id
                if item.status == "pending":
                    item.status = "active"
                break
        plan.active_subgoal_id = active_subgoal_id
        session.working_memory["subgoal_plan"] = plan.model_dump()
        return session

    def _apply_session_state(self, session: AgentSession, item: SubgoalItem) -> SubgoalItem:
        if item.id == "collect_chat_context":
            if session.context.get("chat_id"):
                item.status = "completed"
            else:
                item.status = "blocked"
        elif item.id == "collect_send_target":
            if session.context.get("receive_id") or session.context.get("chat_id"):
                item.status = "completed"
            else:
                item.status = "blocked"
        elif item.id == "collect_image_context":
            if any(session.context.get(key) for key in ("image_url", "image_key", "message_id", "image_base64")):
                item.status = "completed"
            else:
                item.status = "blocked"
        elif item.id == "collect_ingestion_context":
            if session.context.get("document") or session.context.get("chat_id") or any(
                session.context.get(key) for key in ("image_url", "image_key", "message_id", "image_base64")
            ):
                item.status = "completed"
            else:
                item.status = "blocked"
        elif item.id == "search_knowledge":
            if self._has_successful_tool(session, "search_knowledge"):
                item.status = "completed"
        elif item.id == "summarize_chat":
            if session.working_memory.get("latest_summary"):
                item.status = "completed"
        elif item.id == "compose_answer":
            if session.working_memory.get("latest_answer") or session.working_memory.get("latest_summary"):
                item.status = "completed"
        elif item.id == "ingest_knowledge":
            if session.working_memory.get("latest_source"):
                item.status = "completed"
        elif item.id == "send_message":
            if session.working_memory.get("message_sent"):
                item.status = "completed"
        elif item.id == "analyze_image":
            if session.working_memory.get("latest_answer"):
                item.status = "completed"
        elif item.id == "finalize_answer":
            if session.final_answer:
                item.status = "completed"
        return item

    def _has_successful_tool(self, session: AgentSession, tool_name: str) -> bool:
        for item in reversed(list(session.working_memory.get("tool_history") or [])):
            if item.get("tool_name") != tool_name:
                continue
            return bool(item.get("success"))
        return False

    def _get_active_item(self, plan: SubgoalPlan) -> SubgoalItem | None:
        if not plan.active_subgoal_id:
            return None
        for item in plan.items:
            if item.id == plan.active_subgoal_id:
                return item
        return None
# AI GC END

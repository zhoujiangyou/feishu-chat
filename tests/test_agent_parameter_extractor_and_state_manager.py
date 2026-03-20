# AI GC START
from __future__ import annotations

from app import db
from app.agent.parameter_extractor import ParameterExtractor
from app.agent.subgoal_planner import SubgoalPlanner
from app.agent.subgoal_state_manager import SubgoalStateManager
from app.agent.task_classifier import TaskClassifier
from app.agent.types import AgentSession, Observation, ToolSpec, VerificationResult, WorkingContext


def _build_session(*, goal: str, context: dict | None = None, working_memory: dict | None = None) -> AgentSession:
    now = db.utcnow()
    return AgentSession(
        id="sess_state_123",
        service_id="svc_123",
        goal=goal,
        status="running",
        step_count=0,
        max_steps=6,
        context=context or {},
        constraints={"max_steps": 6, "knowledge_limit": 5, "chat_limit": 20},
        policy_config={"allow_send_feishu_message": True},
        current_plan=[],
        working_memory=working_memory or {},
        final_answer=None,
        failure_reason=None,
        created_at=now,
        updated_at=now,
    )


def test_parameter_extractor_parses_targets_and_limits() -> None:
    extractor = ParameterExtractor()
    context, constraints = extractor.extract(
        goal="请把最近 30 条群聊总结发到群 oc_target_123，并参考文档 https://example.feishu.cn/docx/abc 和图片 img_demo",
        context={"chat_id": "oc_current_456"},
        constraints={},
    )
    assert context["chat_id"] == "oc_current_456"
    assert context["receive_id"] == "oc_target_123"
    assert context["receive_id_type"] == "chat_id"
    assert context["document"] == "https://example.feishu.cn/docx/abc"
    assert context["image_key"] == "img_demo"
    assert constraints["chat_limit"] == 30


def test_parameter_extractor_uses_current_chat_for_send_to_current_group() -> None:
    extractor = ParameterExtractor()
    context, constraints = extractor.extract(
        goal="请总结并发到当前群",
        context={"chat_id": "oc_group_123"},
        constraints={},
    )
    assert context["receive_id"] == "oc_group_123"
    assert context["receive_id_type"] == "chat_id"
    assert constraints == {}


def test_subgoal_state_manager_advances_to_next_subgoal_after_summary() -> None:
    session = _build_session(
        goal="请总结当前群并发送结果",
        context={"chat_id": "oc_group_123", "receive_id": "oc_group_123", "receive_id_type": "chat_id"},
        working_memory={"latest_summary": "这里是总结结果"},
    )
    classifier = TaskClassifier().classify(
        session,
        WorkingContext(),
        available_tools=[
            ToolSpec(name="summarize_feishu_chat", description="summary", category="reasoning", risk_level="read_only"),
            ToolSpec(name="send_feishu_message", description="send", category="action", risk_level="side_effect"),
        ],
    )
    plan = SubgoalPlanner().build_plan(session, classifier, WorkingContext(), available_tools=[])
    session.working_memory["subgoal_plan"] = plan.model_dump()
    manager = SubgoalStateManager()
    updated = manager.advance_after_step(
        session,
        observation=Observation(
            step_index=0,
            tool_name="summarize_feishu_chat",
            arguments={"chat_id": "oc_group_123"},
            success=True,
            result={"summary": "这里是总结结果"},
            summary="summary ready",
            created_at=db.utcnow(),
        ),
        verification=VerificationResult(
            step_success=True,
            goal_completed=False,
            should_replan=True,
            verifier_summary="摘要已生成，需要继续发送。",
        ),
    )
    refreshed_plan = updated.working_memory["subgoal_plan"]
    assert refreshed_plan["active_subgoal_id"] == "send_message"
    statuses = {item["id"]: item["status"] for item in refreshed_plan["items"]}
    assert statuses["summarize_chat"] == "completed"
    assert statuses["send_message"] == "active"
# AI GC END

# AI GC START
from __future__ import annotations

import app.agent.planner as planner_module
import pytest
from app import db
from app.agent.planner import AgentPlanner
from app.agent.subgoal_planner import SubgoalPlanner
from app.agent.task_classifier import TaskClassifier
from app.agent.types import AgentSession, ToolSpec, WorkingContext


class FakeInvalidClassifierLLM:
    def __init__(self, service: dict[str, str]) -> None:
        self.service = service

    async def chat_completion_text(self, *, messages, temperature: float = 0.1) -> str:  # type: ignore[no-untyped-def]
        return "invalid-json"


def _create_service() -> dict[str, str]:
    db.init_db()
    return db.create_service(
        {
            "name": "task-classifier-demo",
            "feishu_app_id": "cli_demo",
            "feishu_app_secret": "secret",
            "verification_token": "verify",
            "encrypt_key": "encrypt",
            "llm_base_url": "https://example.com/v1",
            "llm_api_key": "sk-demo",
            "llm_model": "test-model",
            "llm_system_prompt": "你是测试助手。",
        }
    )


def _build_session(service_id: str, *, goal: str, context: dict | None = None, working_memory: dict | None = None) -> AgentSession:
    now = db.utcnow()
    return AgentSession(
        id="sess_classifier_123",
        service_id=service_id,
        goal=goal,
        status="running",
        step_count=0,
        max_steps=6,
        context=context or {},
        constraints={"max_steps": 6, "knowledge_limit": 5, "chat_limit": 20, "max_action_retries": 1},
        policy_config={"allow_send_feishu_message": True},
        current_plan=[],
        working_memory=working_memory or {},
        final_answer=None,
        failure_reason=None,
        created_at=now,
        updated_at=now,
    )


def test_task_classifier_identifies_chat_summary_with_send_intent(tmp_path) -> None:
    db.DB_PATH = tmp_path / "classifier-summary.db"
    service = _create_service()
    session = _build_session(service["id"], goal="请总结当前群的重点并发送到群里", context={"chat_id": "oc_demo"})
    classifier = TaskClassifier()
    result = classifier.classify(
        session,
        WorkingContext(),
        available_tools=[
            ToolSpec(name="summarize_feishu_chat", description="summary", category="reasoning", risk_level="read_only"),
            ToolSpec(name="send_feishu_message", description="send", category="action", risk_level="side_effect"),
        ],
    )
    assert result.task_type == "chat_summary"
    assert "send_message" in result.secondary_intents
    assert "chat_id" in result.required_context
    assert result.preferred_tool_sequence[:2] == ["summarize_feishu_chat", "send_feishu_message"]


def test_subgoal_planner_marks_missing_chat_context_as_blocked(tmp_path) -> None:
    db.DB_PATH = tmp_path / "subgoal-blocked.db"
    service = _create_service()
    session = _build_session(service["id"], goal="请总结这个群的重点并发送结果")
    classifier = TaskClassifier().classify(
        session,
        WorkingContext(),
        available_tools=[
            ToolSpec(name="summarize_feishu_chat", description="summary", category="reasoning", risk_level="read_only"),
            ToolSpec(name="send_feishu_message", description="send", category="action", risk_level="side_effect"),
        ],
    )
    plan = SubgoalPlanner().build_plan(session, classifier, WorkingContext(), available_tools=[])
    assert plan.active_subgoal_id == "collect_chat_context"
    assert plan.items[0].status == "blocked"
    assert plan.items[0].ask_user_message is not None


@pytest.mark.anyio
async def test_planner_uses_task_classification_and_subgoal_plan_for_qa(tmp_path, monkeypatch) -> None:
    db.DB_PATH = tmp_path / "planner-qa.db"
    service = _create_service()
    monkeypatch.setattr(planner_module, "OpenAICompatibleLLM", FakeInvalidClassifierLLM)
    session = _build_session(service["id"], goal="这个系统现在支持哪些 MCP 能力？")
    planner = AgentPlanner()
    decision = await planner.decide_next_action(
        session=session,
        working_context=WorkingContext(),
        available_tools=[
            ToolSpec(name="search_knowledge", description="search", category="knowledge", risk_level="read_only"),
            ToolSpec(name="ask_llm_question", description="ask", category="reasoning", risk_level="read_only"),
        ],
    )
    assert decision.action_type == "tool_call"
    assert decision.next_tool_call is not None
    assert decision.next_tool_call.tool_name == "search_knowledge"
    assert session.working_memory["task_classification"]["task_type"] == "knowledge_qa"
    assert session.working_memory["subgoal_plan"]["active_subgoal_id"] == "search_knowledge"
    assert session.current_plan[:2] == ["检索知识", "组织回答"]
# AI GC END

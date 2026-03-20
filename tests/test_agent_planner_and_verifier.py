# AI GC START
from __future__ import annotations

import app.agent.planner as planner_module
import pytest
from app import db
from app.agent.planner import AgentPlanner
from app.agent.types import AgentSession, Observation, ToolCall, ToolSpec, WorkingContext
from app.agent.verifier import AgentVerifier


class FakeInvalidPlannerLLM:
    def __init__(self, service: dict[str, str]) -> None:
        self.service = service

    async def chat_completion_text(self, *, messages, temperature: float = 0.1) -> str:  # type: ignore[no-untyped-def]
        return "not-json"


def _create_service() -> dict[str, str]:
    db.init_db()
    return db.create_service(
        {
            "name": "planner-demo",
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
        id="sess_planner_123",
        service_id=service_id,
        goal=goal,
        status="running",
        step_count=0,
        max_steps=6,
        context=context or {},
        constraints={"max_steps": 6, "knowledge_limit": 5, "chat_limit": 20, "max_action_retries": 1},
        policy_config={},
        current_plan=[],
        working_memory=working_memory or {},
        final_answer=None,
        failure_reason=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.anyio
async def test_planner_asks_user_for_missing_chat_context(tmp_path, monkeypatch) -> None:
    db.DB_PATH = tmp_path / "planner-missing-chat.db"
    service = _create_service()
    monkeypatch.setattr(planner_module, "OpenAICompatibleLLM", FakeInvalidPlannerLLM)
    planner = AgentPlanner()
    session = _build_session(service["id"], goal="请总结这个群的重点并发送结果")
    decision = await planner.decide_next_action(
        session=session,
        working_context=WorkingContext(),
        available_tools=[
            ToolSpec(
                name="summarize_feishu_chat",
                description="summarize",
                category="reasoning",
                risk_level="read_only",
            ),
            ToolSpec(
                name="send_feishu_message",
                description="send",
                category="action",
                risk_level="side_effect",
                side_effect=True,
            ),
        ],
    )
    assert decision.action_type == "ask_user"
    assert decision.ask_user_message is not None
    assert "chat_id" in decision.ask_user_message or "目标群" in decision.ask_user_message


@pytest.mark.anyio
async def test_planner_reuses_retry_pending_call_when_retry_budget_allows(tmp_path, monkeypatch) -> None:
    db.DB_PATH = tmp_path / "planner-retry.db"
    service = _create_service()
    monkeypatch.setattr(planner_module, "OpenAICompatibleLLM", FakeInvalidPlannerLLM)
    planner = AgentPlanner()
    session = _build_session(
        service["id"],
        goal="请发送项目提醒",
        context={"receive_id": "oc_demo", "receive_id_type": "chat_id"},
        working_memory={
            "retry_pending_call": {
                "tool_name": "send_feishu_message",
                "arguments": {"receive_id": "oc_demo", "receive_id_type": "chat_id", "text": "提醒"},
                "rationale": "retry",
            },
            "retry_reason": "网络超时，重试发送动作。",
            "retry_attempt_counts": {"send_feishu_message": 1},
        },
    )
    decision = await planner.decide_next_action(
        session=session,
        working_context=WorkingContext(),
        available_tools=[
            ToolSpec(
                name="send_feishu_message",
                description="send",
                category="action",
                risk_level="side_effect",
                side_effect=True,
            )
        ],
    )
    assert decision.action_type == "tool_call"
    assert decision.next_tool_call is not None
    assert decision.next_tool_call.tool_name == "send_feishu_message"
    assert decision.next_tool_call.arguments["receive_id"] == "oc_demo"


@pytest.mark.anyio
async def test_verifier_requests_user_input_on_missing_context_error() -> None:
    verifier = AgentVerifier()
    session = _build_session("svc_123", goal="请总结当前群")
    observation = Observation(
        step_index=0,
        tool_name="summarize_feishu_chat",
        arguments={},
        success=False,
        result=None,
        error="Current chat_id is missing for summarize_current_chat.",
        summary="failed",
        created_at=db.utcnow(),
    )
    result = await verifier.verify_step(session=session, observation=observation)
    assert result.should_wait_for_input is True
    assert result.ask_user_message is not None


@pytest.mark.anyio
async def test_verifier_marks_transient_error_as_retryable() -> None:
    verifier = AgentVerifier()
    session = _build_session("svc_123", goal="请发送项目提醒")
    observation = Observation(
        step_index=0,
        tool_name="send_feishu_message",
        arguments={},
        success=False,
        result=None,
        error="Connection timeout while sending message",
        summary="failed",
        created_at=db.utcnow(),
    )
    result = await verifier.verify_step(session=session, observation=observation)
    assert result.should_retry is True
    assert result.goal_completed is False
# AI GC END

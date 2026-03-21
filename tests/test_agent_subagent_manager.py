# AI GC START
from __future__ import annotations

import app.agent.planner as planner_module
import pytest
from app import db
from app.agent.planner import AgentPlanner
from app.agent.session_store import AgentSessionStore
from app.agent.subagent_manager import SubagentManager
from app.agent.types import AgentRunResult, AgentSession, AgentStepLog, ToolSpec, WorkingContext


class FakePlannerLlm:
    def __init__(self, service: dict[str, str]) -> None:
        self.service = service

    async def chat_completion_text(self, *, messages, temperature: float = 0.1) -> str:  # type: ignore[no-untyped-def]
        return "not-json"


class FakeChildRuntime:
    def __init__(self) -> None:
        self.seen_session_ids: list[str] = []

    async def resume(self, session_id: str) -> AgentRunResult:
        self.seen_session_ids.append(session_id)
        session = AgentSession(
            id=session_id,
            service_id="svc_123",
            goal="子 agent 研究任务",
            parent_session_id="parent_123",
            agent_type="explore",
            status="completed",
            step_count=1,
            max_steps=3,
            context={"chat_id": "oc_group_123"},
            constraints={},
            policy_config={"subagent_name": "explore", "readonly": True},
            current_plan=["检索资料"],
            working_memory={"latest_answer": "这是 explore 子 agent 的研究结论。"},
            final_answer="这是 explore 子 agent 的研究结论。",
            failure_reason=None,
            created_at=db.utcnow(),
            updated_at=db.utcnow(),
        )
        logs = [
            AgentStepLog(
                session_id=session.id,
                step_index=0,
                plan_decision={"action_type": "tool_call"},
                observation={"tool_name": "search_knowledge", "summary": "subagent summary"},
                verification={"goal_completed": True},
                processor_state={"status": "completed"},
                created_at=db.utcnow(),
            )
        ]
        return AgentRunResult(session=session, logs=logs)


def _create_service() -> dict[str, str]:
    db.init_db()
    return db.create_service(
        {
            "name": "subagent-demo",
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


def _build_parent_session(service_id: str) -> AgentSession:
    now = db.utcnow()
    return AgentSession(
        id="parent_123",
        service_id=service_id,
        goal="帮我研究一下当前知识库里有哪些关键信息",
        parent_session_id=None,
        agent_type="primary",
        status="running",
        step_count=0,
        max_steps=6,
        context={"chat_id": "oc_group_123"},
        constraints={"max_steps": 6, "knowledge_limit": 5},
        policy_config={"allow_send_feishu_message": True},
        current_plan=[],
        working_memory={},
        final_answer=None,
        failure_reason=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.anyio
async def test_subagent_manager_creates_child_session_and_returns_summary(tmp_path) -> None:
    db.DB_PATH = tmp_path / "subagent-manager.db"
    service = _create_service()
    runtime = FakeChildRuntime()
    manager = SubagentManager(
        runtime_factory=lambda: runtime,  # type: ignore[arg-type]
        session_store=AgentSessionStore(),
    )

    result = await manager.run(
        parent_session_id="parent_123",
        service_id=service["id"],
        subagent_name="explore",
        goal="请先研究这个任务的相关上下文",
        context={"chat_id": "oc_group_123"},
        constraints={"max_steps": 3},
    )

    assert result.summary == "这是 explore 子 agent 的研究结论。"
    assert result.session.parent_session_id == "parent_123"
    assert result.session.agent_type == "explore"
    assert runtime.seen_session_ids

    stored_children = AgentSessionStore().list_child_sessions("parent_123")
    assert stored_children
    assert stored_children[0].parent_session_id == "parent_123"


@pytest.mark.anyio
async def test_planner_dispatches_explore_subagent_for_research_like_goal(tmp_path, monkeypatch) -> None:
    db.DB_PATH = tmp_path / "planner-subagent.db"
    service = _create_service()
    session = _build_parent_session(service["id"])
    monkeypatch.setattr(planner_module, "OpenAICompatibleLLM", FakePlannerLlm)
    planner = AgentPlanner()
    decision = await planner.decide_next_action(
        session=session,
        working_context=WorkingContext(),
        available_tools=[
            ToolSpec(name="run_subagent", description="run subagent", category="orchestration", risk_level="read_only"),
            ToolSpec(name="search_knowledge", description="search", category="knowledge", risk_level="read_only"),
            ToolSpec(name="ask_llm_question", description="ask", category="reasoning", risk_level="read_only"),
        ],
    )

    assert decision.action_type == "tool_call"
    assert decision.next_tool_call is not None
    assert decision.next_tool_call.tool_name == "run_subagent"
    assert decision.next_tool_call.arguments["subagent_name"] == "explore"
# AI GC END

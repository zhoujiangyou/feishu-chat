# AI GC START
from __future__ import annotations

import pytest

from app import db
from app.agent.policy import AgentExecutionPolicy
from app.agent.runtime import AgentRuntime
from app.agent.session_store import AgentSessionStore
from app.agent.types import Observation, PlanDecision, ToolCall, ToolSpec
from app.agent.verifier import AgentVerifier


class FakePlanner:
    async def decide_next_action(self, session, working_context, available_tools):  # type: ignore[no-untyped-def]
        if session.step_count == 0:
            return PlanDecision(
                action_type="tool_call",
                reasoning_summary="先总结群聊。",
                updated_plan=["总结群聊", "发送结果"],
                next_tool_call=ToolCall(
                    tool_name="summarize_feishu_chat",
                    arguments={"chat_id": session.context["chat_id"], "limit": 20},
                    rationale="生成摘要",
                ),
            )
        return PlanDecision(
            action_type="tool_call",
            reasoning_summary="再发送总结。",
            updated_plan=["总结群聊", "发送结果"],
            next_tool_call=ToolCall(
                tool_name="send_feishu_message",
                arguments={
                    "receive_id": session.context["chat_id"],
                    "receive_id_type": "chat_id",
                    "text": session.working_memory["latest_summary"],
                },
                rationale="回发总结",
            ),
        )


class FakeSendPlanner:
    async def decide_next_action(self, session, working_context, available_tools):  # type: ignore[no-untyped-def]
        return PlanDecision(
            action_type="tool_call",
            reasoning_summary="直接尝试发送消息。",
            updated_plan=["发送消息"],
            next_tool_call=ToolCall(
                tool_name="send_feishu_message",
                arguments={"receive_id": "oc_demo", "text": "hello", "receive_id_type": "chat_id"},
                rationale="test",
            ),
        )


class FakeMissingContextPlanner:
    async def decide_next_action(self, session, working_context, available_tools):  # type: ignore[no-untyped-def]
        return PlanDecision(
            action_type="tool_call",
            reasoning_summary="尝试总结当前群。",
            updated_plan=["总结群聊"],
            next_tool_call=ToolCall(
                tool_name="summarize_feishu_chat",
                arguments={},
                rationale="test missing context",
            ),
        )


class FakeToolBridge:
    def list_available_tools(self, session):  # type: ignore[no-untyped-def]
        return [
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
        ]

    def get_tool_spec(self, tool_name: str) -> ToolSpec:
        for tool in self.list_available_tools(None):
            if tool.name == tool_name:
                return tool
        raise ValueError(tool_name)

    async def execute(self, session, call, step_index):  # type: ignore[no-untyped-def]
        if call.tool_name == "summarize_feishu_chat":
            return Observation(
                step_index=step_index,
                tool_name=call.tool_name,
                arguments=call.arguments,
                success=True,
                result={"summary": "这是本次群聊摘要。"},
                summary="summary ready",
                created_at=db.utcnow(),
            )
        if call.tool_name == "send_feishu_message":
            return Observation(
                step_index=step_index,
                tool_name=call.tool_name,
                arguments=call.arguments,
                success=True,
                result={"status": "ok", "receive_id": call.arguments["receive_id"]},
                summary="message sent",
                created_at=db.utcnow(),
            )
        raise ValueError(call.tool_name)


class FakeFailingToolBridge(FakeToolBridge):
    async def execute(self, session, call, step_index):  # type: ignore[no-untyped-def]
        return Observation(
            step_index=step_index,
            tool_name=call.tool_name,
            arguments=call.arguments,
            success=False,
            result=None,
            error="Current chat_id is missing for summarize_current_chat.",
            summary="failed",
            created_at=db.utcnow(),
        )


def _create_service() -> dict[str, str]:
    db.init_db()
    return db.create_service(
        {
            "name": "agent-demo",
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


@pytest.mark.anyio
async def test_agent_runtime_completes_summary_and_send_goal(tmp_path) -> None:
    db.DB_PATH = tmp_path / "agent-runtime.db"
    service = _create_service()
    runtime = AgentRuntime(
        session_store=AgentSessionStore(),
        planner=FakePlanner(),
        verifier=AgentVerifier(),
        tool_bridge=FakeToolBridge(),
        policy=AgentExecutionPolicy(),
    )

    result = await runtime.run(
        service_id=service["id"],
        goal="总结当前群并发送结果",
        context={"chat_id": "oc_group_123"},
        constraints={"max_steps": 4},
        policy_config={"allow_send_feishu_message": True},
    )

    assert result.session.status == "completed"
    assert result.session.final_answer == "这是本次群聊摘要。"
    assert result.session.working_memory["message_sent"] is True
    assert len(result.logs) == 2


@pytest.mark.anyio
async def test_agent_runtime_fails_when_policy_denies_side_effect(tmp_path) -> None:
    db.DB_PATH = tmp_path / "agent-policy.db"
    service = _create_service()
    runtime = AgentRuntime(
        session_store=AgentSessionStore(),
        planner=FakeSendPlanner(),
        verifier=AgentVerifier(),
        tool_bridge=FakeToolBridge(),
        policy=AgentExecutionPolicy(),
    )

    result = await runtime.run(
        service_id=service["id"],
        goal="发送消息给项目群",
        context={"chat_id": "oc_group_123"},
        constraints={"max_steps": 2},
        policy_config={"allow_send_feishu_message": False},
    )

    assert result.session.status == "failed"
    assert "send_feishu_message" in (result.session.failure_reason or "")


@pytest.mark.anyio
async def test_agent_runtime_switches_to_waiting_input_on_missing_context(tmp_path) -> None:
    db.DB_PATH = tmp_path / "agent-waiting.db"
    service = _create_service()
    runtime = AgentRuntime(
        session_store=AgentSessionStore(),
        planner=FakeMissingContextPlanner(),
        verifier=AgentVerifier(),
        tool_bridge=FakeFailingToolBridge(),
        policy=AgentExecutionPolicy(),
    )

    result = await runtime.run(
        service_id=service["id"],
        goal="请总结当前群",
        context={},
        constraints={"max_steps": 2},
        policy_config={},
    )

    assert result.session.status == "waiting_input"
    assert "pending_user_prompt" in result.session.working_memory
# AI GC END

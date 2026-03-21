# AI GC START
from __future__ import annotations

import pytest

from app import db
from app.agent.exceptions import DoomLoopDetectedError, PolicyDeniedError
from app.agent.permission_engine import PermissionEngine
from app.agent.policy import AgentExecutionPolicy
from app.agent.session_processor import SessionProcessor
from app.agent.tool_bridge import AgentToolBridge
from app.agent.types import AgentSession, AgentStepLog, Observation, PermissionRule, PlanDecision, ToolCall, ToolSpec
from app.agent.verifier import AgentVerifier


class FakeProcessorToolBridge:
    def get_tool_spec(self, tool_name: str) -> ToolSpec:
        return ToolSpec(
            name=tool_name,
            description="tool",
            category="reasoning",
            risk_level="read_only" if tool_name != "send_feishu_message" else "side_effect",
            side_effect=tool_name == "send_feishu_message",
        )

    async def execute(self, session, call, step_index):  # type: ignore[no-untyped-def]
        return Observation(
            step_index=step_index,
            tool_name=call.tool_name,
            arguments=call.arguments,
            success=True,
            result={"answer": "ok"} if call.tool_name == "ask_llm_question" else {"status": "ok"},
            summary="done",
            created_at=db.utcnow(),
        )


def _build_session(*, policy_config: dict | None = None) -> AgentSession:
    now = db.utcnow()
    return AgentSession(
        id="sess_processor_123",
        service_id="svc_123",
        goal="测试运行时",
        status="running",
        step_count=0,
        max_steps=6,
        context={"chat_id": "oc_group_123", "receive_id": "oc_group_123", "receive_id_type": "chat_id"},
        constraints={"max_steps": 6},
        policy_config=policy_config or {},
        current_plan=[],
        working_memory={},
        final_answer=None,
        failure_reason=None,
        created_at=now,
        updated_at=now,
    )


def test_permission_engine_last_matching_rule_wins() -> None:
    engine = PermissionEngine()
    result = engine.evaluate(
        permission="send_feishu_message",
        pattern="receive_id:oc_prod_123",
        rulesets=[
            [
                PermissionRule(permission="*", pattern="*", action="deny"),
                PermissionRule(permission="send_feishu_message", pattern="*", action="allow"),
                PermissionRule(permission="send_feishu_message", pattern="receive_id:oc_prod_*", action="deny"),
            ]
        ],
    )
    assert result.action == "deny"


def test_policy_rule_can_override_default_send_permission() -> None:
    policy = AgentExecutionPolicy()
    session = _build_session(
        policy_config={
            "allow_send_feishu_message": True,
            "permission_rules": [
                {"permission": "send_feishu_message", "pattern": "receive_id:oc_group_123", "action": "deny"}
            ],
        }
    )
    tool = ToolSpec(
        name="send_feishu_message",
        description="send",
        category="action",
        risk_level="side_effect",
        side_effect=True,
    )
    with pytest.raises(PolicyDeniedError):
        policy.ensure_tool_call_allowed(
            session,
            ToolCall(
                tool_name="send_feishu_message",
                arguments={"receive_id": "oc_group_123", "text": "hello", "receive_id_type": "chat_id"},
                rationale="test",
            ),
            tool,
        )


@pytest.mark.anyio
async def test_session_processor_detects_doom_loop() -> None:
    processor = SessionProcessor(
        tool_bridge=FakeProcessorToolBridge(),  # type: ignore[arg-type]
        verifier=AgentVerifier(),
        policy=AgentExecutionPolicy(),
    )
    previous_logs = [
        AgentStepLog(
            session_id="sess_processor_123",
            step_index=index,
            plan_decision={"action_type": "tool_call"},
            observation={
                "tool_name": "search_knowledge",
                "arguments": {"query": "重复查询", "limit": 5},
                "success": True,
                "summary": "done",
                "created_at": db.utcnow(),
            },
            verification={"goal_completed": False},
            processor_state={"status": "completed"},
            created_at=db.utcnow(),
        )
        for index in range(3)
    ]
    with pytest.raises(DoomLoopDetectedError):
        await processor.process_step(
            session=_build_session(),
            decision=PlanDecision(
                action_type="tool_call",
                reasoning_summary="重复调用搜索。",
                next_tool_call=ToolCall(
                    tool_name="search_knowledge",
                    arguments={"query": "重复查询", "limit": 5},
                    rationale="repeat",
                ),
            ),
            step_index=3,
            previous_logs=previous_logs,
        )


@pytest.mark.anyio
async def test_session_processor_records_processor_state() -> None:
    processor = SessionProcessor(
        tool_bridge=FakeProcessorToolBridge(),  # type: ignore[arg-type]
        verifier=AgentVerifier(),
        policy=AgentExecutionPolicy(),
    )
    step_log, observation, verification = await processor.process_step(
        session=_build_session(),
        decision=PlanDecision(
            action_type="tool_call",
            reasoning_summary="执行问答。",
            next_tool_call=ToolCall(
                tool_name="ask_llm_question",
                arguments={"question": "机器人能做什么？", "use_knowledge_base": True, "knowledge_limit": 5},
                rationale="test",
            ),
        ),
        step_index=0,
        previous_logs=[],
    )
    assert observation is not None
    assert verification is not None
    assert step_log.processor_state is not None
    assert step_log.processor_state["status"] == "completed"
    assert step_log.processor_state["verification_outcome"] in {"goal_completed", "replan", "continue", "retry"}
# AI GC END

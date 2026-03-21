# AI GC START
from __future__ import annotations

import pytest

from app import db
from app.agent.policy import AgentExecutionPolicy
from app.agent.runtime import AgentRuntime
from app.agent.session_store import AgentSessionStore
from app.agent.types import AgentRunResult, AgentSession, AgentStepLog, ToolSpec
from app.agent.verifier import AgentVerifier


class FakeExplorePlanner:
    async def decide_next_action(self, session, working_context, available_tools):  # type: ignore[no-untyped-def]
        if session.step_count == 0:
            from app.agent.types import PlanDecision, ToolCall

            return PlanDecision(
                action_type="tool_call",
                reasoning_summary="先派发 explore 子 agent 收集上下文。",
                updated_plan=["探索上下文", "组织回答"],
                next_tool_call=ToolCall(
                    tool_name="run_subagent",
                    arguments={"subagent_name": "explore", "goal": session.goal},
                    rationale="delegate explore",
                ),
            )
        from app.agent.types import PlanDecision, ToolCall

        return PlanDecision(
            action_type="tool_call",
            reasoning_summary="基于 explore 结果组织最终回答。",
            updated_plan=["组织回答"],
            next_tool_call=ToolCall(
                tool_name="ask_llm_question",
                arguments={"question": session.working_memory["latest_subagent_summary"], "use_knowledge_base": False, "knowledge_limit": 1},
                rationale="compose from subagent summary",
            ),
        )


class FakeRuntimeToolBridge:
    def list_available_tools(self, session):  # type: ignore[no-untyped-def]
        return [
            ToolSpec(name="run_subagent", description="subagent", category="orchestration", risk_level="read_only"),
            ToolSpec(name="ask_llm_question", description="ask", category="reasoning", risk_level="read_only"),
        ]

    def get_tool_spec(self, tool_name: str) -> ToolSpec:
        for tool in self.list_available_tools(None):
            if tool.name == tool_name:
                return tool
        raise ValueError(tool_name)

    async def execute(self, session, call, step_index):  # type: ignore[no-untyped-def]
        from app.agent.types import Observation

        if call.tool_name == "run_subagent":
            return Observation(
                step_index=step_index,
                tool_name="run_subagent",
                arguments=call.arguments,
                success=True,
                result={
                    "summary": "这是 explore 子 agent 提供的关键上下文摘要。",
                    "session_id": "child_123",
                    "subagent_name": "explore",
                },
                summary="subagent summary ready",
                created_at=db.utcnow(),
            )
        return Observation(
            step_index=step_index,
            tool_name="ask_llm_question",
            arguments=call.arguments,
            success=True,
            result={"answer": "最终答案：基于 explore 摘要整理完成。"},
            summary="final answer ready",
            created_at=db.utcnow(),
        )


def _create_service() -> dict[str, str]:
    db.init_db()
    return db.create_service(
        {
            "name": "subagent-runtime-demo",
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
async def test_runtime_continues_after_subagent_summary(tmp_path) -> None:
    db.DB_PATH = tmp_path / "subagent-runtime-flow.db"
    service = _create_service()
    runtime = AgentRuntime(
        session_store=AgentSessionStore(),
        planner=FakeExplorePlanner(),
        verifier=AgentVerifier(),
        tool_bridge=FakeRuntimeToolBridge(),
        policy=AgentExecutionPolicy(),
    )

    result = await runtime.run(
        service_id=service["id"],
        goal="请研究当前知识库后给我一个答案",
        context={"chat_id": "oc_group_123"},
        constraints={"max_steps": 4},
        policy_config={},
    )

    assert result.session.status == "completed"
    assert result.session.final_answer == "最终答案：基于 explore 摘要整理完成。"
    assert result.session.working_memory["latest_subagent_summary"] == "这是 explore 子 agent 提供的关键上下文摘要。"
    assert result.session.working_memory["latest_subagent_type"] == "explore"
    assert len(result.logs) == 2
# AI GC END

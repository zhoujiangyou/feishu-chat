# AI GC START
from __future__ import annotations

import pytest

from app import db
from app.agent.tool_bridge import AgentToolBridge
from app.agent.types import AgentSession, ToolCall


class FakeAgentApiClient:
    async def search_knowledge(self, *, service_id: str, query: str, limit: int = 5) -> dict[str, object]:
        return {"query": query, "results": [{"id": "chunk_1", "content": "hit"}], "service_id": service_id}

    async def ask_with_llm(
        self,
        *,
        service_id: str,
        question: str,
        use_knowledge_base: bool = True,
        knowledge_limit: int = 5,
        system_prompt_override: str | None = None,
    ) -> dict[str, object]:
        return {
            "answer": f"answer:{question}",
            "service_id": service_id,
            "use_knowledge_base": use_knowledge_base,
            "knowledge_limit": knowledge_limit,
        }

    async def send_feishu_message(
        self,
        *,
        service_id: str,
        receive_id: str,
        text: str,
        receive_id_type: str = "chat_id",
    ) -> dict[str, object]:
        return {
            "status": "ok",
            "service_id": service_id,
            "receive_id": receive_id,
            "text": text,
            "receive_id_type": receive_id_type,
        }


def _build_session(*, allow_send: bool) -> AgentSession:
    now = db.utcnow()
    return AgentSession(
        id="sess_123",
        service_id="svc_123",
        goal="回答问题",
        status="running",
        step_count=0,
        max_steps=4,
        context={},
        constraints={},
        policy_config={"allow_send_feishu_message": allow_send},
        current_plan=[],
        working_memory={},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.anyio
async def test_tool_bridge_executes_llm_question() -> None:
    bridge = AgentToolBridge(api_client=FakeAgentApiClient())
    session = _build_session(allow_send=False)
    observation = await bridge.execute(
        session=session,
        call=ToolCall(
            tool_name="ask_llm_question",
            arguments={"question": "机器人可以做什么？", "use_knowledge_base": True, "knowledge_limit": 3},
            rationale="test",
        ),
        step_index=0,
    )
    assert observation.success is True
    assert observation.result is not None
    assert observation.result["answer"] == "answer:机器人可以做什么？"


def test_tool_bridge_hides_send_message_without_permission() -> None:
    bridge = AgentToolBridge(api_client=FakeAgentApiClient())
    session = _build_session(allow_send=False)
    names = {tool.name for tool in bridge.list_available_tools(session)}
    assert "send_feishu_message" not in names


@pytest.mark.anyio
async def test_tool_bridge_exposes_and_executes_send_message_with_permission() -> None:
    bridge = AgentToolBridge(api_client=FakeAgentApiClient())
    session = _build_session(allow_send=True)
    names = {tool.name for tool in bridge.list_available_tools(session)}
    assert "send_feishu_message" in names

    observation = await bridge.execute(
        session=session,
        call=ToolCall(
            tool_name="send_feishu_message",
            arguments={"receive_id": "oc_demo", "text": "hello", "receive_id_type": "chat_id"},
            rationale="test send",
        ),
        step_index=1,
    )
    assert observation.success is True
    assert observation.result is not None
    assert observation.result["receive_id"] == "oc_demo"
# AI GC END

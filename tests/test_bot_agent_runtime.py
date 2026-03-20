# AI GC START
from __future__ import annotations

import app.services.bot as bot_module
import pytest
from app import db
from app.agent.types import AgentRunResult, AgentSession


class FakeBotAgentFeishuClient:
    last_reply: str | None = None

    def __init__(self, service: dict[str, str]) -> None:
        self.service = service

    async def reply_text_message(self, *, message_id: str, text: str) -> dict[str, object]:
        type(self).last_reply = text
        return {"message_id": message_id, "text": text}

    async def close(self) -> None:
        return None


class FakeBotAgentRuntime:
    def __init__(self, *, final_answer: str, message_sent: bool = False) -> None:
        self.final_answer = final_answer
        self.message_sent = message_sent
        self.calls: list[dict[str, object]] = []

    async def run(self, *, service_id: str, goal: str, context: dict, constraints: dict, policy_config: dict):  # type: ignore[no-untyped-def]
        self.calls.append(
            {
                "service_id": service_id,
                "goal": goal,
                "context": context,
                "constraints": constraints,
                "policy_config": policy_config,
            }
        )
        session = AgentSession(
            id="sess_bot_123",
            service_id=service_id,
            goal=goal,
            status="completed",
            step_count=2,
            max_steps=constraints["max_steps"],
            context=context,
            constraints=constraints,
            policy_config=policy_config,
            current_plan=["理解目标", "完成执行"],
            working_memory={"message_sent": self.message_sent, "latest_summary": self.final_answer},
            final_answer=self.final_answer,
            failure_reason=None,
            created_at=db.utcnow(),
            updated_at=db.utcnow(),
        )
        return AgentRunResult(session=session, logs=[])


class FakeFallbackLLM:
    def __init__(self, service: dict[str, str]) -> None:
        self.service = service

    async def answer(
        self,
        *,
        question: str,
        knowledge,
        system_prompt_override: str | None = None,
    ) -> str:
        return f"fallback:{question}|kb={len(knowledge)}"


class FakeWaitingRuntime:
    async def run(self, *, service_id: str, goal: str, context: dict, constraints: dict, policy_config: dict):  # type: ignore[no-untyped-def]
        session = AgentSession(
            id="sess_wait_123",
            service_id=service_id,
            goal=goal,
            status="waiting_input",
            step_count=1,
            max_steps=constraints["max_steps"],
            context=context,
            constraints=constraints,
            policy_config=policy_config,
            current_plan=["获取更多上下文"],
            working_memory={"pending_user_prompt": "请补充 chat_id 或直接在目标群里发起请求。"},
            final_answer=None,
            failure_reason=None,
            created_at=db.utcnow(),
            updated_at=db.utcnow(),
        )
        return AgentRunResult(session=session, logs=[])


def _create_service() -> dict[str, str]:
    db.init_db()
    return db.create_service(
        {
            "name": "bot-agent-demo",
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


def _build_payload(text: str) -> dict[str, object]:
    return {
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_type": "user", "sender_id": {"open_id": "ou_123"}},
            "message": {
                "message_type": "text",
                "chat_id": "oc_123",
                "message_id": "om_123",
                "content": f'{{"text":"{text}"}}',
            },
        },
    }


@pytest.mark.anyio
async def test_bot_text_message_uses_agent_runtime_and_replies(tmp_path, monkeypatch) -> None:
    db.DB_PATH = tmp_path / "bot-agent-success.db"
    service = _create_service()
    runtime = FakeBotAgentRuntime(final_answer="agent final answer", message_sent=False)
    FakeBotAgentFeishuClient.last_reply = None
    monkeypatch.setattr(bot_module, "FeishuClient", FakeBotAgentFeishuClient)
    monkeypatch.setattr(bot_module, "get_bot_agent_runtime", lambda: runtime)

    result = await bot_module.handle_event(service, _build_payload("请总结当前群的重点"))

    assert result["status"] == "agent_completed"
    assert result["session_id"] == "sess_bot_123"
    assert result["reply_mode"] == "reply_text_message"
    assert FakeBotAgentFeishuClient.last_reply == "agent final answer"
    assert runtime.calls[0]["context"]["chat_id"] == "oc_123"
    assert runtime.calls[0]["policy_config"]["allow_send_feishu_message"] is True


@pytest.mark.anyio
async def test_bot_text_message_skips_reply_when_agent_already_sent_message(tmp_path, monkeypatch) -> None:
    db.DB_PATH = tmp_path / "bot-agent-send.db"
    service = _create_service()
    runtime = FakeBotAgentRuntime(final_answer="已回发到群里", message_sent=True)
    FakeBotAgentFeishuClient.last_reply = None
    monkeypatch.setattr(bot_module, "FeishuClient", FakeBotAgentFeishuClient)
    monkeypatch.setattr(bot_module, "get_bot_agent_runtime", lambda: runtime)

    result = await bot_module.handle_event(service, _build_payload("帮我总结并发到当前群"))

    assert result["status"] == "agent_completed"
    assert result["reply_mode"] == "agent_send_message"
    assert FakeBotAgentFeishuClient.last_reply is None


@pytest.mark.anyio
async def test_bot_text_message_falls_back_to_llm_when_agent_runtime_fails(tmp_path, monkeypatch) -> None:
    db.DB_PATH = tmp_path / "bot-agent-fallback.db"
    service = _create_service()
    FakeBotAgentFeishuClient.last_reply = None

    class BrokenRuntime:
        async def run(self, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("agent runtime unavailable")

    monkeypatch.setattr(bot_module, "FeishuClient", FakeBotAgentFeishuClient)
    monkeypatch.setattr(bot_module, "get_bot_agent_runtime", lambda: BrokenRuntime())
    monkeypatch.setattr(bot_module, "OpenAICompatibleLLM", FakeFallbackLLM)

    result = await bot_module.handle_event(service, _build_payload("机器人现在可以做什么"))

    assert result["status"] == "answered_fallback"
    assert result["reply_mode"] == "reply_text_message"
    assert FakeBotAgentFeishuClient.last_reply == "fallback:机器人现在可以做什么|kb=0"


@pytest.mark.anyio
async def test_bot_text_message_replies_with_waiting_prompt_when_agent_needs_more_context(tmp_path, monkeypatch) -> None:
    db.DB_PATH = tmp_path / "bot-agent-waiting.db"
    service = _create_service()
    FakeBotAgentFeishuClient.last_reply = None

    monkeypatch.setattr(bot_module, "FeishuClient", FakeBotAgentFeishuClient)
    monkeypatch.setattr(bot_module, "get_bot_agent_runtime", lambda: FakeWaitingRuntime())

    result = await bot_module.handle_event(service, _build_payload("请总结另一个群的重点"))

    assert result["status"] == "agent_waiting_input"
    assert result["reply_mode"] == "reply_text_message"
    assert FakeBotAgentFeishuClient.last_reply == "请补充 chat_id 或直接在目标群里发起请求。"
# AI GC END

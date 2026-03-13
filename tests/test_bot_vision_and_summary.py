# AI GC START
from __future__ import annotations

import app.main as main_module
import app.mcp_server as mcp_module
import app.services.bot as bot_module
import pytest
from app import db
from fastapi.testclient import TestClient


class FakeVisionLLM:
    def __init__(self, service: dict[str, str]) -> None:
        self.service = service

    async def analyze_image(
        self,
        *,
        prompt: str,
        knowledge,
        image_base64: str | None = None,
        image_mime_type: str | None = None,
        **_: object,
    ) -> str:
        return f"视觉分析:{prompt}|mime={image_mime_type}|kb={len(knowledge)}"

    async def answer(
        self,
        *,
        question: str,
        knowledge,
        system_prompt_override: str | None = None,
    ) -> str:
        return f"群聊总结:{question[:12]}|kb={len(knowledge)}|prompt={system_prompt_override or 'default'}"


class FakeBotKbService:
    async def import_feishu_image(self, **_: object) -> dict[str, str]:
        return {"id": "src_123", "title": "Image from chat"}

    def search(self, **_: object):
        return []


class FakeBotFeishuClient:
    last_reply: str | None = None

    def __init__(self, service: dict[str, str]) -> None:
        self.service = service

    async def download_image(self, image_key: str) -> tuple[bytes, str | None]:
        return b"fake-image", "image/png"

    async def reply_text_message(self, *, message_id: str, text: str) -> dict[str, object]:
        type(self).last_reply = text
        return {"message_id": message_id, "text": text}

    async def close(self) -> None:
        return None


class FakeSummaryFeishuClient:
    last_sent_text: str | None = None

    def __init__(self, service: dict[str, str]) -> None:
        self.service = service

    async def list_chat_messages(self, *, chat_id: str, limit: int = 100):
        return [
            {
                "message_type": "text",
                "create_time": "1",
                "sender": {"sender_id": {"open_id": "ou_1"}},
                "content": '{"text":"今天讨论了发布计划"}',
            },
            {
                "message_type": "text",
                "create_time": "2",
                "sender": {"sender_id": {"open_id": "ou_2"}},
                "content": '{"text":"需要补充风险评估"}',
            },
        ]

    async def send_text_message(self, *, receive_id: str, text: str, receive_id_type: str = "chat_id"):
        type(self).last_sent_text = text
        return {"receive_id": receive_id, "receive_id_type": receive_id_type, "text": text}

    async def close(self) -> None:
        return None


class FakeMcpSummaryClient:
    async def summarize_feishu_chat(self, **kwargs):
        return {"status": "ok", **kwargs}


def _create_service(client: TestClient) -> str:
    response = client.post(
        "/api/v1/services",
        json={
            "name": "demo-api",
            "feishu_app_id": "cli_demo",
            "feishu_app_secret": "secret",
            "verification_token": "verify",
            "encrypt_key": "encrypt",
            "llm_base_url": "https://example.com/v1",
            "llm_api_key": "sk-demo",
            "llm_model": "test-model",
            "llm_system_prompt": "你是测试助手。",
        },
    )
    assert response.status_code == 200
    return response.json()["service_id"]


@pytest.mark.anyio
async def test_bot_image_message_triggers_vision_reply(tmp_path, monkeypatch) -> None:
    db.DB_PATH = tmp_path / "bot-vision.db"
    db.init_db()
    service = db.create_service(
        {
            "name": "vision-bot",
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
    monkeypatch.setattr(bot_module, "KnowledgeBaseService", FakeBotKbService)
    monkeypatch.setattr(bot_module, "OpenAICompatibleLLM", FakeVisionLLM)
    monkeypatch.setattr(bot_module, "FeishuClient", FakeBotFeishuClient)
    FakeBotFeishuClient.last_reply = None

    payload = {
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_type": "user", "sender_id": {"open_id": "ou_123"}},
            "message": {
                "message_type": "image",
                "chat_id": "oc_123",
                "message_id": "om_123",
                "content": '{"image_key":"img_123"}',
            },
        },
    }

    result = await bot_module.handle_event(service, payload)
    assert result["status"] == "ingested_image"
    assert FakeBotFeishuClient.last_reply is not None
    assert "图片分析：" in FakeBotFeishuClient.last_reply


def test_upload_image_analysis_endpoint(tmp_path, monkeypatch) -> None:
    db.DB_PATH = tmp_path / "upload-vision.db"
    monkeypatch.setattr(main_module, "OpenAICompatibleLLM", FakeVisionLLM)

    with TestClient(main_module.app) as client:
        service_id = _create_service(client)
        response = client.post(
            f"/api/v1/services/{service_id}/llm/image-analyze/upload",
            data={"prompt": "请分析上传图片", "use_knowledge_base": "false", "knowledge_limit": "5"},
            files={"file": ("demo.png", b"fake-image-bytes", "image/png")},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["image_source"] == "upload_file"
        assert "视觉分析:请分析上传图片" in payload["answer"]


def test_summarize_chat_endpoint_and_send(tmp_path, monkeypatch) -> None:
    db.DB_PATH = tmp_path / "summary.db"
    monkeypatch.setattr(main_module, "OpenAICompatibleLLM", FakeVisionLLM)
    monkeypatch.setattr(main_module, "FeishuClient", FakeSummaryFeishuClient)
    FakeSummaryFeishuClient.last_sent_text = None

    with TestClient(main_module.app) as client:
        service_id = _create_service(client)
        response = client.post(
            f"/api/v1/services/{service_id}/feishu/chats/summarize",
            json={
                "chat_id": "oc_123",
                "limit": 50,
                "send_to_receive_id": "oc_123",
                "send_to_receive_id_type": "chat_id",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["chat_id"] == "oc_123"
        assert payload["message_count"] == 2
        assert payload["sent_result"] is not None
        assert FakeSummaryFeishuClient.last_sent_text is not None


@pytest.mark.anyio
async def test_mcp_summarize_tool_delegates_to_service_api(monkeypatch) -> None:
    monkeypatch.setattr(mcp_module, "_api_client", lambda: FakeMcpSummaryClient())
    payload = await mcp_module.summarize_feishu_chat(
        service_id="svc_123",
        chat_id="oc_123",
        limit=20,
        send_to_receive_id="oc_123",
        send_to_receive_id_type="chat_id",
    )
    assert payload["status"] == "ok"
    assert payload["chat_id"] == "oc_123"
# AI GC END

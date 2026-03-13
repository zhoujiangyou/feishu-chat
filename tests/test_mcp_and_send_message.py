# AI GC START
from __future__ import annotations

import app.main as main_module
import app.mcp_server as mcp_module
import pytest
from app import db
from fastapi.testclient import TestClient


class FakeFeishuClient:
    def __init__(self, service: dict[str, str]) -> None:
        self.service = service

    async def send_text_message(
        self,
        *,
        receive_id: str,
        text: str,
        receive_id_type: str = "chat_id",
    ) -> dict[str, object]:
        return {
            "data": {
                "message_id": "om_fake",
                "receive_id": receive_id,
                "text": text,
                "receive_id_type": receive_id_type,
            }
        }

    async def close(self) -> None:
        return None


class FakeServiceApiClient:
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


def test_send_message_endpoint(tmp_path, monkeypatch) -> None:
    db.DB_PATH = tmp_path / "send-message.db"
    monkeypatch.setattr(main_module, "FeishuClient", FakeFeishuClient)

    with TestClient(main_module.app) as client:
        service_id = _create_service(client)
        response = client.post(
            f"/api/v1/services/{service_id}/feishu/messages/send",
            json={
                "receive_id": "oc_group_123",
                "text": "hello group",
                "receive_id_type": "chat_id",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["result"]["data"]["message_id"] == "om_fake"


@pytest.mark.anyio
async def test_mcp_send_tool_delegates_to_service_api(monkeypatch) -> None:
    monkeypatch.setattr(mcp_module, "_api_client", lambda: FakeServiceApiClient())
    payload = await mcp_module.send_feishu_message(
        service_id="svc_123",
        receive_id="oc_group_123",
        text="hello from mcp",
        receive_id_type="chat_id",
    )
    assert payload["status"] == "ok"
    assert payload["service_id"] == "svc_123"
    assert payload["receive_id"] == "oc_group_123"
# AI GC END

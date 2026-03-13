# AI GC START
from __future__ import annotations

import app.main as main_module
import app.mcp_server as mcp_module
import pytest
from app import db
from fastapi.testclient import TestClient


class FakeLLM:
    def __init__(self, service: dict[str, str]) -> None:
        self.service = service

    async def answer(
        self,
        *,
        question: str,
        knowledge: list[dict[str, object]],
        system_prompt_override: str | None = None,
    ) -> str:
        return f"answer:{question}|knowledge={len(knowledge)}|prompt={system_prompt_override or 'default'}"

    async def analyze_image(
        self,
        *,
        prompt: str,
        knowledge: list[dict[str, object]] | None = None,
        image_url: str | None = None,
        image_base64: str | None = None,
        image_mime_type: str | None = None,
        system_prompt_override: str | None = None,
    ) -> str:
        source = "url" if image_url else "base64"
        return (
            f"image:{prompt}|source={source}|mime={image_mime_type or 'n/a'}|"
            f"knowledge={len(knowledge or [])}|prompt={system_prompt_override or 'default'}"
        )


class FakeFeishuImageClient:
    def __init__(self, service: dict[str, str]) -> None:
        self.service = service

    async def get_message(self, message_id: str) -> dict[str, object]:
        return {"content": '{"image_key": "img_from_message"}'}

    async def download_image(self, image_key: str) -> tuple[bytes, str | None]:
        return b"fake-image", "image/png"

    async def close(self) -> None:
        return None


class FakeLlmServiceApiClient:
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
            "answer": "delegated answer",
            "service_id": service_id,
            "question": question,
            "knowledge_limit": knowledge_limit,
            "use_knowledge_base": use_knowledge_base,
            "system_prompt_override": system_prompt_override,
        }

    async def analyze_image_with_llm(
        self,
        *,
        service_id: str,
        prompt: str,
        image_url: str | None = None,
        image_base64: str | None = None,
        image_mime_type: str | None = None,
        image_key: str | None = None,
        message_id: str | None = None,
        use_knowledge_base: bool = False,
        knowledge_query: str | None = None,
        knowledge_limit: int = 5,
        system_prompt_override: str | None = None,
    ) -> dict[str, object]:
        return {
            "answer": "delegated image answer",
            "service_id": service_id,
            "prompt": prompt,
            "image_url": image_url,
            "image_key": image_key,
            "message_id": message_id,
            "knowledge_query": knowledge_query,
            "knowledge_limit": knowledge_limit,
            "use_knowledge_base": use_knowledge_base,
            "system_prompt_override": system_prompt_override,
            "image_mime_type": image_mime_type,
            "image_base64": image_base64,
        }


def _create_service(client: TestClient) -> str:
    response = client.post(
        "/api/v1/services",
        json={
            "name": "llm-demo",
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


def test_llm_ask_endpoint_supports_knowledge_search(tmp_path, monkeypatch) -> None:
    db.DB_PATH = tmp_path / "llm-ask.db"
    monkeypatch.setattr(main_module, "OpenAICompatibleLLM", FakeLLM)

    with TestClient(main_module.app) as client:
        service_id = _create_service(client)
        client.post(
            f"/api/v1/services/{service_id}/knowledge-base/text",
            json={"title": "说明", "content": "飞书机器人支持知识库检索问答。", "metadata": {}},
        )
        response = client.post(
            f"/api/v1/services/{service_id}/llm/ask",
            json={
                "question": "知识库检索问答",
                "use_knowledge_base": True,
                "knowledge_limit": 3,
                "system_prompt_override": "你是问答测试助手。",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert "answer:知识库检索问答" in payload["answer"]
        assert payload["knowledge_results"]


def test_llm_image_analyze_endpoint_supports_feishu_message_image(tmp_path, monkeypatch) -> None:
    db.DB_PATH = tmp_path / "llm-image.db"
    monkeypatch.setattr(main_module, "OpenAICompatibleLLM", FakeLLM)
    monkeypatch.setattr(main_module, "FeishuClient", FakeFeishuImageClient)

    with TestClient(main_module.app) as client:
        service_id = _create_service(client)
        response = client.post(
            f"/api/v1/services/{service_id}/llm/image-analyze",
            json={
                "prompt": "请描述这张图",
                "message_id": "om_xxx",
                "use_knowledge_base": False,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["image_source"] == "feishu_image"
        assert "image:请描述这张图" in payload["answer"]


@pytest.mark.anyio
async def test_mcp_llm_tools_delegate_to_service_api(monkeypatch) -> None:
    monkeypatch.setattr(mcp_module, "_api_client", lambda: FakeLlmServiceApiClient())

    ask_payload = await mcp_module.ask_llm_question(
        service_id="svc_123",
        question="机器人可以做什么？",
        use_knowledge_base=True,
        knowledge_limit=4,
        system_prompt_override="请简洁回答。",
    )
    assert ask_payload["answer"] == "delegated answer"
    assert ask_payload["service_id"] == "svc_123"

    image_payload = await mcp_module.analyze_image_with_llm(
        service_id="svc_123",
        prompt="请分析图片内容",
        image_url="https://example.com/demo.png",
        use_knowledge_base=False,
    )
    assert image_payload["answer"] == "delegated image answer"
    assert image_payload["image_url"] == "https://example.com/demo.png"
# AI GC END

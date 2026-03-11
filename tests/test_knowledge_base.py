# AI GC START
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.services.knowledge_base import KnowledgeBaseService, chunk_text


def test_chunk_text_splits_large_content() -> None:
    text = ("飞书机器人知识库。" * 120).strip()
    chunks = chunk_text(text, chunk_size=120, overlap=20)
    assert len(chunks) > 1
    assert all(chunk for chunk in chunks)


def test_ingest_and_search_text_knowledge(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "test.db"
    db.init_db()
    service = db.create_service(
        {
            "name": "demo",
            "feishu_app_id": "cli_demo",
            "feishu_app_secret": "secret",
            "verification_token": "token",
            "encrypt_key": "encrypt",
            "llm_base_url": "https://example.com/v1",
            "llm_api_key": "sk-demo",
            "llm_model": "test-model",
            "llm_system_prompt": "你是测试助手。",
        }
    )

    kb = KnowledgeBaseService()
    kb.ingest_text(
        service_id=service["id"],
        title="产品说明",
        content="这是一个用于飞书机器人、知识库挂载和任务转发的服务。",
        metadata={"tag": "intro"},
    )

    results = kb.search(service_id=service["id"], query="知识库", limit=5)
    assert results
    assert "知识库" in results[0]["content"]


def test_create_service_bootstraps_default_knowledge(tmp_path: Path) -> None:
    db.DB_PATH = tmp_path / "api-test.db"
    with TestClient(app) as client:
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
        service_id = response.json()["service_id"]

        search_response = client.get(
            f"/api/v1/services/{service_id}/knowledge-base/search",
            params={"query": "抓取文档"},
        )
        assert search_response.status_code == 200
        assert search_response.json()["results"]
# AI GC END

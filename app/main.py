# AI GC START
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app import db
from app.schemas import (
    FeishuChatImportRequest,
    FeishuDocumentImportRequest,
    FeishuImageImportRequest,
    KnowledgeSearchResponse,
    ServiceCreateRequest,
    ServiceResponse,
    TextKnowledgeImportRequest,
)
from app.services.bot import handle_event
from app.services.feishu import FeishuClient, FeishuError, decode_callback_body
from app.services.knowledge_base import KnowledgeBaseService, build_default_knowledge


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Feishu Chat Service", version="0.1.0", lifespan=lifespan)


def get_service_or_404(service_id: str) -> dict[str, Any]:
    service = db.get_service(service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found.")
    return service


async def process_event_async(service_id: str, payload: dict[str, Any]) -> None:
    service = get_service_or_404(service_id)
    try:
        await handle_event(service, payload)
    except Exception as exc:  # pragma: no cover
        print(f"[callback-error] service_id={service_id} error={exc}")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/services", response_model=ServiceResponse)
async def create_service(payload: ServiceCreateRequest) -> ServiceResponse:
    service = db.create_service(payload.model_dump())
    kb = KnowledgeBaseService()
    kb.ingest_text(
        service_id=service["id"],
        title="默认机器人使用说明",
        content=build_default_knowledge(service["name"]),
        source_type="system_bootstrap",
        metadata={"built_in": True},
    )
    return ServiceResponse(
        service_id=service["id"],
        name=service["name"],
        callback_path=f"/api/v1/feishu/{service['id']}/callback",
        created_at=service["created_at"],
    )


@app.get("/api/v1/services/{service_id}")
async def get_service(service_id: str) -> dict[str, Any]:
    service = get_service_or_404(service_id)
    return {
        "service_id": service["id"],
        "name": service["name"],
        "callback_path": f"/api/v1/feishu/{service['id']}/callback",
        "created_at": service["created_at"],
        "llm_model": service["llm_model"],
        "feishu_app_id": service["feishu_app_id"],
    }


@app.post("/api/v1/services/{service_id}/knowledge-base/text")
async def import_text_knowledge(service_id: str, payload: TextKnowledgeImportRequest) -> dict[str, Any]:
    get_service_or_404(service_id)
    kb = KnowledgeBaseService()
    source = kb.ingest_text(
        service_id=service_id,
        title=payload.title,
        content=payload.content,
        metadata=payload.metadata,
    )
    return {"status": "ok", "source": source}


@app.post("/api/v1/services/{service_id}/knowledge-base/feishu/document")
async def import_feishu_document(service_id: str, payload: FeishuDocumentImportRequest) -> dict[str, Any]:
    service = get_service_or_404(service_id)
    kb = KnowledgeBaseService()
    client = FeishuClient(service)
    try:
        source = await kb.import_feishu_document(
            service_id=service_id,
            client=client,
            document=payload.document,
            title=payload.title,
        )
    finally:
        await client.close()
    return {"status": "ok", "source": source}


@app.post("/api/v1/services/{service_id}/knowledge-base/feishu/chat")
async def import_feishu_chat(service_id: str, payload: FeishuChatImportRequest) -> dict[str, Any]:
    service = get_service_or_404(service_id)
    kb = KnowledgeBaseService()
    client = FeishuClient(service)
    try:
        source = await kb.import_feishu_chat(
            service_id=service_id,
            client=client,
            chat_id=payload.chat_id,
            limit=payload.limit,
        )
    finally:
        await client.close()
    return {"status": "ok", "source": source}


@app.post("/api/v1/services/{service_id}/knowledge-base/feishu/image")
async def import_feishu_image(service_id: str, payload: FeishuImageImportRequest) -> dict[str, Any]:
    service = get_service_or_404(service_id)
    kb = KnowledgeBaseService()
    client = FeishuClient(service)
    try:
        source = await kb.import_feishu_image(
            service_id=service_id,
            client=client,
            image_key=payload.image_key,
            message_id=payload.message_id,
            title=payload.title,
        )
    finally:
        await client.close()
    return {"status": "ok", "source": source}


@app.get("/api/v1/services/{service_id}/knowledge-base/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    service_id: str,
    query: str = Query(min_length=1),
    limit: int = Query(default=5, ge=1, le=20),
) -> KnowledgeSearchResponse:
    get_service_or_404(service_id)
    kb = KnowledgeBaseService()
    results = kb.search(service_id=service_id, query=query, limit=limit)
    return KnowledgeSearchResponse(query=query, results=results)


@app.get("/api/v1/services/{service_id}/knowledge-base/sources")
async def list_sources(service_id: str) -> dict[str, Any]:
    get_service_or_404(service_id)
    kb = KnowledgeBaseService()
    return {"items": kb.list_sources(service_id=service_id)}


@app.post("/api/v1/feishu/{service_id}/callback")
async def feishu_callback(service_id: str, request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    service = get_service_or_404(service_id)
    raw_body = await request.body()
    headers = {key.lower(): value for key, value in request.headers.items()}
    try:
        payload = decode_callback_body(raw_body, headers, service)
    except FeishuError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload.get("challenge"):
        return JSONResponse({"challenge": payload["challenge"]})

    background_tasks.add_task(process_event_async, service_id, payload)
    return JSONResponse({"status": "accepted"})
# AI GC END

# AI GC START
from __future__ import annotations

import base64
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app import db
from app.schemas import (
    FeishuChatImportRequest,
    FeishuDocumentImportRequest,
    FeishuImageImportRequest,
    LlmImageAnalyzeRequest,
    LlmImageAnalyzeResponse,
    LlmQuestionRequest,
    LlmQuestionResponse,
    KnowledgeSearchResponse,
    FeishuSendMessageRequest,
    ServiceCreateRequest,
    ServiceResponse,
    TextKnowledgeImportRequest,
)
from app.services.bot import handle_event
from app.services.feishu import (
    FeishuClient,
    FeishuError,
    decode_callback_body,
    extract_image_key_from_message,
)
from app.services.knowledge_base import KnowledgeBaseService, build_default_knowledge
from app.services.llm import OpenAICompatibleLLM


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


@app.post("/api/v1/services/{service_id}/feishu/messages/send")
async def send_feishu_message(service_id: str, payload: FeishuSendMessageRequest) -> dict[str, Any]:
    service = get_service_or_404(service_id)
    client = FeishuClient(service)
    try:
        result = await client.send_text_message(
            receive_id=payload.receive_id,
            text=payload.text,
            receive_id_type=payload.receive_id_type,
        )
    finally:
        await client.close()

    db.log_conversation(
        service_id=service_id,
        direction="outgoing",
        chat_id=payload.receive_id if payload.receive_id_type == "chat_id" else None,
        user_id=payload.receive_id if payload.receive_id_type != "chat_id" else None,
        content=payload.text,
        metadata={"receive_id_type": payload.receive_id_type, "result": result},
    )
    return {"status": "ok", "result": result}


@app.post("/api/v1/services/{service_id}/llm/ask", response_model=LlmQuestionResponse)
async def ask_with_llm(service_id: str, payload: LlmQuestionRequest) -> LlmQuestionResponse:
    service = get_service_or_404(service_id)
    kb = KnowledgeBaseService()
    knowledge = (
        kb.search(service_id=service_id, query=payload.question, limit=payload.knowledge_limit)
        if payload.use_knowledge_base
        else []
    )
    llm = OpenAICompatibleLLM(service)
    answer = await llm.answer(
        question=payload.question,
        knowledge=knowledge,
        system_prompt_override=payload.system_prompt_override,
    )
    return LlmQuestionResponse(answer=answer, knowledge_results=knowledge)


async def _resolve_image_analysis_input(
    *,
    service: dict[str, Any],
    payload: LlmImageAnalyzeRequest,
) -> tuple[dict[str, Any], str]:
    if payload.image_url:
        return {"image_url": payload.image_url}, "image_url"
    if payload.image_base64:
        return {
            "image_base64": payload.image_base64,
            "image_mime_type": payload.image_mime_type or "image/png",
        }, "image_base64"

    client = FeishuClient(service)
    try:
        image_key = payload.image_key
        if not image_key and payload.message_id:
            message = await client.get_message(payload.message_id)
            image_key = extract_image_key_from_message(message)
        if not image_key:
            raise HTTPException(status_code=400, detail="Unable to resolve image_key from Feishu message.")
        image_bytes, mime_type = await client.download_image(image_key)
    finally:
        await client.close()

    return {
        "image_base64": base64.b64encode(image_bytes).decode("utf-8"),
        "image_mime_type": mime_type or payload.image_mime_type or "image/png",
    }, "feishu_image"


@app.post("/api/v1/services/{service_id}/llm/image-analyze", response_model=LlmImageAnalyzeResponse)
async def analyze_image_with_llm(service_id: str, payload: LlmImageAnalyzeRequest) -> LlmImageAnalyzeResponse:
    service = get_service_or_404(service_id)
    kb = KnowledgeBaseService()
    knowledge_query = payload.knowledge_query or payload.prompt
    knowledge = (
        kb.search(service_id=service_id, query=knowledge_query, limit=payload.knowledge_limit)
        if payload.use_knowledge_base
        else []
    )
    image_kwargs, image_source = await _resolve_image_analysis_input(service=service, payload=payload)
    llm = OpenAICompatibleLLM(service)
    answer = await llm.analyze_image(
        prompt=payload.prompt,
        knowledge=knowledge,
        system_prompt_override=payload.system_prompt_override,
        **image_kwargs,
    )
    return LlmImageAnalyzeResponse(
        answer=answer,
        knowledge_results=knowledge,
        image_source=image_source,
    )


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

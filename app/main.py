# AI GC START
from __future__ import annotations

import base64
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from app import db
from app.agent import AgentRuntime
from app.agent.types import AgentRunResult, AgentSession, AgentStepLog
from app.schemas import (
    AgentCancelResponse,
    AgentRunRequest,
    AgentRunResponse,
    AgentSessionLogResponse,
    AgentSessionResponse,
    FeishuChatImportRequest,
    FeishuChatSummaryRequest,
    FeishuChatSummaryResponse,
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
from app.services.knowledge_base import KnowledgeBaseService, build_chat_transcript, build_default_knowledge
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


def get_agent_runtime() -> AgentRuntime:
    return AgentRuntime()


def _build_agent_session_response(session: AgentSession) -> AgentSessionResponse:
    return AgentSessionResponse(
        session_id=session.id,
        service_id=session.service_id,
        goal=session.goal,
        status=session.status,
        step_count=session.step_count,
        max_steps=session.max_steps,
        context=session.context,
        constraints=session.constraints,
        policy_config=session.policy_config,
        current_plan=session.current_plan,
        working_memory=session.working_memory,
        final_answer=session.final_answer,
        failure_reason=session.failure_reason,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _build_agent_run_response(result: AgentRunResult) -> AgentRunResponse:
    return AgentRunResponse(
        session=_build_agent_session_response(result.session),
        logs=[_serialize_agent_step_log(item) for item in result.logs],
    )


def _serialize_agent_step_log(step_log: AgentStepLog) -> dict[str, Any]:
    return step_log.model_dump()


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
    saved_source = None
    if payload.save_analysis_to_knowledge_base:
        title = payload.analysis_title or f"Image Analysis {image_source}"
        saved_source = kb.ingest_generated_artifact(
            service_id=service_id,
            title=title,
            content=answer,
            source_type="llm_image_analysis",
            external_id=payload.image_key or payload.message_id or payload.image_url or image_source,
            metadata={
                "image_source": image_source,
                "prompt": payload.prompt,
                "image_url": payload.image_url,
                "image_key": payload.image_key,
                "message_id": payload.message_id,
            },
        )
    return LlmImageAnalyzeResponse(
        answer=answer,
        knowledge_results=knowledge,
        image_source=image_source,
        saved_source=saved_source,
    )


@app.post("/api/v1/services/{service_id}/llm/image-analyze/upload", response_model=LlmImageAnalyzeResponse)
async def analyze_uploaded_image_with_llm(
    service_id: str,
    prompt: str = Form(...),
    file: UploadFile = File(...),
    use_knowledge_base: bool = Form(False),
    knowledge_query: str | None = Form(None),
    knowledge_limit: int = Form(5),
    system_prompt_override: str | None = Form(None),
    save_analysis_to_knowledge_base: bool = Form(False),
    analysis_title: str | None = Form(None),
) -> LlmImageAnalyzeResponse:
    service = get_service_or_404(service_id)
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    kb = KnowledgeBaseService()
    resolved_knowledge_query = knowledge_query or prompt
    knowledge = (
        kb.search(service_id=service_id, query=resolved_knowledge_query, limit=knowledge_limit)
        if use_knowledge_base
        else []
    )
    llm = OpenAICompatibleLLM(service)
    answer = await llm.analyze_image(
        prompt=prompt,
        knowledge=knowledge,
        image_base64=base64.b64encode(file_bytes).decode("utf-8"),
        image_mime_type=file.content_type or "application/octet-stream",
        system_prompt_override=system_prompt_override,
    )
    saved_source = None
    if save_analysis_to_knowledge_base:
        saved_source = kb.ingest_generated_artifact(
            service_id=service_id,
            title=analysis_title or f"Uploaded Image Analysis {file.filename or 'file'}",
            content=answer,
            source_type="llm_image_analysis",
            external_id=file.filename,
            metadata={
                "image_source": "upload_file",
                "file_name": file.filename,
                "mime_type": file.content_type,
                "prompt": prompt,
            },
        )
    return LlmImageAnalyzeResponse(
        answer=answer,
        knowledge_results=knowledge,
        image_source="upload_file",
        saved_source=saved_source,
    )


@app.post("/api/v1/services/{service_id}/feishu/chats/summarize", response_model=FeishuChatSummaryResponse)
async def summarize_feishu_chat(service_id: str, payload: FeishuChatSummaryRequest) -> FeishuChatSummaryResponse:
    service = get_service_or_404(service_id)
    kb = KnowledgeBaseService()
    client = FeishuClient(service)
    try:
        messages = await client.list_chat_messages(chat_id=payload.chat_id, limit=payload.limit)
        transcript, transcript_count = build_chat_transcript(messages)
        if not transcript.strip():
            raise HTTPException(status_code=400, detail="No usable messages found in the target chat.")

        knowledge_query = payload.knowledge_query or payload.chat_id
        knowledge = (
            kb.search(service_id=service_id, query=knowledge_query, limit=payload.knowledge_limit)
            if payload.use_knowledge_base
            else []
        )

        summary_prompt = payload.summary_prompt or (
            "请对下面的飞书群聊记录做结构化总结，输出：\n"
            "1. 主要议题\n2. 关键结论\n3. 待办事项\n4. 风险与阻塞\n\n"
            f"群聊记录如下：\n{transcript}"
        )
        llm = OpenAICompatibleLLM(service)
        summary = await llm.answer(
            question=summary_prompt,
            knowledge=knowledge,
            system_prompt_override=payload.system_prompt_override,
        )
        saved_source: dict[str, Any] | None = None
        if payload.save_summary_to_knowledge_base:
            saved_source = kb.ingest_generated_artifact(
                service_id=service_id,
                title=payload.summary_title or f"Chat Summary {payload.chat_id}",
                content=summary,
                source_type="chat_summary",
                external_id=payload.chat_id,
                metadata={
                    "chat_id": payload.chat_id,
                    "limit": payload.limit,
                    "message_count": transcript_count,
                    "summary_prompt": payload.summary_prompt,
                },
            )

        sent_result: dict[str, Any] | None = None
        if payload.send_to_receive_id:
            sent_result = await client.send_text_message(
                receive_id=payload.send_to_receive_id,
                text=summary,
                receive_id_type=payload.send_to_receive_id_type,
            )
            db.log_conversation(
                service_id=service_id,
                direction="outgoing",
                chat_id=payload.send_to_receive_id if payload.send_to_receive_id_type == "chat_id" else None,
                user_id=payload.send_to_receive_id if payload.send_to_receive_id_type != "chat_id" else None,
                content=summary,
                metadata={
                    "action": "summarize_feishu_chat",
                    "source_chat_id": payload.chat_id,
                    "result": sent_result,
                },
            )
    finally:
        await client.close()

    return FeishuChatSummaryResponse(
        chat_id=payload.chat_id,
        message_count=transcript_count,
        summary=summary,
        knowledge_results=knowledge,
        sent_result=sent_result,
        saved_source=saved_source,
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


@app.post("/api/v1/services/{service_id}/agent/run", response_model=AgentRunResponse)
async def run_agent(service_id: str, payload: AgentRunRequest) -> AgentRunResponse:
    get_service_or_404(service_id)
    runtime = get_agent_runtime()
    result = await runtime.run(
        service_id=service_id,
        goal=payload.goal,
        context=payload.context,
        constraints=payload.constraints,
        policy_config=payload.policy_config,
    )
    return _build_agent_run_response(result)


@app.get("/api/v1/services/{service_id}/agent/sessions/{session_id}", response_model=AgentSessionResponse)
async def get_agent_session(service_id: str, session_id: str) -> AgentSessionResponse:
    get_service_or_404(service_id)
    runtime = get_agent_runtime()
    session = runtime.get_session(session_id)
    if session.service_id != service_id:
        raise HTTPException(status_code=404, detail="Agent session not found.")
    return _build_agent_session_response(session)


@app.get("/api/v1/services/{service_id}/agent/sessions/{session_id}/logs", response_model=AgentSessionLogResponse)
async def get_agent_session_logs(service_id: str, session_id: str) -> AgentSessionLogResponse:
    get_service_or_404(service_id)
    runtime = get_agent_runtime()
    session = runtime.get_session(session_id)
    if session.service_id != service_id:
        raise HTTPException(status_code=404, detail="Agent session not found.")
    return AgentSessionLogResponse(
        session_id=session_id,
        items=[_serialize_agent_step_log(item) for item in runtime.get_logs(session_id)],
    )


@app.post("/api/v1/services/{service_id}/agent/sessions/{session_id}/resume", response_model=AgentRunResponse)
async def resume_agent_session(service_id: str, session_id: str) -> AgentRunResponse:
    get_service_or_404(service_id)
    runtime = get_agent_runtime()
    session = runtime.get_session(session_id)
    if session.service_id != service_id:
        raise HTTPException(status_code=404, detail="Agent session not found.")
    result = await runtime.resume(session_id)
    return _build_agent_run_response(result)


@app.post("/api/v1/services/{service_id}/agent/sessions/{session_id}/cancel", response_model=AgentCancelResponse)
async def cancel_agent_session(service_id: str, session_id: str) -> AgentCancelResponse:
    get_service_or_404(service_id)
    runtime = get_agent_runtime()
    session = runtime.get_session(session_id)
    if session.service_id != service_id:
        raise HTTPException(status_code=404, detail="Agent session not found.")
    cancelled = runtime.cancel(session_id)
    return AgentCancelResponse(session_id=cancelled.id, status=cancelled.status)


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

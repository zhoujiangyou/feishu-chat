# AI GC START
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ServiceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    feishu_app_id: str = Field(min_length=3)
    feishu_app_secret: str = Field(min_length=3)
    verification_token: str | None = None
    encrypt_key: str | None = None
    llm_base_url: str = Field(min_length=8)
    llm_api_key: str = Field(min_length=1)
    llm_model: str = Field(min_length=1)
    llm_system_prompt: str | None = None


class ServiceResponse(BaseModel):
    service_id: str
    name: str
    callback_path: str
    created_at: str


class TextKnowledgeImportRequest(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FeishuDocumentImportRequest(BaseModel):
    document: str = Field(min_length=3, description="Document token or doc URL")
    title: str | None = None


class FeishuChatImportRequest(BaseModel):
    chat_id: str = Field(min_length=3)
    limit: int = Field(default=100, ge=1, le=500)


class FeishuImageImportRequest(BaseModel):
    image_key: str | None = None
    message_id: str | None = None
    title: str | None = None


class KnowledgeSearchResponse(BaseModel):
    query: str
    results: list[dict[str, Any]]


class FeishuCallbackAck(BaseModel):
    challenge: str | None = None
    status: str = "ok"


class FeishuSendMessageRequest(BaseModel):
    receive_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    receive_id_type: Literal["chat_id", "open_id", "user_id", "union_id", "email"] = "chat_id"
# AI GC END

# AI GC START
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


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


class LlmQuestionRequest(BaseModel):
    question: str = Field(min_length=1)
    use_knowledge_base: bool = True
    knowledge_limit: int = Field(default=5, ge=1, le=20)
    system_prompt_override: str | None = None


class LlmQuestionResponse(BaseModel):
    answer: str
    knowledge_results: list[dict[str, Any]]


class LlmImageAnalyzeRequest(BaseModel):
    prompt: str = Field(min_length=1)
    image_url: str | None = None
    image_base64: str | None = None
    image_mime_type: str | None = "image/png"
    image_key: str | None = None
    message_id: str | None = None
    use_knowledge_base: bool = False
    knowledge_query: str | None = None
    knowledge_limit: int = Field(default=5, ge=1, le=20)
    system_prompt_override: str | None = None
    save_analysis_to_knowledge_base: bool = False
    analysis_title: str | None = None

    @model_validator(mode="after")
    def validate_image_source(self) -> "LlmImageAnalyzeRequest":
        if any([self.image_url, self.image_base64, self.image_key, self.message_id]):
            return self
        raise ValueError("One of image_url, image_base64, image_key, or message_id is required.")


class LlmImageAnalyzeResponse(BaseModel):
    answer: str
    knowledge_results: list[dict[str, Any]]
    image_source: str
    saved_source: dict[str, Any] | None = None


class FeishuChatSummaryRequest(BaseModel):
    chat_id: str = Field(min_length=3)
    limit: int = Field(default=100, ge=1, le=500)
    use_knowledge_base: bool = False
    knowledge_query: str | None = None
    knowledge_limit: int = Field(default=5, ge=1, le=20)
    summary_prompt: str | None = None
    system_prompt_override: str | None = None
    send_to_receive_id: str | None = None
    send_to_receive_id_type: Literal["chat_id", "open_id", "user_id", "union_id", "email"] = "chat_id"
    save_summary_to_knowledge_base: bool = False
    summary_title: str | None = None


class FeishuChatSummaryResponse(BaseModel):
    chat_id: str
    message_count: int
    summary: str
    knowledge_results: list[dict[str, Any]]
    sent_result: dict[str, Any] | None = None
    saved_source: dict[str, Any] | None = None


class AgentRunRequest(BaseModel):
    goal: str = Field(min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    policy_config: dict[str, Any] = Field(default_factory=dict)


class AgentSessionResponse(BaseModel):
    session_id: str
    service_id: str
    goal: str
    status: str
    step_count: int
    max_steps: int
    context: dict[str, Any]
    constraints: dict[str, Any]
    policy_config: dict[str, Any]
    current_plan: list[str]
    working_memory: dict[str, Any]
    final_answer: str | None = None
    failure_reason: str | None = None
    created_at: str
    updated_at: str


class AgentSessionLogResponse(BaseModel):
    session_id: str
    items: list[dict[str, Any]]


class AgentRunResponse(BaseModel):
    session: AgentSessionResponse
    logs: list[dict[str, Any]] = Field(default_factory=list)


class AgentCancelResponse(BaseModel):
    session_id: str
    status: str
# AI GC END

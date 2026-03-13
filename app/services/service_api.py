# AI GC START
from __future__ import annotations

import os
from typing import Any

import httpx


DEFAULT_SERVICE_BASE_URL = os.environ.get("FEISHU_CHAT_SERVICE_BASE_URL", "http://127.0.0.1:8000")
DEFAULT_SERVICE_TIMEOUT_SECONDS = float(os.environ.get("FEISHU_CHAT_SERVICE_TIMEOUT_SECONDS", "60"))


class ServiceApiError(RuntimeError):
    """Raised when the Feishu Chat Service API returns an error."""


class FeishuChatServiceApiClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or DEFAULT_SERVICE_BASE_URL).rstrip("/")
        self.timeout = timeout or DEFAULT_SERVICE_TIMEOUT_SECONDS
        self.transport = transport

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            transport=self.transport,
        ) as client:
            response = await client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise ServiceApiError(f"Service API request failed: {response.status_code} {response.text}")
        return response.json()

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def create_service(
        self,
        *,
        name: str,
        feishu_app_id: str,
        feishu_app_secret: str,
        llm_base_url: str,
        llm_api_key: str,
        llm_model: str,
        verification_token: str | None = None,
        encrypt_key: str | None = None,
        llm_system_prompt: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/v1/services",
            json={
                "name": name,
                "feishu_app_id": feishu_app_id,
                "feishu_app_secret": feishu_app_secret,
                "verification_token": verification_token,
                "encrypt_key": encrypt_key,
                "llm_base_url": llm_base_url,
                "llm_api_key": llm_api_key,
                "llm_model": llm_model,
                "llm_system_prompt": llm_system_prompt,
            },
        )

    async def get_service(self, service_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/v1/services/{service_id}")

    async def import_text_knowledge(
        self,
        *,
        service_id: str,
        title: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/v1/services/{service_id}/knowledge-base/text",
            json={
                "title": title,
                "content": content,
                "metadata": metadata or {},
            },
        )

    async def import_feishu_document(
        self,
        *,
        service_id: str,
        document: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/v1/services/{service_id}/knowledge-base/feishu/document",
            json={"document": document, "title": title},
        )

    async def import_feishu_chat(
        self,
        *,
        service_id: str,
        chat_id: str,
        limit: int = 100,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/v1/services/{service_id}/knowledge-base/feishu/chat",
            json={"chat_id": chat_id, "limit": limit},
        )

    async def import_feishu_image(
        self,
        *,
        service_id: str,
        image_key: str | None = None,
        message_id: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/v1/services/{service_id}/knowledge-base/feishu/image",
            json={"image_key": image_key, "message_id": message_id, "title": title},
        )

    async def search_knowledge(
        self,
        *,
        service_id: str,
        query: str,
        limit: int = 5,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/api/v1/services/{service_id}/knowledge-base/search",
            params={"query": query, "limit": limit},
        )

    async def list_knowledge_sources(self, service_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/v1/services/{service_id}/knowledge-base/sources")

    async def send_feishu_message(
        self,
        *,
        service_id: str,
        receive_id: str,
        text: str,
        receive_id_type: str = "chat_id",
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/v1/services/{service_id}/feishu/messages/send",
            json={
                "receive_id": receive_id,
                "text": text,
                "receive_id_type": receive_id_type,
            },
        )

    async def ask_with_llm(
        self,
        *,
        service_id: str,
        question: str,
        use_knowledge_base: bool = True,
        knowledge_limit: int = 5,
        system_prompt_override: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/v1/services/{service_id}/llm/ask",
            json={
                "question": question,
                "use_knowledge_base": use_knowledge_base,
                "knowledge_limit": knowledge_limit,
                "system_prompt_override": system_prompt_override,
            },
        )

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
        save_analysis_to_knowledge_base: bool = False,
        analysis_title: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/v1/services/{service_id}/llm/image-analyze",
            json={
                "prompt": prompt,
                "image_url": image_url,
                "image_base64": image_base64,
                "image_mime_type": image_mime_type,
                "image_key": image_key,
                "message_id": message_id,
                "use_knowledge_base": use_knowledge_base,
                "knowledge_query": knowledge_query,
                "knowledge_limit": knowledge_limit,
                "system_prompt_override": system_prompt_override,
                "save_analysis_to_knowledge_base": save_analysis_to_knowledge_base,
                "analysis_title": analysis_title,
            },
        )

    async def summarize_feishu_chat(
        self,
        *,
        service_id: str,
        chat_id: str,
        limit: int = 100,
        use_knowledge_base: bool = False,
        knowledge_query: str | None = None,
        knowledge_limit: int = 5,
        summary_prompt: str | None = None,
        system_prompt_override: str | None = None,
        send_to_receive_id: str | None = None,
        send_to_receive_id_type: str = "chat_id",
        save_summary_to_knowledge_base: bool = False,
        summary_title: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/v1/services/{service_id}/feishu/chats/summarize",
            json={
                "chat_id": chat_id,
                "limit": limit,
                "use_knowledge_base": use_knowledge_base,
                "knowledge_query": knowledge_query,
                "knowledge_limit": knowledge_limit,
                "summary_prompt": summary_prompt,
                "system_prompt_override": system_prompt_override,
                "send_to_receive_id": send_to_receive_id,
                "send_to_receive_id_type": send_to_receive_id_type,
                "save_summary_to_knowledge_base": save_summary_to_knowledge_base,
                "summary_title": summary_title,
            },
        )
# AI GC END

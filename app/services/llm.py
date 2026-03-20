# AI GC START
from __future__ import annotations

import base64
from typing import Any

import httpx

from app.config import DEFAULT_LLM_TIMEOUT_SECONDS


def _normalize_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


class OpenAICompatibleLLM:
    def __init__(self, service: dict[str, Any]) -> None:
        self.base_url = service["llm_base_url"].rstrip("/")
        self.api_key = service["llm_api_key"]
        self.model = service["llm_model"]
        self.system_prompt = service.get("llm_system_prompt") or "你是一个飞书机器人助手。"

    async def answer(
        self,
        *,
        question: str,
        knowledge: list[dict[str, Any]],
        system_prompt_override: str | None = None,
    ) -> str:
        system_prompt = self._build_system_prompt(
            knowledge=knowledge,
            system_prompt_override=system_prompt_override,
        )
        payload = await self._chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ]
        )
        return self._extract_text(payload)

    async def chat_completion_text(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
    ) -> str:
        payload = await self._chat_completion(messages=messages, temperature=temperature)
        return self._extract_text(payload)

    async def analyze_image(
        self,
        *,
        prompt: str,
        knowledge: list[dict[str, Any]] | None = None,
        image_url: str | None = None,
        image_base64: str | None = None,
        image_mime_type: str | None = None,
        system_prompt_override: str | None = None,
    ) -> str:
        if not image_url and not image_base64:
            raise ValueError("image_url or image_base64 is required for image analysis.")

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if image_url:
            content.append({"type": "image_url", "image_url": {"url": image_url}})
        else:
            mime_type = image_mime_type or "image/png"
            data_url = self._build_data_url(image_base64=image_base64 or "", image_mime_type=mime_type)
            content.append({"type": "image_url", "image_url": {"url": data_url}})

        system_prompt = self._build_system_prompt(
            knowledge=knowledge or [],
            system_prompt_override=system_prompt_override,
        )
        payload = await self._chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ]
        )
        return self._extract_text(payload)

    def _build_system_prompt(
        self,
        *,
        knowledge: list[dict[str, Any]],
        system_prompt_override: str | None = None,
    ) -> str:
        knowledge_text = "\n\n".join(
            f"[{item['title']}#{item['chunk_index']}]\n{item['content']}" for item in knowledge
        ).strip()
        system_prompt = system_prompt_override or self.system_prompt
        if knowledge_text:
            system_prompt += (
                "\n\n以下是检索到的知识库片段，请优先基于这些内容回答；"
                "如果知识库没有覆盖，再明确说明哪些内容来自通用推理：\n"
                f"{knowledge_text}"
            )
        return system_prompt

    async def _chat_completion(self, *, messages: list[dict[str, Any]], temperature: float = 0.2) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=DEFAULT_LLM_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "temperature": temperature,
                    "messages": messages,
                },
            )
            response.raise_for_status()
            return response.json()

    def _extract_text(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError("LLM returned no choices.")
        message = choices[0].get("message", {})
        return _normalize_content(message.get("content")).strip()

    def _build_data_url(self, *, image_base64: str, image_mime_type: str) -> str:
        # Normalize whitespace to keep the OpenAI-compatible image payload compact.
        normalized = "".join(image_base64.split())
        try:
            base64.b64decode(normalized, validate=True)
        except Exception as exc:  # pragma: no cover
            raise ValueError("image_base64 must be valid base64 data.") from exc
        return f"data:{image_mime_type};base64,{normalized}"
# AI GC END

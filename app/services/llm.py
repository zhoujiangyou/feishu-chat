# AI GC START
from __future__ import annotations

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

    async def answer(self, *, question: str, knowledge: list[dict[str, Any]]) -> str:
        knowledge_text = "\n\n".join(
            f"[{item['title']}#{item['chunk_index']}]\n{item['content']}" for item in knowledge
        ).strip()
        system_prompt = self.system_prompt
        if knowledge_text:
            system_prompt += (
                "\n\n以下是检索到的知识库片段，请优先基于这些内容回答；"
                "如果知识库没有覆盖，再明确说明哪些内容来自通用推理：\n"
                f"{knowledge_text}"
            )

        async with httpx.AsyncClient(timeout=DEFAULT_LLM_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "temperature": 0.2,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question},
                    ],
                },
            )
            response.raise_for_status()
            payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError("LLM returned no choices.")
        message = choices[0].get("message", {})
        return _normalize_content(message.get("content")).strip()
# AI GC END

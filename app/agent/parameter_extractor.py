# AI GC START
from __future__ import annotations

import re
from typing import Any


CHAT_ID_PATTERN = re.compile(r"\boc_[A-Za-z0-9_-]+\b")
IMAGE_KEY_PATTERN = re.compile(r"\bimg_[A-Za-z0-9_-]+\b")
MESSAGE_ID_PATTERN = re.compile(r"\bom_[A-Za-z0-9_-]+\b")
DOCUMENT_URL_PATTERN = re.compile(r"https?://\S+")
LIMIT_PATTERN = re.compile(r"(?:最近|近|latest\s+)?(\d{1,3})\s*条")


class ParameterExtractor:
    def extract(
        self,
        *,
        goal: str,
        context: dict[str, Any] | None = None,
        constraints: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        merged_context = dict(context or {})
        merged_constraints = dict(constraints or {})
        stripped_goal = goal.strip()
        lowered_goal = stripped_goal.lower()

        self._extract_chat_targets(stripped_goal, lowered_goal, merged_context)
        self._extract_document_reference(stripped_goal, merged_context)
        self._extract_image_reference(stripped_goal, merged_context)
        self._extract_limit(stripped_goal, merged_constraints)

        if any(keyword in stripped_goal for keyword in ("发到当前群", "发送到当前群", "回发到当前群", "发到这个群", "发送到这个群")):
            if merged_context.get("chat_id") and not merged_context.get("receive_id"):
                merged_context["receive_id"] = merged_context["chat_id"]
                merged_context.setdefault("receive_id_type", "chat_id")

        return merged_context, merged_constraints

    def _extract_chat_targets(self, goal: str, lowered_goal: str, context: dict[str, Any]) -> None:
        chat_ids = CHAT_ID_PATTERN.findall(goal)
        if chat_ids and not context.get("chat_id"):
            context["chat_id"] = chat_ids[0]

        explicit_send_target = self._match_send_target(goal)
        if explicit_send_target and not context.get("receive_id"):
            context["receive_id"] = explicit_send_target
            context.setdefault("receive_id_type", "chat_id")

        if any(keyword in lowered_goal for keyword in ("当前群", "这个群", "当前 chat", "current chat")) and context.get("chat_id"):
            context.setdefault("receive_id", context["chat_id"])
            context.setdefault("receive_id_type", "chat_id")

    def _extract_document_reference(self, goal: str, context: dict[str, Any]) -> None:
        if context.get("document"):
            return
        urls = DOCUMENT_URL_PATTERN.findall(goal)
        for url in urls:
            lowered = url.lower()
            if any(keyword in lowered for keyword in ("feishu", "lark", "docx", "docs", "wiki")):
                context["document"] = url
                return

    def _extract_image_reference(self, goal: str, context: dict[str, Any]) -> None:
        if not context.get("image_key"):
            image_keys = IMAGE_KEY_PATTERN.findall(goal)
            if image_keys:
                context["image_key"] = image_keys[0]

        if not context.get("message_id"):
            message_ids = MESSAGE_ID_PATTERN.findall(goal)
            if message_ids:
                context["message_id"] = message_ids[0]

    def _extract_limit(self, goal: str, constraints: dict[str, Any]) -> None:
        if "chat_limit" in constraints:
            return
        match = LIMIT_PATTERN.search(goal)
        if match:
            constraints["chat_limit"] = int(match.group(1))

    def _match_send_target(self, goal: str) -> str | None:
        patterns = [
            r"(?:发到|发送到|回发到)(?:群|群聊)?\s*(oc_[A-Za-z0-9_-]+)",
            r"(?:发给|发送给)\s*(oc_[A-Za-z0-9_-]+)",
            r"(?:to)\s+(oc_[A-Za-z0-9_-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, goal, flags=re.IGNORECASE)
            if match:
                return match.group(1)
        return None
# AI GC END

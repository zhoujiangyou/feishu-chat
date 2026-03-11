# AI GC START
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app import db
from app.services.feishu import FeishuClient, extract_text_from_message, sanitize_user_text
from app.services.knowledge_base import KnowledgeBaseService
from app.services.llm import OpenAICompatibleLLM


HELP_TEXT = (
    "可用命令：\n"
    "1. 抓取文档 <文档链接或token>\n"
    "2. 抓取群聊 <chat_id> [limit]\n"
    "3. 抓取图片 <image_key或message_id>\n"
    "4. /kb doc <文档链接或token>\n"
    "5. /kb chat <chat_id> [limit]\n"
    "6. /kb image <image_key或message_id>\n"
    "普通文本会自动走知识库检索 + 大模型回答。"
)


@dataclass(slots=True)
class BotCommand:
    name: str
    value: str | None = None
    limit: int | None = None


def parse_bot_command(text: str) -> BotCommand | None:
    normalized = sanitize_user_text(text)
    if not normalized:
        return None
    if normalized.lower() in {"帮助", "/help", "help"}:
        return BotCommand(name="help")

    patterns = [
        (r"^(?:抓取文档|/kb\s+doc)\s+(.+)$", "import_doc"),
        (r"^(?:抓取群聊|/kb\s+chat)\s+(\S+)(?:\s+(\d+))?$", "import_chat"),
        (r"^(?:抓取图片|/kb\s+image)\s+(\S+)$", "import_image"),
    ]
    for pattern, name in patterns:
        match = re.match(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1)
        limit = int(match.group(2)) if match.lastindex and match.lastindex >= 2 and match.group(2) else None
        return BotCommand(name=name, value=value, limit=limit)
    return None


async def handle_event(service: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("challenge"):
        return {"challenge": payload["challenge"], "status": "challenge"}

    header = payload.get("header", {})
    event_type = header.get("event_type") or payload.get("type")
    if event_type != "im.message.receive_v1":
        return {"status": "ignored", "reason": f"unsupported event type {event_type}"}

    event = payload.get("event", {})
    sender = event.get("sender", {})
    if sender.get("sender_type") == "app":
        return {"status": "ignored", "reason": "skip bot self messages"}

    message = event.get("message", {})
    chat_id = message.get("chat_id")
    message_id = message.get("message_id")
    user_id = sender.get("sender_id", {}).get("open_id")
    user_text = extract_text_from_message(message)

    db.log_conversation(
        service_id=service["id"],
        direction="incoming",
        chat_id=chat_id,
        message_id=message_id,
        user_id=user_id,
        content=user_text or f"[{message.get('message_type', 'unknown')}]",
        metadata=message,
    )

    kb = KnowledgeBaseService()
    client = FeishuClient(service)
    try:
        if message.get("message_type") == "image":
            source = await kb.import_feishu_image(
                service_id=service["id"],
                client=client,
                message_id=message_id,
                title=f"Image from {chat_id or 'chat'}",
            )
            reply = f"图片已抓取并入库：{source['title']}"
            await client.reply_text_message(message_id=message_id, text=reply)
            db.log_conversation(
                service_id=service["id"],
                direction="outgoing",
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                content=reply,
            )
            return {"status": "ingested_image", "source_id": source["id"]}

        command = parse_bot_command(user_text)
        if command:
            reply = await _execute_command(
                service=service,
                client=client,
                kb=kb,
                command=command,
                message_id=message_id,
            )
            db.log_conversation(
                service_id=service["id"],
                direction="outgoing",
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                content=reply,
            )
            return {"status": "command_executed", "command": command.name}

        query = sanitize_user_text(user_text)
        knowledge = kb.search(service_id=service["id"], query=query, limit=5) if query else []
        llm = OpenAICompatibleLLM(service)
        answer = await llm.answer(question=query or "请说明收到的消息内容。", knowledge=knowledge)
        await client.reply_text_message(message_id=message_id, text=answer)
        db.log_conversation(
            service_id=service["id"],
            direction="outgoing",
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            content=answer,
            metadata={"knowledge_count": len(knowledge)},
        )
        return {"status": "answered", "knowledge_count": len(knowledge)}
    finally:
        await client.close()


async def _execute_command(
    *,
    service: dict[str, Any],
    client: FeishuClient,
    kb: KnowledgeBaseService,
    command: BotCommand,
    message_id: str,
) -> str:
    if command.name == "help":
        await client.reply_text_message(message_id=message_id, text=HELP_TEXT)
        return HELP_TEXT

    if command.name == "import_doc" and command.value:
        source = await kb.import_feishu_document(
            service_id=service["id"],
            client=client,
            document=command.value,
        )
        reply = f"文档已抓取并入库：{source['title']}"
        await client.reply_text_message(message_id=message_id, text=reply)
        return reply

    if command.name == "import_chat" and command.value:
        source = await kb.import_feishu_chat(
            service_id=service["id"],
            client=client,
            chat_id=command.value,
            limit=command.limit or 100,
        )
        reply = f"群聊记录已抓取并入库：{source['title']}"
        await client.reply_text_message(message_id=message_id, text=reply)
        return reply

    if command.name == "import_image" and command.value:
        source = await kb.import_feishu_image(
            service_id=service["id"],
            client=client,
            image_key=command.value if command.value.startswith("img_") else None,
            message_id=None if command.value.startswith("img_") else command.value,
        )
        reply = f"图片已抓取并入库：{source['title']}"
        await client.reply_text_message(message_id=message_id, text=reply)
        return reply

    raise ValueError(f"Unsupported command: {command.name}")
# AI GC END

# AI GC START
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Any

from app import db
from app.services.feishu import FeishuClient, extract_image_key_from_message, extract_text_from_message, sanitize_user_text
from app.services.knowledge_base import KnowledgeBaseService, build_chat_transcript
from app.services.llm import OpenAICompatibleLLM


HELP_TEXT = (
    "可用命令：\n"
    "1. 抓取文档 <文档链接或token>\n"
    "2. 抓取群聊 <chat_id> [limit]\n"
    "3. 抓取当前群 [limit]\n"
    "4. 总结当前群 [limit]\n"
    "5. 抓取图片 <image_key或message_id>\n"
    "6. /kb doc <文档链接或token>\n"
    "7. /kb chat <chat_id> [limit]\n"
    "8. /kb image <image_key或message_id>\n"
    "9. 直接发送图片，机器人会自动做视觉分析并回复，并把分析结果写回知识库。\n"
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
        (r"^(?:抓取当前群|抓取当前群聊天记录|/kb\s+current-chat)(?:\s+(\d+))?$", "import_current_chat"),
        (r"^(?:总结当前群|总结当前群聊天记录|/sum\s+current-chat)(?:\s+(\d+))?$", "summarize_current_chat"),
    ]
    for pattern, name in patterns:
        match = re.match(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1) if match.lastindex and match.lastindex >= 1 else None
        limit = None
        if name in {"import_current_chat", "summarize_current_chat"}:
            limit = int(match.group(1)) if match.lastindex and match.group(1) else None
            value = None
        else:
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
            image_key = extract_image_key_from_message(message)
            image_reply = ""
            if image_key:
                image_bytes, mime_type = await client.download_image(image_key)
                llm = OpenAICompatibleLLM(service)
                image_reply = await llm.analyze_image(
                    prompt="请用简洁中文描述这张图片的主要内容，并指出可见的关键信息或风险。",
                    knowledge=[],
                    image_base64=base64.b64encode(image_bytes).decode("utf-8"),
                    image_mime_type=mime_type or "image/png",
                )
                kb.ingest_generated_artifact(
                    service_id=service["id"],
                    title=f"Image Analysis {image_key}",
                    content=image_reply,
                    source_type="llm_image_analysis",
                    external_id=image_key,
                    metadata={"source_id": source["id"], "chat_id": chat_id, "message_id": message_id},
                )
            reply = (
                f"图片已抓取并入库：{source['title']}\n\n图片分析：{image_reply}"
                if image_reply
                else f"图片已抓取并入库：{source['title']}"
            )
            await client.reply_text_message(message_id=message_id, text=reply)
            db.log_conversation(
                service_id=service["id"],
                direction="outgoing",
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                content=reply,
                metadata={"source_id": source["id"], "image_analyzed": bool(image_reply)},
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
                chat_id=chat_id,
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
    chat_id: str | None,
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

    if command.name == "import_current_chat":
        if not chat_id:
            raise ValueError("Current chat_id is missing for import_current_chat.")
        source = await kb.import_feishu_chat(
            service_id=service["id"],
            client=client,
            chat_id=chat_id,
            limit=command.limit or 100,
        )
        reply = f"当前群聊天记录已抓取并入库：{source['title']}"
        await client.reply_text_message(message_id=message_id, text=reply)
        return reply

    if command.name == "summarize_current_chat":
        if not chat_id:
            raise ValueError("Current chat_id is missing for summarize_current_chat.")
        summary = await _summarize_current_chat(
            service=service,
            client=client,
            kb=kb,
            chat_id=chat_id,
            limit=command.limit or 100,
        )
        await client.reply_text_message(message_id=message_id, text=summary)
        return summary

    raise ValueError(f"Unsupported command: {command.name}")


async def _summarize_current_chat(
    *,
    service: dict[str, Any],
    client: FeishuClient,
    kb: KnowledgeBaseService,
    chat_id: str,
    limit: int,
) -> str:
    messages = await client.list_chat_messages(chat_id=chat_id, limit=limit)
    if not messages:
        return "当前群暂无可总结的聊天记录。"

    transcript, transcript_count = build_chat_transcript(messages)
    if not transcript.strip():
        return "当前群暂无可总结的文本内容。"

    knowledge = kb.search(service_id=service["id"], query=chat_id, limit=5)
    llm = OpenAICompatibleLLM(service)
    summary = await llm.answer(
        question=(
            "请对下面的当前群聊天记录做结构化总结，输出：\n"
            "1. 主要议题\n2. 关键结论\n3. 待办事项\n4. 风险与阻塞\n\n"
            f"群聊记录如下：\n{transcript}"
        ),
        knowledge=knowledge,
    )
    kb.ingest_generated_artifact(
        service_id=service["id"],
        title=f"Current Chat Summary {chat_id}",
        content=summary,
        source_type="chat_summary",
        external_id=chat_id,
        metadata={"chat_id": chat_id, "limit": limit, "message_count": transcript_count},
    )
    return summary
# AI GC END

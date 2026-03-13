# AI GC START
from __future__ import annotations

import json
import mimetypes
import re
from pathlib import Path
from typing import Any

from app.config import DATA_DIR
from app import db
from app.services.feishu import FeishuClient, extract_image_key_from_message, extract_text_from_message


def build_default_knowledge(service_name: str) -> str:
    return f"""
服务名称：{service_name}

这是一个飞书机器人服务，核心能力包括：
1. 接收飞书事件回调并处理机器人消息。
2. 把用户任务转发到后台配置的大模型。
3. 在回答前检索本地知识库，为回答提供上下文。
4. 支持抓取飞书文档、群聊记录、图片并沉淀到知识库。

推荐的机器人使用方式：
- 普通提问：直接发送文本，机器人会先检索知识库，再调用大模型回答。
- 导入文档：抓取文档 <文档链接或token>
- 导入群聊：抓取群聊 <chat_id> [limit]
- 导入图片：抓取图片 <image_key或message_id>
- 查看帮助：帮助

推荐飞书权限：
- im:message
- im:message:send_as_bot
- im:resource
- docx / wiki / drive 读取权限

部署建议：
- 飞书事件回调地址指向 /api/v1/feishu/<service_id>/callback
- 打开事件订阅并订阅 im.message.receive_v1
- 如启用 Encrypt Key，则服务端也要配置 encrypt_key
- 如启用 Verification Token，则服务端也要配置 verification_token
""".strip()


def chunk_text(text: str, chunk_size: int = 600, overlap: int = 120) -> list[str]:
    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not cleaned:
        return []
    if len(cleaned) <= chunk_size:
        return [cleaned]

    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + chunk_size)
        piece = cleaned[start:end]
        if end < len(cleaned):
            split_at = max(piece.rfind("\n\n"), piece.rfind("\n"), piece.rfind("。"), piece.rfind("."), piece.rfind(" "))
            if split_at > int(chunk_size * 0.5):
                end = start + split_at + 1
                piece = cleaned[start:end]
        chunks.append(piece.strip())
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return [chunk for chunk in chunks if chunk]


def _collect_text_fragments(value: Any, sink: list[str]) -> None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            sink.append(stripped)
        return
    if isinstance(value, list):
        for item in value:
            _collect_text_fragments(item, sink)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"token", "block_id", "parent_id", "page_token", "image_key"}:
                continue
            _collect_text_fragments(item, sink)


def build_chat_transcript(messages: list[dict[str, Any]]) -> tuple[str, int]:
    lines: list[str] = []
    for message in messages:
        text = extract_text_from_message(message)
        if not text and message.get("message_type") == "image":
            image_key = extract_image_key_from_message(message)
            text = f"[image] image_key={image_key}" if image_key else "[image]"
        if not text:
            continue
        sender = (
            message.get("sender", {})
            .get("sender_id", {})
            .get("open_id")
            or message.get("sender", {}).get("name")
            or "unknown"
        )
        created_at = message.get("create_time", "")
        lines.append(f"[{created_at}] {sender}: {text}")
    return "\n".join(lines), len(lines)


class KnowledgeBaseService:
    def ingest_text(
        self,
        *,
        service_id: str,
        title: str,
        content: str,
        source_type: str = "text",
        external_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source = db.create_source(
            service_id=service_id,
            source_type=source_type,
            title=title,
            external_id=external_id,
            content=content,
            metadata=metadata,
        )
        chunks = chunk_text(content)
        db.add_chunks(
            service_id=service_id,
            source_id=source["id"],
            chunks=chunks,
            metadata={"title": title, **(metadata or {})},
        )
        return source

    def search(self, *, service_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return db.search_chunks(service_id=service_id, query=query, limit=limit)

    def list_sources(self, *, service_id: str) -> list[dict[str, Any]]:
        return db.list_sources(service_id)

    async def import_feishu_document(
        self,
        *,
        service_id: str,
        client: FeishuClient,
        document: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        blocks = await client.get_document_blocks(document)
        fragments: list[str] = []
        for block in blocks:
            _collect_text_fragments(block, fragments)
        content = "\n".join(dict.fromkeys(fragment for fragment in fragments if fragment))
        return self.ingest_text(
            service_id=service_id,
            title=title or f"Feishu Document {document}",
            content=content,
            source_type="feishu_document",
            external_id=document,
            metadata={"document": document, "block_count": len(blocks)},
        )

    async def import_feishu_chat(
        self,
        *,
        service_id: str,
        client: FeishuClient,
        chat_id: str,
        limit: int,
    ) -> dict[str, Any]:
        messages = await client.list_chat_messages(chat_id=chat_id, limit=limit)
        content, line_count = build_chat_transcript(messages)
        return self.ingest_text(
            service_id=service_id,
            title=f"Feishu Chat {chat_id}",
            content=content,
            source_type="feishu_chat",
            external_id=chat_id,
            metadata={"chat_id": chat_id, "message_count": len(messages), "line_count": line_count},
        )

    async def import_feishu_image(
        self,
        *,
        service_id: str,
        client: FeishuClient,
        image_key: str | None = None,
        message_id: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        message: dict[str, Any] | None = None
        resolved_image_key = image_key
        if not resolved_image_key and message_id:
            message = await client.get_message(message_id)
            resolved_image_key = extract_image_key_from_message(message)
        if not resolved_image_key:
            raise ValueError("image_key or message_id must resolve to a valid image.")

        image_bytes, mime_type = await client.download_image(resolved_image_key)
        extension = mimetypes.guess_extension(mime_type or "") or ".bin"
        asset_dir = DATA_DIR / service_id / "images"
        asset_dir.mkdir(parents=True, exist_ok=True)
        file_path = asset_dir / f"{resolved_image_key}{extension}"
        file_path.write_bytes(image_bytes)

        image_title = title or f"Feishu Image {resolved_image_key}"
        placeholder_content = json.dumps(
            {
                "title": image_title,
                "image_key": resolved_image_key,
                "message_id": message_id,
                "note": "Image asset downloaded from Feishu. Extend this pipeline with OCR or multimodal captioning if needed.",
            },
            ensure_ascii=False,
        )

        source = self.ingest_text(
            service_id=service_id,
            title=image_title,
            content=placeholder_content,
            source_type="feishu_image",
            external_id=resolved_image_key,
            metadata={"image_key": resolved_image_key, "message_id": message_id},
        )
        db.add_asset(
            service_id=service_id,
            source_id=source["id"],
            asset_type="image",
            file_name=file_path.name,
            local_path=Path(file_path),
            mime_type=mime_type,
            metadata={"image_key": resolved_image_key, "message_id": message_id, "message": message or {}},
        )
        return source
# AI GC END

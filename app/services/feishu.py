# AI GC START
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from Crypto.Cipher import AES


class FeishuError(RuntimeError):
    """Raised when Feishu API interaction fails."""


_TOKEN_CACHE: dict[str, dict[str, Any]] = {}


@dataclass(slots=True)
class FeishuCredentials:
    app_id: str
    app_secret: str
    verification_token: str | None
    encrypt_key: str | None


def parse_credentials(service: dict[str, Any]) -> FeishuCredentials:
    return FeishuCredentials(
        app_id=service["feishu_app_id"],
        app_secret=service["feishu_app_secret"],
        verification_token=service.get("verification_token"),
        encrypt_key=service.get("encrypt_key"),
    )


def verify_callback_signature(
    *,
    timestamp: str | None,
    nonce: str | None,
    signature: str | None,
    encrypt_key: str,
    raw_body: bytes,
) -> bool:
    if not timestamp or not nonce or not signature:
        return True
    digest = hashlib.sha256()
    digest.update(f"{timestamp}{nonce}{encrypt_key}".encode("utf-8"))
    digest.update(raw_body)
    expected = digest.hexdigest()
    return expected.lower() == signature.lower()


def _pkcs7_unpad(content: bytes) -> bytes:
    if not content:
        raise FeishuError("Empty encrypted payload.")
    pad_length = content[-1]
    if pad_length < 1 or pad_length > 16:
        raise FeishuError("Invalid PKCS7 padding.")
    return content[:-pad_length]


def decrypt_callback_payload(encrypted: str, encrypt_key: str) -> dict[str, Any]:
    key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
    raw = base64.b64decode(encrypted)
    iv = raw[:16]
    cipher_text = raw[16:]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    plain_text = cipher.decrypt(cipher_text)
    decoded = _pkcs7_unpad(plain_text).decode("utf-8")
    return json.loads(decoded)


def decode_callback_body(
    raw_body: bytes,
    headers: dict[str, str],
    credentials: FeishuCredentials | dict[str, Any],
) -> dict[str, Any]:
    if isinstance(credentials, dict):
        credentials = parse_credentials(credentials)
    payload = json.loads(raw_body.decode("utf-8") or "{}")
    if "encrypt" in payload:
        if not credentials.encrypt_key:
            raise FeishuError("Encrypted callback received but encrypt_key is missing.")
        is_valid = verify_callback_signature(
            timestamp=headers.get("x-lark-request-timestamp"),
            nonce=headers.get("x-lark-request-nonce"),
            signature=headers.get("x-lark-signature"),
            encrypt_key=credentials.encrypt_key,
            raw_body=raw_body,
        )
        if not is_valid:
            raise FeishuError("Invalid Feishu callback signature.")
        payload = decrypt_callback_payload(payload["encrypt"], credentials.encrypt_key)

    token = payload.get("token")
    if credentials.verification_token and token and token != credentials.verification_token:
        raise FeishuError("Invalid Feishu verification token.")
    return payload


def extract_doc_token(document: str) -> str:
    if document.startswith("http://") or document.startswith("https://"):
        path = urlparse(document).path
        match = re.search(r"/(docx|docs|wiki)/([^/?]+)", path)
        if match:
            return match.group(2)
    return document.strip()


def extract_text_from_message(message: dict[str, Any]) -> str:
    content = message.get("content")
    if not content:
        return ""
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return content
    if message.get("message_type") == "text":
        return sanitize_user_text(content.get("text", ""))
    if message.get("message_type") == "post":
        return json.dumps(content, ensure_ascii=False)
    if "text" in content:
        return sanitize_user_text(str(content["text"]))
    return json.dumps(content, ensure_ascii=False)


def extract_image_key_from_message(message: dict[str, Any]) -> str | None:
    content = message.get("content")
    if not content:
        return None
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return None
    return content.get("image_key")


def sanitize_user_text(text: str) -> str:
    text = re.sub(r"<at[^>]*>.*?</at>", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


class FeishuClient:
    def __init__(self, service: dict[str, Any]) -> None:
        self.service = service
        self.credentials = parse_credentials(service)
        self.base_url = "https://open.feishu.cn"
        self.http = httpx.AsyncClient(base_url=self.base_url, timeout=60.0)

    async def close(self) -> None:
        await self.http.aclose()

    async def get_tenant_access_token(self) -> str:
        cache_key = self.credentials.app_id
        cached = _TOKEN_CACHE.get(cache_key)
        now = time.time()
        if cached and cached["expires_at"] > now + 30:
            return cached["token"]

        response = await self.http.post(
            "/open-apis/auth/v3/tenant_access_token/internal",
            json={
                "app_id": self.credentials.app_id,
                "app_secret": self.credentials.app_secret,
            },
        )
        data = self._parse_json(response)
        token = data["tenant_access_token"]
        _TOKEN_CACHE[cache_key] = {
            "token": token,
            "expires_at": now + int(data.get("expire", 7200)),
        }
        return token

    async def api_request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        token = await self.get_tenant_access_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        response = await self.http.request(method, path, headers=headers, **kwargs)
        return self._parse_json(response)

    async def send_text_message(
        self,
        *,
        receive_id: str,
        text: str,
        receive_id_type: str = "chat_id",
    ) -> dict[str, Any]:
        return await self.api_request(
            "POST",
            "/open-apis/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            json={
                "receive_id": receive_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )

    async def reply_text_message(self, *, message_id: str, text: str) -> dict[str, Any]:
        return await self.api_request(
            "POST",
            f"/open-apis/im/v1/messages/{message_id}/reply",
            json={
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )

    async def get_message(self, message_id: str) -> dict[str, Any]:
        payload = await self.api_request("GET", f"/open-apis/im/v1/messages/{message_id}")
        return payload.get("data", {}).get("items", [{}])[0] if "items" in payload.get("data", {}) else payload.get("data", {})

    async def list_chat_messages(
        self,
        *,
        chat_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        page_token: str | None = None

        while len(messages) < limit:
            payload = await self.api_request(
                "GET",
                "/open-apis/im/v1/messages",
                params={
                    "container_id_type": "chat",
                    "container_id": chat_id,
                    "page_size": min(50, limit - len(messages)),
                    **({"page_token": page_token} if page_token else {}),
                },
            )
            data = payload.get("data", {})
            batch = data.get("items", [])
            messages.extend(batch)
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            if not page_token:
                break
        return messages[:limit]

    async def get_document_blocks(self, document: str) -> list[dict[str, Any]]:
        document_id = extract_doc_token(document)
        blocks: list[dict[str, Any]] = []
        page_token: str | None = None

        while True:
            payload = await self.api_request(
                "GET",
                f"/open-apis/docx/v1/documents/{document_id}/blocks",
                params={
                    "page_size": 100,
                    "document_revision_id": -1,
                    **({"page_token": page_token} if page_token else {}),
                },
            )
            data = payload.get("data", {})
            blocks.extend(data.get("items", []))
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            if not page_token:
                break
        return blocks

    async def download_image(self, image_key: str) -> tuple[bytes, str | None]:
        token = await self.get_tenant_access_token()
        response = await self.http.get(
            "/open-apis/im/v1/images",
            params={"image_key": image_key},
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code >= 400:
            raise FeishuError(f"Failed to download image: {response.status_code} {response.text}")
        return response.content, response.headers.get("content-type")

    def _parse_json(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            raise FeishuError(f"Feishu API request failed: {response.status_code} {response.text}")
        data = response.json()
        code = data.get("code", 0)
        if code not in (0, None):
            raise FeishuError(data.get("msg") or f"Feishu API error code: {code}")
        return data
# AI GC END

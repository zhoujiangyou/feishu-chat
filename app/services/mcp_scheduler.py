# AI GC START
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import uuid
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from app.config import DATA_DIR


logger = logging.getLogger(__name__)

DEFAULT_TASK_DB_PATH = Path(
    os.environ.get("FEISHU_CHAT_MCP_TASK_DB_PATH", DATA_DIR / "mcp_tasks.db")
).resolve()
DEFAULT_SCHEDULER_POLL_SECONDS = float(os.environ.get("FEISHU_CHAT_MCP_SCHEDULER_POLL_SECONDS", "5"))

SUPPORTED_SCHEDULED_ACTIONS: dict[str, dict[str, Any]] = {
    "send_feishu_message": {
        "description": "Send a Feishu text message to a group or a user.",
        "required_payload_fields": ["receive_id", "text"],
        "optional_payload_fields": ["receive_id_type"],
    },
    "import_feishu_chat": {
        "description": "Import Feishu group chat history into the knowledge base.",
        "required_payload_fields": ["chat_id"],
        "optional_payload_fields": ["limit"],
    },
    "import_feishu_document": {
        "description": "Import a Feishu document into the knowledge base.",
        "required_payload_fields": ["document"],
        "optional_payload_fields": ["title"],
    },
    "import_feishu_image": {
        "description": "Import a Feishu image into the knowledge base.",
        "required_payload_fields": [],
        "optional_payload_fields": ["image_key", "message_id", "title"],
    },
    "import_text_knowledge": {
        "description": "Import free-form text into the knowledge base.",
        "required_payload_fields": ["title", "content"],
        "optional_payload_fields": ["metadata"],
    },
    "summarize_feishu_chat": {
        "description": "Summarize a Feishu group chat and optionally send the summary to a target.",
        "required_payload_fields": ["chat_id"],
        "optional_payload_fields": [
            "limit",
            "use_knowledge_base",
            "knowledge_query",
            "knowledge_limit",
            "summary_prompt",
            "system_prompt_override",
            "send_to_receive_id",
            "send_to_receive_id_type",
            "save_summary_to_knowledge_base",
            "summary_title",
        ],
    },
}


class ScheduledTaskError(RuntimeError):
    """Raised when scheduled task storage or execution fails."""


def _dict_factory(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    return {column[0]: row[index] for index, column in enumerate(cursor.description)}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


@contextmanager
def _get_connection(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, check_same_thread=False)
    connection.row_factory = _dict_factory
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def _loads_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _validate_payload(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if action_type not in SUPPORTED_SCHEDULED_ACTIONS:
        raise ScheduledTaskError(f"Unsupported scheduled action: {action_type}")

    metadata = SUPPORTED_SCHEDULED_ACTIONS[action_type]
    for field in metadata["required_payload_fields"]:
        if field not in payload or payload[field] in (None, ""):
            raise ScheduledTaskError(f"Missing required payload field '{field}' for action '{action_type}'.")

    if action_type == "import_feishu_image" and not (payload.get("image_key") or payload.get("message_id")):
        raise ScheduledTaskError("Scheduled action 'import_feishu_image' requires image_key or message_id.")

    normalized = dict(payload)
    if action_type == "send_feishu_message":
        normalized.setdefault("receive_id_type", "chat_id")
    if action_type == "import_feishu_chat":
        normalized.setdefault("limit", 100)
    if action_type == "summarize_feishu_chat":
        normalized.setdefault("limit", 100)
        normalized.setdefault("use_knowledge_base", False)
        normalized.setdefault("knowledge_limit", 5)
        normalized.setdefault("send_to_receive_id_type", "chat_id")
        normalized.setdefault("save_summary_to_knowledge_base", False)
    return normalized


class ScheduledTaskStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DEFAULT_TASK_DB_PATH
        self.init_db()

    def init_db(self) -> None:
        with _get_connection(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    interval_seconds INTEGER NOT NULL,
                    enabled INTEGER NOT NULL,
                    next_run_at TEXT NOT NULL,
                    last_run_at TEXT,
                    last_status TEXT,
                    last_error TEXT,
                    last_result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def create_interval_task(
        self,
        *,
        name: str,
        service_id: str,
        action_type: str,
        payload: dict[str, Any],
        interval_seconds: int,
        enabled: bool = True,
        run_immediately: bool = False,
    ) -> dict[str, Any]:
        if interval_seconds < 1:
            raise ScheduledTaskError("interval_seconds must be at least 1.")
        normalized_payload = _validate_payload(action_type, payload)
        now = _utcnow()
        next_run_at = now if run_immediately else now + timedelta(seconds=interval_seconds)
        task_id = str(uuid.uuid4())
        with _get_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO scheduled_tasks (
                    id, name, service_id, action_type, payload_json,
                    interval_seconds, enabled, next_run_at, last_run_at,
                    last_status, last_error, last_result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    name,
                    service_id,
                    action_type,
                    json.dumps(normalized_payload, ensure_ascii=False),
                    interval_seconds,
                    1 if enabled else 0,
                    next_run_at.isoformat(),
                    None,
                    None,
                    None,
                    None,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        with _get_connection(self.db_path) as connection:
            cursor = connection.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
        if not row:
            raise ScheduledTaskError(f"Scheduled task not found: {task_id}")
        return self._deserialize_task(row)

    def list_tasks(self, service_id: str | None = None) -> list[dict[str, Any]]:
        with _get_connection(self.db_path) as connection:
            if service_id:
                cursor = connection.execute(
                    "SELECT * FROM scheduled_tasks WHERE service_id = ? ORDER BY created_at DESC",
                    (service_id,),
                )
            else:
                cursor = connection.execute("SELECT * FROM scheduled_tasks ORDER BY created_at DESC")
            rows = cursor.fetchall()
        return [self._deserialize_task(row) for row in rows]

    def delete_task(self, task_id: str) -> None:
        with _get_connection(self.db_path) as connection:
            cursor = connection.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        if cursor.rowcount == 0:
            raise ScheduledTaskError(f"Scheduled task not found: {task_id}")

    def set_task_enabled(self, task_id: str, enabled: bool) -> dict[str, Any]:
        task = self.get_task(task_id)
        next_run_at = task["next_run_at"]
        if enabled:
            next_run_at = (_utcnow() + timedelta(seconds=task["interval_seconds"])).isoformat()
        with _get_connection(self.db_path) as connection:
            connection.execute(
                """
                UPDATE scheduled_tasks
                SET enabled = ?, next_run_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (1 if enabled else 0, next_run_at, _utcnow_iso(), task_id),
            )
        return self.get_task(task_id)

    def fetch_due_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        now = _utcnow_iso()
        with _get_connection(self.db_path) as connection:
            cursor = connection.execute(
                """
                SELECT * FROM scheduled_tasks
                WHERE enabled = 1 AND next_run_at <= ?
                ORDER BY next_run_at ASC
                LIMIT ?
                """,
                (now, limit),
            )
            rows = cursor.fetchall()
        return [self._deserialize_task(row) for row in rows]

    def update_after_run(
        self,
        *,
        task_id: str,
        status: str,
        next_run_at: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        now = _utcnow_iso()
        with _get_connection(self.db_path) as connection:
            connection.execute(
                """
                UPDATE scheduled_tasks
                SET last_run_at = ?, last_status = ?, last_error = ?,
                    last_result_json = ?, next_run_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    now,
                    status,
                    error,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    next_run_at,
                    now,
                    task_id,
                ),
            )
        return self.get_task(task_id)

    def _deserialize_task(self, row: dict[str, Any]) -> dict[str, Any]:
        task = dict(row)
        task["enabled"] = bool(task["enabled"])
        task["payload"] = _loads_json(task.pop("payload_json"), {})
        task["last_result"] = _loads_json(task.pop("last_result_json"), None)
        return task


class ScheduledTaskManager:
    def __init__(
        self,
        *,
        api_client_factory: Callable[[], Any],
        store: ScheduledTaskStore | None = None,
        poll_seconds: float | None = None,
    ) -> None:
        self.api_client_factory = api_client_factory
        self.store = store or ScheduledTaskStore()
        self.poll_seconds = poll_seconds or DEFAULT_SCHEDULER_POLL_SECONDS
        self._runner_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._running_task_ids: set[str] = set()

    async def start(self) -> None:
        if self._runner_task and not self._runner_task.done():
            return
        self.store.init_db()
        self._stop_event = asyncio.Event()
        self._runner_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if not self._runner_task:
            return
        self._stop_event.set()
        self._runner_task.cancel()
        with suppress(asyncio.CancelledError):
            await self._runner_task
        self._runner_task = None

    def create_interval_task(
        self,
        *,
        name: str,
        service_id: str,
        action_type: str,
        payload: dict[str, Any],
        interval_seconds: int,
        enabled: bool = True,
        run_immediately: bool = False,
    ) -> dict[str, Any]:
        return self.store.create_interval_task(
            name=name,
            service_id=service_id,
            action_type=action_type,
            payload=payload,
            interval_seconds=interval_seconds,
            enabled=enabled,
            run_immediately=run_immediately,
        )

    def list_tasks(self, service_id: str | None = None) -> list[dict[str, Any]]:
        return self.store.list_tasks(service_id=service_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        return self.store.get_task(task_id)

    def delete_task(self, task_id: str) -> None:
        self.store.delete_task(task_id)

    def pause_task(self, task_id: str) -> dict[str, Any]:
        return self.store.set_task_enabled(task_id, enabled=False)

    def resume_task(self, task_id: str) -> dict[str, Any]:
        return self.store.set_task_enabled(task_id, enabled=True)

    async def run_task_now(self, task_id: str) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        await self._execute_task(task)
        return self.store.get_task(task_id)

    async def process_due_tasks_once(self) -> list[dict[str, Any]]:
        due_tasks = self.store.fetch_due_tasks()
        results: list[dict[str, Any]] = []
        for task in due_tasks:
            if task["id"] in self._running_task_ids:
                continue
            await self._execute_task(task)
            results.append(self.store.get_task(task["id"]))
        return results

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.process_due_tasks_once()
            except Exception:
                logger.exception("MCP scheduled task loop failed.")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                continue

    async def _execute_task(self, task: dict[str, Any]) -> None:
        task_id = task["id"]
        self._running_task_ids.add(task_id)
        try:
            result = await self._dispatch(task)
            self.store.update_after_run(
                task_id=task_id,
                status="success",
                result=result,
                error=None,
                next_run_at=(_utcnow() + timedelta(seconds=task["interval_seconds"])).isoformat(),
            )
        except Exception as exc:
            logger.exception("Scheduled task execution failed: %s", task_id)
            self.store.update_after_run(
                task_id=task_id,
                status="error",
                result=None,
                error=str(exc),
                next_run_at=(_utcnow() + timedelta(seconds=task["interval_seconds"])).isoformat(),
            )
        finally:
            self._running_task_ids.discard(task_id)

    async def _dispatch(self, task: dict[str, Any]) -> dict[str, Any]:
        payload = task["payload"]
        client = self.api_client_factory()
        action_type = task["action_type"]

        if action_type == "send_feishu_message":
            return await client.send_feishu_message(service_id=task["service_id"], **payload)
        if action_type == "import_feishu_chat":
            return await client.import_feishu_chat(service_id=task["service_id"], **payload)
        if action_type == "import_feishu_document":
            return await client.import_feishu_document(service_id=task["service_id"], **payload)
        if action_type == "import_feishu_image":
            return await client.import_feishu_image(service_id=task["service_id"], **payload)
        if action_type == "import_text_knowledge":
            return await client.import_text_knowledge(service_id=task["service_id"], **payload)
        if action_type == "summarize_feishu_chat":
            return await client.summarize_feishu_chat(service_id=task["service_id"], **payload)
        raise ScheduledTaskError(f"Unsupported scheduled action: {action_type}")
# AI GC END

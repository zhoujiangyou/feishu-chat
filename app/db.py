# AI GC START
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Generator

from app.config import DB_PATH


def _dict_factory(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    return {column[0]: row[index] for index, column in enumerate(cursor.description)}


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, check_same_thread=False)
    connection.row_factory = _dict_factory
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _loads_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS services (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                feishu_app_id TEXT NOT NULL,
                feishu_app_secret TEXT NOT NULL,
                verification_token TEXT,
                encrypt_key TEXT,
                llm_base_url TEXT NOT NULL,
                llm_api_key TEXT NOT NULL,
                llm_model TEXT NOT NULL,
                llm_system_prompt TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_sessions (
                id TEXT PRIMARY KEY,
                service_id TEXT NOT NULL,
                goal TEXT NOT NULL,
                parent_session_id TEXT,
                agent_type TEXT NOT NULL,
                status TEXT NOT NULL,
                step_count INTEGER NOT NULL,
                max_steps INTEGER NOT NULL,
                context_json TEXT NOT NULL,
                constraints_json TEXT NOT NULL,
                policy_config_json TEXT NOT NULL,
                current_plan_json TEXT NOT NULL,
                working_memory_json TEXT NOT NULL,
                final_answer TEXT,
                failure_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(service_id) REFERENCES services(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_step_logs (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                plan_decision_json TEXT NOT NULL,
                observation_json TEXT,
                verification_json TEXT,
                processor_state_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES agent_sessions(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_sources (
                id TEXT PRIMARY KEY,
                service_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                title TEXT NOT NULL,
                external_id TEXT,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(service_id) REFERENCES services(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                service_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(source_id) REFERENCES knowledge_sources(id),
                FOREIGN KEY(service_id) REFERENCES services(id)
            )
            """
        )
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts
            USING fts5(chunk_id UNINDEXED, service_id UNINDEXED, content)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS assets (
                id TEXT PRIMARY KEY,
                source_id TEXT,
                service_id TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                file_name TEXT NOT NULL,
                mime_type TEXT,
                local_path TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(source_id) REFERENCES knowledge_sources(id),
                FOREIGN KEY(service_id) REFERENCES services(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_logs (
                id TEXT PRIMARY KEY,
                service_id TEXT NOT NULL,
                direction TEXT NOT NULL,
                chat_id TEXT,
                message_id TEXT,
                user_id TEXT,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(service_id) REFERENCES services(id)
            )
            """
        )


def create_service(payload: dict[str, Any]) -> dict[str, Any]:
    service = {
        "id": str(uuid.uuid4()),
        "name": payload["name"],
        "feishu_app_id": payload["feishu_app_id"],
        "feishu_app_secret": payload["feishu_app_secret"],
        "verification_token": payload.get("verification_token"),
        "encrypt_key": payload.get("encrypt_key"),
        "llm_base_url": payload["llm_base_url"].rstrip("/"),
        "llm_api_key": payload["llm_api_key"],
        "llm_model": payload["llm_model"],
        "llm_system_prompt": payload.get("llm_system_prompt") or "",
        "created_at": utcnow(),
    }
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO services (
                id, name, feishu_app_id, feishu_app_secret, verification_token,
                encrypt_key, llm_base_url, llm_api_key, llm_model,
                llm_system_prompt, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                service["id"],
                service["name"],
                service["feishu_app_id"],
                service["feishu_app_secret"],
                service["verification_token"],
                service["encrypt_key"],
                service["llm_base_url"],
                service["llm_api_key"],
                service["llm_model"],
                service["llm_system_prompt"],
                service["created_at"],
            ),
        )
    return service


def get_service(service_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        cursor = connection.execute("SELECT * FROM services WHERE id = ?", (service_id,))
        return cursor.fetchone()


def create_source(
    *,
    service_id: str,
    source_type: str,
    title: str,
    content: str,
    external_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = {
        "id": str(uuid.uuid4()),
        "service_id": service_id,
        "source_type": source_type,
        "title": title,
        "external_id": external_id,
        "content": content,
        "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
        "created_at": utcnow(),
    }
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO knowledge_sources (
                id, service_id, source_type, title, external_id, content,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source["id"],
                source["service_id"],
                source["source_type"],
                source["title"],
                source["external_id"],
                source["content"],
                source["metadata_json"],
                source["created_at"],
            ),
        )
    return source


def add_chunks(
    *,
    service_id: str,
    source_id: str,
    chunks: list[str],
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    created_chunks: list[dict[str, Any]] = []
    with get_connection() as connection:
        for index, chunk in enumerate(chunks):
            created = {
                "id": str(uuid.uuid4()),
                "source_id": source_id,
                "service_id": service_id,
                "chunk_index": index,
                "content": chunk,
                "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
                "created_at": utcnow(),
            }
            connection.execute(
                """
                INSERT INTO knowledge_chunks (
                    id, source_id, service_id, chunk_index, content,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created["id"],
                    created["source_id"],
                    created["service_id"],
                    created["chunk_index"],
                    created["content"],
                    created["metadata_json"],
                    created["created_at"],
                ),
            )
            try:
                connection.execute(
                    "INSERT INTO knowledge_chunks_fts (chunk_id, service_id, content) VALUES (?, ?, ?)",
                    (created["id"], service_id, chunk),
                )
            except sqlite3.OperationalError:
                pass
            created_chunks.append(created)
    return created_chunks


def list_sources(service_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            SELECT id, service_id, source_type, title, external_id, metadata_json, created_at
            FROM knowledge_sources
            WHERE service_id = ?
            ORDER BY created_at DESC
            """,
            (service_id,),
        )
        return list(cursor.fetchall())


def search_chunks(service_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
    with get_connection() as connection:
        try:
            cursor = connection.execute(
                """
                SELECT kc.id, kc.source_id, kc.content, kc.chunk_index, ks.title, ks.source_type
                FROM knowledge_chunks_fts fts
                JOIN knowledge_chunks kc ON kc.id = fts.chunk_id
                JOIN knowledge_sources ks ON ks.id = kc.source_id
                WHERE fts.service_id = ? AND knowledge_chunks_fts MATCH ?
                LIMIT ?
                """,
                (service_id, query, limit),
            )
            rows = list(cursor.fetchall())
            if rows:
                return rows
        except sqlite3.OperationalError:
            pass

        cursor = connection.execute(
            """
            SELECT kc.id, kc.source_id, kc.content, kc.chunk_index, ks.title, ks.source_type
            FROM knowledge_chunks kc
            JOIN knowledge_sources ks ON ks.id = kc.source_id
            WHERE kc.service_id = ? AND kc.content LIKE ?
            LIMIT ?
            """,
            (service_id, f"%{query}%", limit),
        )
        return list(cursor.fetchall())


def log_conversation(
    *,
    service_id: str,
    direction: str,
    content: str,
    chat_id: str | None = None,
    message_id: str | None = None,
    user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = {
        "id": str(uuid.uuid4()),
        "service_id": service_id,
        "direction": direction,
        "chat_id": chat_id,
        "message_id": message_id,
        "user_id": user_id,
        "content": content,
        "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
        "created_at": utcnow(),
    }
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO conversation_logs (
                id, service_id, direction, chat_id, message_id, user_id,
                content, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["id"],
                entry["service_id"],
                entry["direction"],
                entry["chat_id"],
                entry["message_id"],
                entry["user_id"],
                entry["content"],
                entry["metadata_json"],
                entry["created_at"],
            ),
        )
    return entry


def add_asset(
    *,
    service_id: str,
    source_id: str | None,
    asset_type: str,
    file_name: str,
    local_path: Path,
    mime_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    asset = {
        "id": str(uuid.uuid4()),
        "source_id": source_id,
        "service_id": service_id,
        "asset_type": asset_type,
        "file_name": file_name,
        "mime_type": mime_type,
        "local_path": str(local_path),
        "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
        "created_at": utcnow(),
    }
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO assets (
                id, source_id, service_id, asset_type, file_name, mime_type,
                local_path, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset["id"],
                asset["source_id"],
                asset["service_id"],
                asset["asset_type"],
                asset["file_name"],
                asset["mime_type"],
                asset["local_path"],
                asset["metadata_json"],
                asset["created_at"],
            ),
        )
    return asset


def create_agent_session(
    *,
    service_id: str,
    goal: str,
    parent_session_id: str | None = None,
    agent_type: str = "primary",
    status: str,
    step_count: int,
    max_steps: int,
    context: dict[str, Any] | None = None,
    constraints: dict[str, Any] | None = None,
    policy_config: dict[str, Any] | None = None,
    current_plan: list[str] | None = None,
    working_memory: dict[str, Any] | None = None,
    final_answer: str | None = None,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    now = utcnow()
    session = {
        "id": str(uuid.uuid4()),
        "service_id": service_id,
        "goal": goal,
        "parent_session_id": parent_session_id,
        "agent_type": agent_type,
        "status": status,
        "step_count": step_count,
        "max_steps": max_steps,
        "context_json": json.dumps(context or {}, ensure_ascii=False),
        "constraints_json": json.dumps(constraints or {}, ensure_ascii=False),
        "policy_config_json": json.dumps(policy_config or {}, ensure_ascii=False),
        "current_plan_json": json.dumps(current_plan or [], ensure_ascii=False),
        "working_memory_json": json.dumps(working_memory or {}, ensure_ascii=False),
        "final_answer": final_answer,
        "failure_reason": failure_reason,
        "created_at": now,
        "updated_at": now,
    }
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO agent_sessions (
                id, service_id, goal, parent_session_id, agent_type, status, step_count, max_steps,
                context_json, constraints_json, policy_config_json,
                current_plan_json, working_memory_json, final_answer,
                failure_reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session["id"],
                session["service_id"],
                session["goal"],
                session["parent_session_id"],
                session["agent_type"],
                session["status"],
                session["step_count"],
                session["max_steps"],
                session["context_json"],
                session["constraints_json"],
                session["policy_config_json"],
                session["current_plan_json"],
                session["working_memory_json"],
                session["final_answer"],
                session["failure_reason"],
                session["created_at"],
                session["updated_at"],
            ),
        )
    return get_agent_session(session["id"]) or session


def get_agent_session(session_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        cursor = connection.execute("SELECT * FROM agent_sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
    return _deserialize_agent_session(row) if row else None


def update_agent_session(
    session_id: str,
    *,
    parent_session_id: str | None,
    agent_type: str,
    status: str,
    step_count: int,
    max_steps: int,
    context: dict[str, Any],
    constraints: dict[str, Any],
    policy_config: dict[str, Any],
    current_plan: list[str],
    working_memory: dict[str, Any],
    final_answer: str | None,
    failure_reason: str | None,
) -> dict[str, Any]:
    now = utcnow()
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE agent_sessions
            SET parent_session_id = ?, agent_type = ?, status = ?, step_count = ?, max_steps = ?, context_json = ?,
                constraints_json = ?, policy_config_json = ?, current_plan_json = ?,
                working_memory_json = ?, final_answer = ?, failure_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                parent_session_id,
                agent_type,
                status,
                step_count,
                max_steps,
                json.dumps(context, ensure_ascii=False),
                json.dumps(constraints, ensure_ascii=False),
                json.dumps(policy_config, ensure_ascii=False),
                json.dumps(current_plan, ensure_ascii=False),
                json.dumps(working_memory, ensure_ascii=False),
                final_answer,
                failure_reason,
                now,
                session_id,
            ),
        )
    session = get_agent_session(session_id)
    if not session:
        raise ValueError(f"Agent session not found: {session_id}")
    return session


def list_agent_sessions(service_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            SELECT * FROM agent_sessions
            WHERE service_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (service_id, limit),
        )
        rows = cursor.fetchall()
    return [_deserialize_agent_session(row) for row in rows]


def list_child_agent_sessions(parent_session_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            SELECT * FROM agent_sessions
            WHERE parent_session_id = ?
            ORDER BY created_at ASC
            """,
            (parent_session_id,),
        )
        rows = cursor.fetchall()
    return [_deserialize_agent_session(row) for row in rows]


def create_agent_step_log(
    *,
    session_id: str,
    step_index: int,
    plan_decision: dict[str, Any],
    observation: dict[str, Any] | None = None,
    verification: dict[str, Any] | None = None,
    processor_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    step_log = {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "step_index": step_index,
        "plan_decision_json": json.dumps(plan_decision, ensure_ascii=False),
        "observation_json": json.dumps(observation, ensure_ascii=False) if observation is not None else None,
        "verification_json": json.dumps(verification, ensure_ascii=False) if verification is not None else None,
        "processor_state_json": json.dumps(processor_state, ensure_ascii=False) if processor_state is not None else None,
        "created_at": utcnow(),
    }
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO agent_step_logs (
                id, session_id, step_index, plan_decision_json,
                observation_json, verification_json, processor_state_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                step_log["id"],
                step_log["session_id"],
                step_log["step_index"],
                step_log["plan_decision_json"],
                step_log["observation_json"],
                step_log["verification_json"],
                step_log["processor_state_json"],
                step_log["created_at"],
            ),
        )
    return _deserialize_agent_step_log(step_log)


def list_agent_step_logs(session_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            SELECT * FROM agent_step_logs
            WHERE session_id = ?
            ORDER BY step_index ASC, created_at ASC
            """,
            (session_id,),
        )
        rows = cursor.fetchall()
    return [_deserialize_agent_step_log(row) for row in rows]


def _deserialize_agent_session(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["context"] = _loads_json(payload.pop("context_json"), {})
    payload["constraints"] = _loads_json(payload.pop("constraints_json"), {})
    payload["policy_config"] = _loads_json(payload.pop("policy_config_json"), {})
    payload["current_plan"] = _loads_json(payload.pop("current_plan_json"), [])
    payload["working_memory"] = _loads_json(payload.pop("working_memory_json"), {})
    return payload


def _deserialize_agent_step_log(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["plan_decision"] = _loads_json(payload.pop("plan_decision_json"), {})
    payload["observation"] = _loads_json(payload.pop("observation_json"), None)
    payload["verification"] = _loads_json(payload.pop("verification_json"), None)
    payload["processor_state"] = _loads_json(payload.pop("processor_state_json", None), None)
    return payload
# AI GC END

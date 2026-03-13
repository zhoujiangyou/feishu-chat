# AI GC START
from __future__ import annotations

from pathlib import Path

import pytest

import app.mcp_server as mcp_module
from app.services.mcp_scheduler import ScheduledTaskManager, ScheduledTaskStore


class FakeScheduledApiClient:
    async def send_feishu_message(
        self,
        *,
        service_id: str,
        receive_id: str,
        text: str,
        receive_id_type: str = "chat_id",
    ) -> dict[str, object]:
        return {
            "status": "ok",
            "service_id": service_id,
            "receive_id": receive_id,
            "text": text,
            "receive_id_type": receive_id_type,
        }


def _build_manager(tmp_path: Path) -> ScheduledTaskManager:
    store = ScheduledTaskStore(db_path=tmp_path / "mcp-tasks.db")
    return ScheduledTaskManager(
        api_client_factory=lambda: FakeScheduledApiClient(),
        store=store,
        poll_seconds=0.01,
    )


@pytest.mark.anyio
async def test_scheduled_task_executes_and_updates_status(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)
    task = manager.create_interval_task(
        name="hourly-reminder",
        service_id="svc_123",
        action_type="send_feishu_message",
        payload={
            "receive_id": "oc_group_123",
            "receive_id_type": "chat_id",
            "text": "hello scheduled",
        },
        interval_seconds=60,
        run_immediately=True,
    )

    executed = await manager.run_task_now(task["id"])
    assert executed["last_status"] == "success"
    assert executed["last_result"]["receive_id"] == "oc_group_123"
    assert executed["last_result"]["text"] == "hello scheduled"


def test_pause_and_resume_scheduled_task(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)
    task = manager.create_interval_task(
        name="paused-reminder",
        service_id="svc_123",
        action_type="send_feishu_message",
        payload={
            "receive_id": "oc_group_123",
            "text": "hello scheduled",
        },
        interval_seconds=300,
    )

    paused = manager.pause_task(task["id"])
    assert paused["enabled"] is False

    resumed = manager.resume_task(task["id"])
    assert resumed["enabled"] is True


@pytest.mark.anyio
async def test_mcp_scheduler_tools_use_manager(tmp_path: Path, monkeypatch) -> None:
    manager = _build_manager(tmp_path)
    monkeypatch.setattr(mcp_module, "scheduler_manager", manager)

    created = mcp_module.create_interval_scheduled_task(
        name="tool-reminder",
        service_id="svc_123",
        action_type="send_feishu_message",
        payload={
            "receive_id": "oc_group_123",
            "text": "hello from tool",
        },
        interval_seconds=120,
        run_immediately=False,
    )
    task_id = created["task"]["id"]

    listed = mcp_module.list_scheduled_tasks(service_id="svc_123")
    assert listed["items"]
    assert listed["items"][0]["id"] == task_id

    run_result = await mcp_module.run_scheduled_task_now(task_id)
    assert run_result["task"]["last_status"] == "success"
# AI GC END

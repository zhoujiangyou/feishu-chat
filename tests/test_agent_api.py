# AI GC START
from __future__ import annotations

import app.main as main_module
from app import db
from app.agent.types import AgentRunResult, AgentSession, AgentStepLog
from fastapi.testclient import TestClient


def _create_service(client: TestClient) -> str:
    response = client.post(
        "/api/v1/services",
        json={
            "name": "agent-api-demo",
            "feishu_app_id": "cli_demo",
            "feishu_app_secret": "secret",
            "verification_token": "verify",
            "encrypt_key": "encrypt",
            "llm_base_url": "https://example.com/v1",
            "llm_api_key": "sk-demo",
            "llm_model": "test-model",
            "llm_system_prompt": "你是测试助手。",
        },
    )
    assert response.status_code == 200
    return response.json()["service_id"]


class FakeRuntime:
    def __init__(self, service_id: str) -> None:
        self.session = AgentSession(
            id="sess_api_123",
            service_id=service_id,
            goal="总结并发送",
            status="completed",
            step_count=2,
            max_steps=6,
            context={"chat_id": "oc_group_123"},
            constraints={"max_steps": 6},
            policy_config={"allow_send_feishu_message": True},
            current_plan=["总结群聊", "发送结果"],
            working_memory={"latest_summary": "done", "message_sent": True},
            final_answer="done",
            failure_reason=None,
            created_at=db.utcnow(),
            updated_at=db.utcnow(),
        )
        self.logs = [
            AgentStepLog(
                session_id=self.session.id,
                step_index=0,
                plan_decision={"action_type": "tool_call"},
                observation={"tool_name": "summarize_feishu_chat", "summary": "summary ready"},
                verification={"goal_completed": False},
                created_at=db.utcnow(),
            ),
            AgentStepLog(
                session_id=self.session.id,
                step_index=1,
                plan_decision={"action_type": "tool_call"},
                observation={"tool_name": "send_feishu_message", "summary": "message sent"},
                verification={"goal_completed": True},
                created_at=db.utcnow(),
            ),
        ]

    async def run(self, *, service_id: str, goal: str, context: dict, constraints: dict, policy_config: dict):  # type: ignore[no-untyped-def]
        self.session.goal = goal
        self.session.context = context
        self.session.constraints = constraints
        self.session.policy_config = policy_config
        return AgentRunResult(session=self.session, logs=self.logs)

    async def resume(self, session_id: str) -> AgentRunResult:
        assert session_id == self.session.id
        return AgentRunResult(session=self.session, logs=self.logs)

    def get_session(self, session_id: str) -> AgentSession:
        assert session_id == self.session.id
        return self.session

    def get_logs(self, session_id: str) -> list[AgentStepLog]:
        assert session_id == self.session.id
        return self.logs

    def cancel(self, session_id: str) -> AgentSession:
        assert session_id == self.session.id
        self.session.status = "cancelled"
        return self.session


def test_agent_api_routes_return_expected_payloads(tmp_path, monkeypatch) -> None:
    db.DB_PATH = tmp_path / "agent-api.db"

    with TestClient(main_module.app) as client:
        service_id = _create_service(client)
        fake_runtime = FakeRuntime(service_id=service_id)
        monkeypatch.setattr(main_module, "get_agent_runtime", lambda: fake_runtime)

        run_response = client.post(
            f"/api/v1/services/{service_id}/agent/run",
            json={
                "goal": "总结当前群并发送结果",
                "context": {"chat_id": "oc_group_123"},
                "constraints": {"max_steps": 6},
                "policy_config": {"allow_send_feishu_message": True},
            },
        )
        assert run_response.status_code == 200
        assert run_response.json()["session"]["session_id"] == "sess_api_123"

        session_response = client.get(f"/api/v1/services/{service_id}/agent/sessions/sess_api_123")
        assert session_response.status_code == 200
        assert session_response.json()["status"] == "completed"

        logs_response = client.get(f"/api/v1/services/{service_id}/agent/sessions/sess_api_123/logs")
        assert logs_response.status_code == 200
        assert len(logs_response.json()["items"]) == 2

        resume_response = client.post(f"/api/v1/services/{service_id}/agent/sessions/sess_api_123/resume")
        assert resume_response.status_code == 200
        assert resume_response.json()["session"]["final_answer"] == "done"

        cancel_response = client.post(f"/api/v1/services/{service_id}/agent/sessions/sess_api_123/cancel")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] == "cancelled"
# AI GC END

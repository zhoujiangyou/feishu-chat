# AI GC START
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AgentStatus = Literal[
    "created",
    "running",
    "waiting_input",
    "completed",
    "failed",
    "cancelled",
    "paused",
]

ActionType = Literal["tool_call", "finish", "ask_user", "wait", "fail"]


class ToolSpec(BaseModel):
    name: str
    description: str
    category: str
    risk_level: Literal["read_only", "write", "side_effect", "dangerous"]
    input_schema: dict[str, Any] = Field(default_factory=dict)
    idempotent: bool = False
    side_effect: bool = False


class ToolCall(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""


class PlanDecision(BaseModel):
    action_type: ActionType
    reasoning_summary: str
    updated_plan: list[str] = Field(default_factory=list)
    next_tool_call: ToolCall | None = None
    final_answer: str | None = None
    ask_user_message: str | None = None
    done: bool = False


class Observation(BaseModel):
    step_index: int
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    success: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    summary: str
    created_at: str


class VerificationResult(BaseModel):
    step_success: bool
    goal_completed: bool
    should_retry: bool = False
    should_replan: bool = False
    should_abort: bool = False
    should_wait_for_input: bool = False
    verifier_summary: str
    final_answer: str | None = None
    ask_user_message: str | None = None


class AgentSession(BaseModel):
    id: str
    service_id: str
    goal: str
    status: AgentStatus
    step_count: int
    max_steps: int
    context: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    policy_config: dict[str, Any] = Field(default_factory=dict)
    current_plan: list[str] = Field(default_factory=list)
    working_memory: dict[str, Any] = Field(default_factory=dict)
    final_answer: str | None = None
    failure_reason: str | None = None
    created_at: str
    updated_at: str


class AgentStepLog(BaseModel):
    session_id: str
    step_index: int
    plan_decision: dict[str, Any]
    observation: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    created_at: str


class WorkingContext(BaseModel):
    knowledge_results: list[dict[str, Any]] = Field(default_factory=list)
    recent_observations: list[dict[str, Any]] = Field(default_factory=list)
    working_memory: dict[str, Any] = Field(default_factory=dict)


class AgentRunResult(BaseModel):
    session: AgentSession
    logs: list[AgentStepLog] = Field(default_factory=list)
# AI GC END

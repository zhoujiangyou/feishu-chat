# AI GC START
from __future__ import annotations

import json

from app.agent.types import AgentSession, ToolSpec, WorkingContext


PLANNER_OUTPUT_EXAMPLE = {
    "action_type": "tool_call",
    "reasoning_summary": "当前知识不足，需要先拉取群聊后再总结。",
    "updated_plan": ["获取上下文", "生成答案", "如有需要再执行副作用动作"],
    "next_tool_call": {
        "tool_name": "summarize_feishu_chat",
        "arguments": {"chat_id": "oc_xxx", "limit": 100},
        "rationale": "先总结当前群聊内容。",
    },
    "final_answer": None,
    "ask_user_message": None,
    "done": False,
}

VERIFIER_OUTPUT_EXAMPLE = {
    "step_success": True,
    "goal_completed": False,
    "should_retry": False,
    "should_replan": True,
    "should_abort": False,
    "verifier_summary": "当前步骤成功，但距离目标仍差后续执行动作。",
    "final_answer": None,
}


def _tool_descriptions(available_tools: list[ToolSpec]) -> list[dict[str, object]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "category": tool.category,
            "risk_level": tool.risk_level,
            "input_schema": tool.input_schema,
        }
        for tool in available_tools
    ]


def build_planner_system_prompt() -> str:
    return (
        "你是当前服务内部的闭环自主 Agent Planner。"
        "你的任务不是直接给最终答案，而是为当前这一轮输出一个严格 JSON 的下一步动作。"
        "每次只能选择一个动作：tool_call、finish、ask_user、wait 或 fail。"
        "优先使用已有知识；知识不足时再调用工具；避免重复调用明显无效的动作。"
        "输出必须是合法 JSON，字段结构必须和示例保持一致。"
    )


def build_planner_user_prompt(
    *,
    session: AgentSession,
    working_context: WorkingContext,
    available_tools: list[ToolSpec],
) -> str:
    payload = {
        "goal": session.goal,
        "context": session.context,
        "constraints": session.constraints,
        "policy_config": session.policy_config,
        "current_plan": session.current_plan,
        "working_memory": session.working_memory,
        "knowledge_results": working_context.knowledge_results,
        "recent_observations": working_context.recent_observations,
        "available_tools": _tool_descriptions(available_tools),
        "output_example": PLANNER_OUTPUT_EXAMPLE,
    }
    return (
        "请根据下面的上下文决定当前这一轮下一步动作，并严格输出 JSON。\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def build_verifier_system_prompt() -> str:
    return (
        "你是当前服务内部的闭环自主 Agent Verifier。"
        "你的任务是根据用户目标、当前 observation 和 working memory，判断这一步是否真正推进了目标。"
        "请严格输出 JSON。"
    )


def build_verifier_user_prompt(
    *,
    session: AgentSession,
    observation: dict[str, object] | None,
) -> str:
    payload = {
        "goal": session.goal,
        "context": session.context,
        "working_memory": session.working_memory,
        "observation": observation,
        "output_example": VERIFIER_OUTPUT_EXAMPLE,
    }
    return (
        "请校验下面这一步的结果，并严格输出 JSON。\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
# AI GC END

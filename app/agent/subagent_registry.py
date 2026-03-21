# AI GC START
from __future__ import annotations

from app.agent.types import SubagentSpec


class SubagentRegistry:
    def __init__(self) -> None:
        self._items = {
            "explore": SubagentSpec(
                name="explore",
                description="A read-only subagent for fast research, knowledge lookups, and context gathering.",
                readonly=True,
                preferred_tool_names=[
                    "search_knowledge",
                    "list_knowledge_sources",
                    "ask_llm_question",
                ],
            ),
            "general": SubagentSpec(
                name="general",
                description="A general-purpose subagent for multi-step tasks with full tool access.",
                readonly=False,
                preferred_tool_names=[],
            ),
        }

    def get(self, name: str) -> SubagentSpec | None:
        return self._items.get(name)

    def list(self) -> list[SubagentSpec]:
        return list(self._items.values())
# AI GC END

# AI GC START
from __future__ import annotations

from app.agent.types import AgentSession, Observation, VerificationResult


class AgentVerifier:
    async def verify_step(
        self,
        session: AgentSession,
        observation: Observation | None,
    ) -> VerificationResult:
        if observation is None:
            return VerificationResult(
                step_success=False,
                goal_completed=False,
                should_abort=True,
                verifier_summary="本轮没有产生 observation，无法继续执行。",
            )

        if not observation.success:
            return VerificationResult(
                step_success=False,
                goal_completed=False,
                should_retry=False,
                should_replan=True,
                verifier_summary=f"工具执行失败，需要重新规划：{observation.error}",
            )

        if observation.tool_name == "send_feishu_message":
            final_answer = str(session.working_memory.get("latest_summary") or "消息已发送。")
            return VerificationResult(
                step_success=True,
                goal_completed=True,
                verifier_summary="发送动作已成功完成，目标可判定为完成。",
                final_answer=final_answer,
            )

        if observation.tool_name == "ask_llm_question":
            answer = str((observation.result or {}).get("answer") or "").strip()
            if answer:
                return VerificationResult(
                    step_success=True,
                    goal_completed=True,
                    verifier_summary="问答结果已经足够直接返回给用户。",
                    final_answer=answer,
                )

        if observation.tool_name == "analyze_image_with_llm":
            answer = str((observation.result or {}).get("answer") or "").strip()
            if answer:
                return VerificationResult(
                    step_success=True,
                    goal_completed=True,
                    verifier_summary="图片分析结果已经可直接作为最终答案。",
                    final_answer=answer,
                )

        if observation.tool_name == "summarize_feishu_chat":
            summary = str((observation.result or {}).get("summary") or "").strip()
            if summary and not self._goal_mentions_send(session.goal):
                return VerificationResult(
                    step_success=True,
                    goal_completed=True,
                    verifier_summary="摘要已经生成且当前目标不要求后续副作用动作。",
                    final_answer=summary,
                )
            return VerificationResult(
                step_success=True,
                goal_completed=False,
                should_replan=True,
                verifier_summary="摘要已生成，但还需要继续判断是否执行发送等后续动作。",
            )

        if observation.tool_name.startswith("import_feishu_"):
            if self._goal_is_ingest_only(session.goal):
                source_title = str(((observation.result or {}).get("source") or {}).get("title") or "").strip()
                final_answer = source_title or "知识已导入。"
                return VerificationResult(
                    step_success=True,
                    goal_completed=True,
                    verifier_summary="当前目标仅要求导入知识，步骤已完成。",
                    final_answer=final_answer,
                )
            return VerificationResult(
                step_success=True,
                goal_completed=False,
                should_replan=True,
                verifier_summary="知识导入已完成，但仍需继续执行后续分析或回答步骤。",
            )

        return VerificationResult(
            step_success=True,
            goal_completed=False,
            should_replan=True,
            verifier_summary="当前步骤成功，但仍需继续规划后续动作。",
        )

    def _goal_mentions_send(self, goal: str) -> bool:
        return any(keyword in goal for keyword in ("发送", "发到", "回发", "send"))

    def _goal_is_ingest_only(self, goal: str) -> bool:
        has_ingest = any(keyword in goal for keyword in ("抓取", "导入", "同步"))
        has_follow_up = any(keyword in goal for keyword in ("总结", "分析", "回答", "发送", "发到"))
        return has_ingest and not has_follow_up
# AI GC END

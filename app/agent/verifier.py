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
            missing_input_prompt = self._build_missing_input_prompt(observation.error or "")
            if missing_input_prompt:
                return VerificationResult(
                    step_success=False,
                    goal_completed=False,
                    should_wait_for_input=True,
                    verifier_summary=f"当前步骤缺少必要上下文：{observation.error}",
                    ask_user_message=missing_input_prompt,
                )
            if self._is_transient_error(observation.error or ""):
                return VerificationResult(
                    step_success=False,
                    goal_completed=False,
                    should_retry=True,
                    verifier_summary=f"检测到疑似瞬时错误，允许对当前动作进行有限重试：{observation.error}",
                )
            return VerificationResult(
                step_success=False,
                goal_completed=False,
                should_retry=False,
                should_replan=True,
                verifier_summary=f"工具执行失败，需要重新规划：{observation.error}",
            )

        if observation.tool_name == "search_knowledge":
            results = ((observation.result or {}).get("results") or [])
            if results:
                return VerificationResult(
                    step_success=True,
                    goal_completed=False,
                    should_replan=True,
                    verifier_summary=f"知识检索命中 {len(results)} 条结果，下一步可组织回答或继续推理。",
                )
            return VerificationResult(
                step_success=True,
                goal_completed=False,
                should_replan=True,
                verifier_summary="知识检索未命中，可转为通用问答或继续补充上下文。",
            )

        if observation.tool_name == "run_subagent":
            summary = str((observation.result or {}).get("summary") or "").strip()
            if summary:
                return VerificationResult(
                    step_success=True,
                    goal_completed=False,
                    should_replan=True,
                    verifier_summary="子 agent 已返回上下文摘要，主会话应基于摘要继续推进。",
                )
            return VerificationResult(
                step_success=False,
                goal_completed=False,
                should_replan=True,
                verifier_summary="子 agent 没有返回有效摘要，需要重新规划。",
            )

        if observation.tool_name == "send_feishu_message":
            if not observation.result or not (observation.result.get("result") or observation.result.get("status") or observation.result.get("receive_id")):
                return VerificationResult(
                    step_success=False,
                    goal_completed=False,
                    should_replan=True,
                    verifier_summary="发送动作缺少有效返回结果，需要重新规划。",
                )
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
                if self._goal_mentions_send(session.goal):
                    return VerificationResult(
                        step_success=True,
                        goal_completed=False,
                        should_replan=True,
                        verifier_summary="问答结果已生成，但目标还要求执行发送动作。",
                        final_answer=answer,
                    )
                return VerificationResult(
                    step_success=True,
                    goal_completed=True,
                    verifier_summary="问答结果已经足够直接返回给用户。",
                    final_answer=answer,
                )
            return VerificationResult(
                step_success=False,
                goal_completed=False,
                should_replan=True,
                verifier_summary="问答动作没有返回有效 answer，需要重新规划。",
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
            return VerificationResult(
                step_success=False,
                goal_completed=False,
                should_replan=True,
                verifier_summary="图像分析没有返回有效 answer，需要重新规划。",
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
            if summary and self._goal_mentions_send(session.goal):
                return VerificationResult(
                    step_success=True,
                    goal_completed=False,
                    should_replan=True,
                    verifier_summary="摘要已生成，但还需要继续判断是否执行发送等后续动作。",
                )
            return VerificationResult(
                step_success=False,
                goal_completed=False,
                should_replan=True,
                verifier_summary="群聊总结没有返回有效 summary，需要重新规划。",
            )

        if observation.tool_name.startswith("import_feishu_"):
            source = (observation.result or {}).get("source")
            if not source:
                return VerificationResult(
                    step_success=False,
                    goal_completed=False,
                    should_replan=True,
                    verifier_summary="知识导入动作没有返回有效 source，需要重新规划。",
                )
            if self._goal_is_ingest_only(session.goal):
                source_title = str((source or {}).get("title") or "").strip()
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

    def _is_transient_error(self, error: str) -> bool:
        lowered = error.lower()
        transient_keywords = ("timeout", "temporarily", "temporary", "connection", "429", "502", "503", "rate limit")
        return any(keyword in lowered for keyword in transient_keywords)

    def _build_missing_input_prompt(self, error: str) -> str | None:
        lowered = error.lower()
        if any(keyword in lowered for keyword in ("chat_id", "当前群", "current chat")):
            return "当前缺少可处理的 chat_id，请告诉我要处理的群聊，或直接在目标群里发起请求。"
        if any(keyword in lowered for keyword in ("receive_id", "send target", "发送目标")):
            return "当前缺少消息发送目标，请补充 chat_id 或其他 receive_id。"
        if any(keyword in lowered for keyword in ("document", "文档", "token")):
            return "当前缺少文档链接或 token，请补充后再试。"
        if any(keyword in lowered for keyword in ("image", "image_key", "message_id", "图片")):
            return "当前缺少图片上下文，请补充 image_url、image_key、message_id 或直接发送图片。"
        if any(keyword in lowered for keyword in ("missing required", "required field", "unable to resolve", "not found")):
            return "当前缺少完成任务所需的必要上下文，请补充更多信息后再试。"
        return None
# AI GC END

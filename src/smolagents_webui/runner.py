from __future__ import annotations

import threading
from typing import Any, TYPE_CHECKING

from smolagents_webui.config import AgentRunConfig
from smolagents_webui.model_factory import ModelFactory
from smolagents_webui.serialization import to_json_compatible
from smolagents_webui.store import SessionStore

if TYPE_CHECKING:
    from smolagents import CodeAgent


class RunCancelled(Exception):
    """Internal signal for cooperative run cancellation."""


class AgentRunner:
    """Run smolagents tasks in background threads and publish UI events."""

    def __init__(self, store: SessionStore, model_factory: ModelFactory | None = None):
        self.store = store
        self.model_factory = model_factory or ModelFactory()

    def start_run(self, session_id: str, prompt: str, config: AgentRunConfig) -> None:
        run_id = self.store.try_start_run(session_id, prompt, to_json_compatible(config))
        self.store.append_event(
            session_id,
            "run_started",
            {
                "run_id": run_id,
                "prompt": prompt,
                "config": to_json_compatible(config),
            },
        )

        worker = threading.Thread(
            target=self._run_worker,
            kwargs={"session_id": session_id, "prompt": prompt, "config": config, "run_id": run_id},
            daemon=True,
        )
        worker.start()

    def _run_worker(self, session_id: str, prompt: str, config: AgentRunConfig, run_id: str) -> None:
        final_answer: Any = None
        try:
            from smolagents import CodeAgent
            from smolagents.agents import ToolOutput
            from smolagents.agents import PlanningStep
            from smolagents.memory import ActionStep, FinalAnswerStep, ToolCall
            from smolagents.models import ChatMessageStreamDelta
            from smolagents.monitoring import LogLevel

            step_callback = self._build_step_callback(
                session_id=session_id,
                run_id=run_id,
                action_step_type=ActionStep,
                planning_step_type=PlanningStep,
                final_answer_step_type=FinalAnswerStep,
            )

            self._raise_if_cancelled(session_id, run_id)
            model = self.model_factory.create(config)
            agent = CodeAgent(
                tools=[],
                model=model,
                additional_authorized_imports=config.additional_imports,
                planning_interval=config.planning_interval,
                step_callbacks={
                    ActionStep: step_callback,
                    PlanningStep: step_callback,
                    FinalAnswerStep: step_callback,
                },
                stream_outputs=config.stream_model_output,
                verbosity_level=LogLevel.INFO,
            )

            for event in agent.run(prompt, stream=True, reset=False, max_steps=config.max_steps):
                self._raise_if_cancelled(session_id, run_id)
                if isinstance(event, ChatMessageStreamDelta):
                    if event.content:
                        self.store.append_event(
                            session_id,
                            "assistant_delta",
                            {
                                "text": event.content,
                            },
                        )
                elif isinstance(event, ToolCall):
                    self.store.append_event(
                        session_id,
                        "tool_call",
                        {
                            "id": event.id,
                            "name": event.name,
                            "arguments": to_json_compatible(event.arguments),
                        },
                    )
                elif isinstance(event, ToolOutput):
                    self.store.append_event(
                        session_id,
                        "tool_output",
                        {
                            "id": event.id,
                            "name": event.tool_call.name,
                            "observation": event.observation,
                            "output": self._preview(event.output),
                            "is_final_answer": event.is_final_answer,
                        },
                        )
                elif isinstance(event, FinalAnswerStep):
                    final_answer = event.output
                self._raise_if_cancelled(session_id, run_id)

            self.store.append_event(
                session_id,
                "run_completed",
                {
                    "run_id": run_id,
                    "final_answer": to_json_compatible(final_answer),
                },
            )
            self.store.mark_run_finished(session_id)
        except RunCancelled:
            self.store.append_event(
                session_id,
                "run_cancelled",
                {
                    "run_id": run_id,
                    "message": "Run cancelled by user.",
                },
            )
            self.store.mark_run_finished(session_id)
        except Exception as exc:
            error_message = f"{type(exc).__name__}: {exc}"
            self.store.append_event(session_id, "run_failed", {"run_id": run_id, "error": error_message})
            self.store.mark_run_finished(session_id, error=error_message)

    def _raise_if_cancelled(self, session_id: str, run_id: str) -> None:
        if self.store.is_cancel_requested(session_id, run_id):
            raise RunCancelled()

    def _build_step_callback(
        self,
        session_id: str,
        run_id: str,
        action_step_type: type,
        planning_step_type: type,
        final_answer_step_type: type,
    ):
        def _callback(step: Any, agent: CodeAgent) -> None:
            self._raise_if_cancelled(session_id, run_id)
            state_snapshot = to_json_compatible(getattr(agent, "state", {}))
            if isinstance(state_snapshot, dict):
                self.store.update_agent_state(session_id, state_snapshot)

            if isinstance(step, action_step_type):
                self.store.append_event(session_id, "action_step", self._action_step_payload(step, state_snapshot))
            elif isinstance(step, planning_step_type):
                self.store.append_event(session_id, "planning_step", self._planning_step_payload(step, state_snapshot))
            elif isinstance(step, final_answer_step_type):
                self.store.append_event(
                    session_id,
                    "final_answer_step",
                    {
                        "output": to_json_compatible(step.output),
                        "state": state_snapshot,
                    },
                )
            self._raise_if_cancelled(session_id, run_id)

        return _callback

    def _action_step_payload(self, step: Any, state_snapshot: Any) -> dict[str, Any]:
        tool_calls: list[dict[str, Any]] = []
        for tool_call in step.tool_calls or []:
            tool_calls.append(
                {
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": to_json_compatible(tool_call.arguments),
                }
            )

        return {
            "step_number": step.step_number,
            "model_output": step.model_output,
            "code_action": step.code_action,
            "tool_calls": tool_calls,
            "observations": step.observations,
            "action_output": self._preview(step.action_output),
            "is_final_answer": step.is_final_answer,
            "error": str(step.error) if step.error else None,
            "token_usage": to_json_compatible(step.token_usage),
            "duration_seconds": round(float(step.timing.duration or 0), 3),
            "state": state_snapshot,
        }

    def _planning_step_payload(self, step: Any, state_snapshot: Any) -> dict[str, Any]:
        return {
            "plan": step.plan,
            "model_output": step.model_output_message.content,
            "token_usage": to_json_compatible(step.token_usage),
            "duration_seconds": round(float(step.timing.duration or 0), 3),
            "state": state_snapshot,
        }

    def _preview(self, value: Any, limit: int = 3000) -> str:
        text = str(to_json_compatible(value))
        if len(text) > limit:
            return text[: limit - 3] + "..."
        return text

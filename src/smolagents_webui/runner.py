from __future__ import annotations

import importlib
import inspect
import sys
import threading
from pathlib import Path
from typing import Any, TYPE_CHECKING

from smolagents_webui.config import AgentRunConfig
from smolagents_webui.model_factory import ModelFactory
from smolagents_webui.serialization import to_json_compatible
from smolagents_webui.store import SessionStore

if TYPE_CHECKING:
    from smolagents import CodeAgent


class RunCancelled(Exception):
    """Internal signal for cooperative run cancellation."""


class FactoryLoadError(ValueError):
    """Raised when a user-provided factory cannot be loaded or used."""


class AgentRunner:
    """Run smolagents tasks in background threads and publish UI events."""

    def __init__(
        self,
        store: SessionStore,
        model_factory: ModelFactory | None = None,
        *,
        agent_factory_path: str | None = None,
        tools_factory_path: str | None = None,
    ):
        self.store = store
        self.model_factory = model_factory or ModelFactory()
        self.agent_factory_path = agent_factory_path
        self.tools_factory_path = tools_factory_path
        self._agent_factory = self._load_factory(agent_factory_path, "--agent-factory") if agent_factory_path else None
        self._tools_factory = self._load_factory(tools_factory_path, "--tools-factory") if tools_factory_path else None

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
            if self._agent_factory is not None:
                agent = self._create_agent_from_factory(model=model, config=config)
            else:
                tools = self._create_tools_from_factory()
                agent = CodeAgent(
                    tools=tools,
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

            self._validate_agent(agent)

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

    def _load_factory(self, factory_path: str, option_name: str) -> Any:
        if ":" not in factory_path:
            raise FactoryLoadError(f"{option_name} must use module:function format.")

        module_name, function_name = [part.strip() for part in factory_path.split(":", 1)]
        if not module_name or not function_name:
            raise FactoryLoadError(f"{option_name} must use module:function format.")

        cwd = str(Path.cwd())
        if cwd not in sys.path:
            sys.path.insert(0, cwd)

        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise FactoryLoadError(f"{option_name} could not import module '{module_name}': {exc}") from exc

        try:
            factory = getattr(module, function_name)
        except AttributeError as exc:
            raise FactoryLoadError(f"{option_name} module '{module_name}' has no callable '{function_name}'.") from exc

        if not callable(factory):
            raise FactoryLoadError(f"{option_name} target '{factory_path}' is not callable.")
        return factory

    def _create_agent_from_factory(self, *, model: Any, config: AgentRunConfig) -> Any:
        try:
            return self._call_agent_factory(self._agent_factory, model=model, config=config)
        except FactoryLoadError:
            raise
        except Exception as exc:
            raise FactoryLoadError(f"--agent-factory '{self.agent_factory_path}' failed: {exc}") from exc

    def _call_agent_factory(self, factory: Any, *, model: Any, config: AgentRunConfig) -> Any:
        try:
            signature = inspect.signature(factory)
        except (TypeError, ValueError):
            return factory(model, config)

        parameters = signature.parameters
        if any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in parameters.values()):
            return factory(model, config)

        keyword_args: dict[str, Any] = {}
        if "model" in parameters:
            keyword_args["model"] = model
        if "config" in parameters:
            keyword_args["config"] = config
        elif "run_config" in parameters:
            keyword_args["run_config"] = config
        if keyword_args and all(
            parameter.kind in {inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
            for name, parameter in parameters.items()
            if name in keyword_args
        ):
            return factory(**keyword_args)

        positional_parameters = [
            parameter
            for parameter in parameters.values()
            if parameter.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
        ]
        if len(positional_parameters) >= 2:
            return factory(model, config)
        if len(positional_parameters) == 1:
            return factory(model)
        return factory()

    def _create_tools_from_factory(self) -> list[Any]:
        if self._tools_factory is None:
            return []
        try:
            tools = self._tools_factory()
        except Exception as exc:
            raise FactoryLoadError(f"--tools-factory '{self.tools_factory_path}' failed: {exc}") from exc
        if not isinstance(tools, list):
            raise FactoryLoadError(f"--tools-factory '{self.tools_factory_path}' must return a list of tools.")
        return tools

    def _validate_agent(self, agent: Any) -> None:
        if not callable(getattr(agent, "run", None)):
            raise FactoryLoadError("--agent-factory must return a smolagents agent with a callable run method.")

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

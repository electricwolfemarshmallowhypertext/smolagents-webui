from pathlib import Path
import sys
import time
import types
import uuid

import pytest


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) in sys.path:
    sys.path.remove(str(SRC_ROOT))
sys.path.insert(0, str(SRC_ROOT))

from smolagents_webui.config import AgentRunConfig
from smolagents_webui.runner import AgentRunner, FactoryLoadError
from smolagents_webui.store import SessionStore


class FakeModelFactory:
    def __init__(self):
        self.model = object()
        self.config = None

    def create(self, config):
        self.config = config
        return self.model


def install_fake_smolagents(monkeypatch, *, delay_between_events=0.0):
    captured = {}

    class FakeDelta:
        def __init__(self, content):
            self.content = content

    class FakeCodeAgent:
        def __init__(self, **kwargs):
            captured["code_agent_kwargs"] = kwargs
            self.state = {"tool_count": len(kwargs.get("tools", []))}

        def run(self, prompt, stream, reset, max_steps):
            captured["run_args"] = {
                "prompt": prompt,
                "stream": stream,
                "reset": reset,
                "max_steps": max_steps,
            }
            yield FakeDelta("first")
            if delay_between_events:
                time.sleep(delay_between_events)
            yield FakeDelta("second")

    class FakeLogLevel:
        INFO = "info"

    smolagents_module = types.ModuleType("smolagents")
    smolagents_module.CodeAgent = FakeCodeAgent

    agents_module = types.ModuleType("smolagents.agents")
    agents_module.ToolOutput = type("ToolOutput", (), {})
    agents_module.PlanningStep = type("PlanningStep", (), {})

    memory_module = types.ModuleType("smolagents.memory")
    memory_module.ActionStep = type("ActionStep", (), {})
    memory_module.FinalAnswerStep = type("FinalAnswerStep", (), {})
    memory_module.ToolCall = type("ToolCall", (), {})

    models_module = types.ModuleType("smolagents.models")
    models_module.ChatMessageStreamDelta = FakeDelta

    monitoring_module = types.ModuleType("smolagents.monitoring")
    monitoring_module.LogLevel = FakeLogLevel

    monkeypatch.setitem(sys.modules, "smolagents", smolagents_module)
    monkeypatch.setitem(sys.modules, "smolagents.agents", agents_module)
    monkeypatch.setitem(sys.modules, "smolagents.memory", memory_module)
    monkeypatch.setitem(sys.modules, "smolagents.models", models_module)
    monkeypatch.setitem(sys.modules, "smolagents.monitoring", monitoring_module)
    return captured, FakeDelta


def make_store():
    store = SessionStore(Path.cwd() / f"runner-sessions-{uuid.uuid4().hex}.json")
    store._persist_locked = lambda: None  # type: ignore[method-assign]
    return store


def wait_for_idle(store, session_id):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and store.get_session(session_id)["is_running"]:
        time.sleep(0.02)
    assert store.get_session(session_id)["is_running"] is False


def test_runner_default_path_passes_empty_tools_to_code_agent(monkeypatch):
    captured, _fake_delta = install_fake_smolagents(monkeypatch)
    store = make_store()
    runner = AgentRunner(store=store, model_factory=FakeModelFactory())
    session_id = store.create_session("Default")["id"]

    runner.start_run(session_id, "hello", AgentRunConfig(provider="openai", model_id="gpt-4o-mini"))
    wait_for_idle(store, session_id)

    assert captured["code_agent_kwargs"]["tools"] == []
    assert captured["run_args"] == {
        "prompt": "hello",
        "stream": True,
        "reset": False,
        "max_steps": 12,
    }


def test_runner_passes_tools_factory_result_to_code_agent(monkeypatch):
    captured, _fake_delta = install_fake_smolagents(monkeypatch)
    tool_a = object()
    tool_b = object()
    module = types.ModuleType("custom_tools_factory")

    def get_tools():
        captured["tools_factory_called"] = True
        return [tool_a, tool_b]

    module.get_tools = get_tools
    monkeypatch.setitem(sys.modules, "custom_tools_factory", module)
    store = make_store()
    runner = AgentRunner(
        store=store,
        model_factory=FakeModelFactory(),
        tools_factory_path="custom_tools_factory:get_tools",
    )
    session_id = store.create_session("Tools")["id"]

    runner.start_run(session_id, "use tools", AgentRunConfig(provider="openai", model_id="gpt-4o-mini"))
    wait_for_idle(store, session_id)

    assert captured["tools_factory_called"] is True
    assert captured["code_agent_kwargs"]["tools"] == [tool_a, tool_b]


def test_runner_agent_factory_overrides_default_code_agent(monkeypatch):
    captured, fake_delta = install_fake_smolagents(monkeypatch)
    model_factory = FakeModelFactory()
    module = types.ModuleType("custom_agent_factory")

    class FactoryAgent:
        state = {"custom": True}

        def run(self, prompt, stream, reset, max_steps):
            captured["factory_agent_run_args"] = {
                "prompt": prompt,
                "stream": stream,
                "reset": reset,
                "max_steps": max_steps,
            }
            yield fake_delta("factory")

    def create_agent(model, config):
        captured["agent_factory_model"] = model
        captured["agent_factory_config"] = config
        return FactoryAgent()

    module.create_agent = create_agent
    monkeypatch.setitem(sys.modules, "custom_agent_factory", module)
    store = make_store()
    runner = AgentRunner(
        store=store,
        model_factory=model_factory,
        agent_factory_path="custom_agent_factory:create_agent",
    )
    session_id = store.create_session("Agent")["id"]
    config = AgentRunConfig(provider="openai", model_id="gpt-4o-mini", max_steps=4)

    runner.start_run(session_id, "custom run", config)
    wait_for_idle(store, session_id)

    assert "code_agent_kwargs" not in captured
    assert captured["agent_factory_model"] is model_factory.model
    assert captured["agent_factory_config"] is config
    assert captured["factory_agent_run_args"] == {
        "prompt": "custom run",
        "stream": True,
        "reset": False,
        "max_steps": 4,
    }


def test_runner_bad_factory_path_raises_clear_error():
    store = make_store()

    with pytest.raises(FactoryLoadError, match="module:function"):
        AgentRunner(store=store, model_factory=FakeModelFactory(), agent_factory_path="not-a-factory-path")


def test_runner_records_cancellation_and_marks_session_idle(monkeypatch):
    install_fake_smolagents(monkeypatch, delay_between_events=0.2)
    store = make_store()
    runner = AgentRunner(store=store, model_factory=FakeModelFactory())
    session_id = store.create_session("Cancel")["id"]

    runner.start_run(session_id, "long run", AgentRunConfig(provider="openai", model_id="gpt-4o-mini"))
    run_id = store.get_session(session_id)["active_run_id"]
    store.request_run_cancel(run_id)

    wait_for_idle(store, session_id)

    session = store.get_session(session_id)
    event_types = [event["type"] for event in session["events"]]
    assert session["is_running"] is False
    assert "run_cancelled" in event_types
    assert "run_failed" not in event_types

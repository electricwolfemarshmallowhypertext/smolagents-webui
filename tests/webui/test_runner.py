from pathlib import Path
import sys
import time
import types


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) in sys.path:
    sys.path.remove(str(SRC_ROOT))
sys.path.insert(0, str(SRC_ROOT))

from smolagents_webui.config import AgentRunConfig
from smolagents_webui.runner import AgentRunner
from smolagents_webui.store import SessionStore


class FakeModelFactory:
    def create(self, config):
        return object()


def install_fake_smolagents(monkeypatch):
    class FakeDelta:
        def __init__(self, content):
            self.content = content

    class FakeCodeAgent:
        def __init__(self, **kwargs):
            pass

        def run(self, prompt, stream, reset, max_steps):
            yield FakeDelta("first")
            time.sleep(0.2)
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


def test_runner_records_cancellation_and_marks_session_idle(monkeypatch):
    install_fake_smolagents(monkeypatch)
    store = SessionStore(Path("unused-runner-sessions.json"))
    store._persist_locked = lambda: None  # type: ignore[method-assign]
    runner = AgentRunner(store=store, model_factory=FakeModelFactory())
    session_id = store.create_session("Cancel")["id"]

    runner.start_run(session_id, "long run", AgentRunConfig(provider="openai", model_id="gpt-4o-mini"))
    run_id = store.get_session(session_id)["active_run_id"]
    store.request_run_cancel(run_id)

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and store.get_session(session_id)["is_running"]:
        time.sleep(0.02)

    session = store.get_session(session_id)
    event_types = [event["type"] for event in session["events"]]
    assert session["is_running"] is False
    assert "run_cancelled" in event_types
    assert "run_failed" not in event_types


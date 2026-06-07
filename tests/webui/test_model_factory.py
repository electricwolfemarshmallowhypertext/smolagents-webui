import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import smolagents_webui.model_factory as model_factory_module
from smolagents_webui.config import AgentRunConfig
from smolagents_webui.model_factory import ModelFactory


def test_model_factory_routes_to_inference_client(monkeypatch):
    captured = {}

    def fake_inference(**kwargs):
        captured.update(kwargs)
        return ("inference", kwargs)

    monkeypatch.setattr(
        model_factory_module,
        "_import_models",
        lambda: (fake_inference, lambda **kwargs: ("litellm", kwargs), lambda **kwargs: ("openai", kwargs)),
    )
    factory = ModelFactory()

    config = AgentRunConfig(
        provider="hf_inference",
        model_id="Qwen/Qwen3",
        hf_provider="together",
        api_key="hf_x",
        api_base="https://custom.example",
    )
    model = factory.create(config)

    assert model[0] == "inference"
    assert captured["model_id"] == "Qwen/Qwen3"
    assert captured["provider"] == "together"
    assert captured["token"] == "hf_x"
    assert captured["base_url"] == "https://custom.example"


def test_model_factory_routes_to_litellm(monkeypatch):
    captured = {}

    def fake_litellm(**kwargs):
        captured.update(kwargs)
        return ("litellm", kwargs)

    monkeypatch.setattr(
        model_factory_module,
        "_import_models",
        lambda: (lambda **kwargs: ("inference", kwargs), fake_litellm, lambda **kwargs: ("openai", kwargs)),
    )
    factory = ModelFactory()
    model = factory.create(AgentRunConfig(provider="litellm", model_id="gpt-4o-mini", api_key="k", api_base="b"))

    assert model[0] == "litellm"
    assert captured["model_id"] == "gpt-4o-mini"
    assert captured["api_key"] == "k"
    assert captured["api_base"] == "b"


def test_model_factory_still_receives_api_key_for_model_creation(monkeypatch):
    captured = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return ("openai", kwargs)

    monkeypatch.setattr(
        model_factory_module,
        "_import_models",
        lambda: (lambda **kwargs: ("inference", kwargs), lambda **kwargs: ("litellm", kwargs), fake_openai),
    )
    factory = ModelFactory()

    model = factory.create(AgentRunConfig(provider="openai", model_id="gpt-4o-mini", api_key="live-api-key-value"))

    assert model[0] == "openai"
    assert captured["api_key"] == "live-api-key-value"


def test_model_factory_routes_ollama_to_openai_compat(monkeypatch):
    captured = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return ("openai", kwargs)

    monkeypatch.setattr(
        model_factory_module,
        "_import_models",
        lambda: (lambda **kwargs: ("inference", kwargs), lambda **kwargs: ("litellm", kwargs), fake_openai),
    )
    factory = ModelFactory()

    model = factory.create(AgentRunConfig(provider="ollama", model_id="llama3.1"))
    assert model[0] == "openai"
    assert captured["model_id"] == "llama3.1"
    assert captured["api_base"] == "http://localhost:11434/v1"
    assert captured["api_key"] == "ollama"

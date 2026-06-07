from __future__ import annotations

from typing import TYPE_CHECKING

from smolagents_webui.config import AgentRunConfig

if TYPE_CHECKING:
    from smolagents import Model


def _import_models():
    from smolagents import InferenceClientModel, LiteLLMModel, OpenAIModel

    return InferenceClientModel, LiteLLMModel, OpenAIModel


class ModelFactory:
    """Create smolagents model instances from WebUI configuration."""

    def create(self, config: AgentRunConfig) -> Model:
        InferenceClientModel, LiteLLMModel, OpenAIModel = _import_models()

        if config.provider == "hf_inference":
            return InferenceClientModel(
                model_id=config.model_id,
                provider=config.hf_provider,
                token=config.api_key,
                base_url=config.api_base,
            )

        if config.provider == "litellm":
            return LiteLLMModel(
                model_id=config.model_id,
                api_key=config.api_key,
                api_base=config.api_base,
            )

        if config.provider == "openai":
            return OpenAIModel(
                model_id=config.model_id,
                api_key=config.api_key,
                api_base=config.api_base,
            )

        if config.provider == "ollama":
            return OpenAIModel(
                model_id=config.model_id,
                api_key=config.api_key or "ollama",
                api_base=config.api_base or "http://localhost:11434/v1",
            )

        raise ValueError(f"Unsupported provider: {config.provider}")

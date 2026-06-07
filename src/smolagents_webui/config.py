from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ProviderName = Literal["hf_inference", "litellm", "openai", "ollama"]

DEFAULT_MODEL_BY_PROVIDER: dict[ProviderName, str] = {
    "hf_inference": "Qwen/Qwen3-Next-80B-A3B-Thinking",
    "litellm": "gpt-4o-mini",
    "openai": "gpt-4o-mini",
    "ollama": "llama3.1",
}


def _clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(slots=True)
class AgentRunConfig:
    """Runtime settings sent from the WebUI client for an agent run."""

    provider: ProviderName = "hf_inference"
    model_id: str = DEFAULT_MODEL_BY_PROVIDER["hf_inference"]
    api_base: str | None = None
    api_key: str | None = None
    hf_provider: str | None = None
    max_steps: int = 12
    planning_interval: int | None = None
    additional_imports: list[str] = field(default_factory=list)
    stream_model_output: bool = True

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "AgentRunConfig":
        if payload is None:
            payload = {}

        provider_value = str(payload.get("provider", "hf_inference")).strip().lower()
        provider: ProviderName = (
            provider_value if provider_value in {"hf_inference", "litellm", "openai", "ollama"} else "hf_inference"
        )

        default_model = DEFAULT_MODEL_BY_PROVIDER[provider]
        model_id = str(payload.get("model_id", default_model)).strip() or default_model

        planning_interval_raw = payload.get("planning_interval")
        planning_interval = None
        if planning_interval_raw not in (None, ""):
            planning_interval = _clamp_int(planning_interval_raw, default=2, minimum=1, maximum=50)

        additional_imports: list[str] = []
        raw_imports = payload.get("additional_imports", [])
        if isinstance(raw_imports, str):
            additional_imports = [item.strip() for item in raw_imports.split(",") if item.strip()]
        elif isinstance(raw_imports, list):
            additional_imports = [str(item).strip() for item in raw_imports if str(item).strip()]

        return cls(
            provider=provider,
            model_id=model_id,
            api_base=_clean_text(payload.get("api_base")),
            api_key=_clean_text(payload.get("api_key")),
            hf_provider=_clean_text(payload.get("hf_provider")),
            max_steps=_clamp_int(payload.get("max_steps"), default=12, minimum=1, maximum=100),
            planning_interval=planning_interval,
            additional_imports=additional_imports,
            stream_model_output=bool(payload.get("stream_model_output", True)),
        )

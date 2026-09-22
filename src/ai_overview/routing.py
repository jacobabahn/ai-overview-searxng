"""Provider defaults and model routing shared by configuration and selection."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Optional

from .errors import OverviewError

if TYPE_CHECKING:
    from .config import Profile
    from .models import Conversation

DEFAULTS = {
    "openai": ("responses", "https://api.openai.com/v1/responses", "OPENAI_API_KEY"),
    "openrouter": ("chat", "https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY"),
    "opencode_go": (
        "chat",
        "https://opencode.ai/zen/go/v1/chat/completions",
        "OPENCODE_GO_API_KEY",
    ),
    "gemini": ("gemini", "https://generativelanguage.googleapis.com/v1beta", "GEMINI_API_KEY"),
    "ollama": ("ollama", "http://localhost:11434/api/chat", None),
    "local": ("chat", "http://localhost:1234/v1/chat/completions", None),
}
EXTRA_OPTIONS = {
    "chat": {"temperature", "top_p", "reasoning_effort", "thinking"},
    "responses": {"temperature", "top_p", "reasoning"},
    "gemini": {"temperature", "topP", "thinkingConfig"},
    "ollama": {"temperature", "top_p", "num_ctx", "think"},
    "anthropic": {"temperature", "top_p", "thinking"},
}


# Protocol routing from https://opencode.ai/docs/go/#endpoints (2026-09-20).
# The live /models endpoint lists IDs but does not currently describe protocols.
# Unknown IDs stay visible but disabled until configured with model_protocols.
GO_PROTOCOLS = {
    **dict.fromkeys(
        [
            "glm-5.3-flash",
            "glm-5.3",
            "glm-5.2",
            "glm-5.1",
            "kimi-k3",
            "kimi-k2.7-code",
            "kimi-k2.6",
            "longcat-2.0",
            "deepseek-v4.1-flash",
            "deepseek-v4-pro",
            "deepseek-v4-flash",
            "deepseek-v4-flash-vision-exp",
            "mimo-v2.5",
            "mimo-v2.5-pro",
            "hy4-preview",
            "hy3",
        ],
        "chat",
    ),
    **dict.fromkeys(
        [
            "grok-4.6",
            "gpt-5.6-luna",
            "muse-spark-1.3-contributor",
            "muse-spark-1.2-contributor",
        ],
        "responses",
    ),
    **dict.fromkeys(
        [
            "minimax-m3",
            "minimax-m2.7",
            "minimax-m2.5",
            "qwen3.8-max",
            "qwen3.8-flash",
            "qwen3.7-max",
            "qwen3.7-plus",
            "qwen3.6-plus",
        ],
        "anthropic",
    ),
}
SUFFIXES = {"chat": "chat/completions", "responses": "responses", "anthropic": "messages"}


def go_root(endpoint: str) -> str:
    for suffix in SUFFIXES.values():
        if endpoint.endswith("/" + suffix):
            return endpoint[: -len(suffix)]
    raise OverviewError(
        "configuration", "Configure a standard Go API endpoint for model discovery."
    )


def selected_profile(profile: Profile, state: Conversation) -> Profile:
    if state.model is None:
        return profile
    protocol = state.protocol or profile.protocol
    endpoint = profile.endpoint
    if profile.backend == "opencode_go":
        endpoint = go_endpoint(endpoint, protocol)
    return replace(
        profile,
        model=state.model,
        protocol=protocol,
        endpoint=endpoint,
        options={
            k: v
            for k, v in profile.options.items()
            if k in EXTRA_OPTIONS[protocol]
            # Thinking payloads are model-specific, even across chat endpoints.
            and (k != "thinking" or (state.model == profile.model and protocol == profile.protocol))
        },
    )


def go_endpoint(endpoint: str, protocol: str) -> str:
    if protocol not in SUFFIXES:
        raise OverviewError("configuration", "Unsupported model protocol.")
    return go_root(endpoint) + SUFFIXES[protocol]


def model_protocol(profile: Profile, model: str) -> Optional[str]:
    if model == profile.model:
        return profile.protocol
    return profile.model_protocols.get(model, GO_PROTOCOLS.get(model))

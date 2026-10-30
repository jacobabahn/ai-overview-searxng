"""Provider defaults and model routing shared by configuration and selection."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from .errors import OverviewError
from .providers.protocols import PROTOCOLS

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


# Protocol routing from https://opencode.ai/docs/go/#endpoints (2026-10-29).
# The live /models endpoint lists IDs but does not currently describe protocols.
# Go translates between protocols, so this table only picks each model's native one.
GO_PROTOCOLS = {
    **dict.fromkeys(
        [
            "glm-5.3-flash",
            "glm-5.3",
            "glm-5.2",
            "kimi-k3.1-pro",
            "kimi-k3",
            "kimi-k2.7-code",
            "longcat-2.0",
            "deepseek-v4.1-flash",
            "deepseek-v4-pro",
            "mimo-v2.6-flash",
            "mimo-v2.6-pro",
            "mimo-v2.5",
            "mimo-v2.5-pro",
            "minimax-m3.1-flash",
            "hy4-preview",
            "hy3",
            "step-5-preview",
            "beam-free",
            "iceman-contributor-free",
        ],
        "chat",
    ),
    **dict.fromkeys(
        [
            "grok-4.7",
            "gpt-6-luna",
            "gpt-5.6-luna",
            "muse-spark-1.3-contributor",
            "muse-spark-1.2-contributor",
        ],
        "responses",
    ),
    **dict.fromkeys(
        [
            "claude-haiku-5-5",
            "minimax-m3",
            "qwen3.8-max",
            "qwen3.8-flash",
            "qwen3.7-plus",
        ],
        "anthropic",
    ),
}
# IDs missing from the table use Messages. In a 2026-10-29 check every catalog
# model answered cleanly there, while Chat Completions leaked minimax-m3's
# <think> reasoning into the answer text.
GO_FALLBACK = "anthropic"
SUFFIXES = {name: p.go_suffix for name, p in PROTOCOLS.items() if p.go_suffix}


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
    adapter = PROTOCOLS[protocol]
    same_model = state.model == profile.model and protocol == profile.protocol
    return replace(
        profile,
        model=state.model,
        protocol=protocol,
        endpoint=endpoint,
        options={
            k: v
            for k, v in profile.options.items()
            if k in adapter.options and (same_model or k not in adapter.model_options)
        },
    )


def go_endpoint(endpoint: str, protocol: str) -> str:
    if protocol not in SUFFIXES:
        raise OverviewError("configuration", "Unsupported model protocol.")
    return go_root(endpoint) + SUFFIXES[protocol]


def model_protocol(profile: Profile, model: str) -> str:
    if model == profile.model:
        return profile.protocol
    return profile.model_protocols.get(model, GO_PROTOCOLS.get(model, GO_FALLBACK))

"""Thinking levels: one reader-facing setting, sent in each wire protocol's terms."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .config import Profile

# Levels each protocol can express, quickest first. Ollama models only switch
# thinking on or off; an OpenAI Responses model always reasons a little.
LEVELS: dict[str, tuple[str, ...]] = {
    "chat": ("off", "low", "medium", "high"),
    "responses": ("low", "medium", "high"),
    "anthropic": ("off", "low", "medium", "high"),
    "gemini": ("off", "low", "medium", "high"),
    "ollama": ("off", "on"),
}
# Token budgets for protocols that size thinking rather than name an effort.
BUDGETS = {"low": 1024, "medium": 4096, "high": 16384}


def levels(profile: Profile, protocol: Optional[str] = None) -> tuple[str, ...]:
    """Levels a reader may choose for this profile, or none unless it opts in."""
    if not profile.thinking_control:
        return ()
    return LEVELS.get(protocol or profile.protocol, ())


def options(protocol: str, level: str) -> dict[str, Any]:
    """Request options that ask `protocol` for `level`."""
    off = level == "off"
    if protocol == "chat":
        if off:
            return {"thinking": {"type": "disabled"}}
        return {"thinking": {"type": "enabled"}, "reasoning_effort": level}
    if protocol == "responses":
        return {"reasoning": {"effort": level}}
    if protocol == "anthropic":
        if off:
            return {"thinking": {"type": "disabled"}}
        return {"thinking": {"type": "enabled", "budget_tokens": BUDGETS[level]}}
    if protocol == "gemini":
        return {"thinkingConfig": {"thinkingBudget": 0 if off else BUDGETS[level]}}
    if protocol == "ollama":
        return {"think": not off}
    raise ValueError(f"Thinking is not supported for {protocol}")


def with_thinking(profile: Profile, level: Optional[str]) -> Profile:
    """The profile with a chosen level applied; an unknown or absent level changes nothing."""
    if level is None or level not in levels(profile):
        return profile
    return replace(profile, options={**profile.options, **options(profile.protocol, level)})


def quickest(profile: Profile) -> Profile:
    """The profile at its least thinking, for short background requests."""
    available = levels(profile)
    return with_thinking(profile, available[0]) if available else profile


def thinking_budget(options: dict[str, Any]) -> int:
    """Tokens a request's thinking may spend on top of its answer, if it sizes them."""
    thinking = options.get("thinking")
    if isinstance(thinking, dict) and thinking.get("type") == "enabled":
        return int(thinking.get("budget_tokens", 0))
    config = options.get("thinkingConfig")
    if isinstance(config, dict):
        return max(0, int(config.get("thinkingBudget", 0)))
    return 0

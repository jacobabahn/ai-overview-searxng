from dataclasses import replace
from typing import Any

import pytest
from test_service import ScriptedTransport

from ai_overview.catalog import ModelCatalog
from ai_overview.config import Config, Profile
from ai_overview.errors import OverviewError
from ai_overview.evidence import build_sources
from ai_overview.models import Message
from ai_overview.providers.protocols import PROTOCOLS
from ai_overview.service import GenerationService
from ai_overview.state import StateSigner, initial_state
from ai_overview.thinking import levels, options, quickest, with_thinking


def profile(backend: str = "local", control: Any = True, **settings: Any) -> Profile:
    config = Config.from_dict(
        {
            "default_profile": "p",
            "profiles": {
                "p": {"backend": backend, "model": "m", "thinking_control": control, **settings}
            },
        }
    )
    return config.profiles["p"]


def test_each_protocol_names_its_own_levels() -> None:
    assert levels(profile("ollama")) == ("off", "on")
    assert levels(profile("openai")) == ("low", "medium", "high")
    assert levels(profile("local")) == ("off", "low", "medium", "high")
    # Readers choose only where the operator opted in.
    assert levels(profile(control=False)) == ()
    assert options("chat", "off") == {"thinking": {"type": "disabled"}}
    assert options("chat", "high") == {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}
    assert options("responses", "low") == {"reasoning": {"effort": "low"}}
    assert options("anthropic", "medium") == {
        "thinking": {"type": "enabled", "budget_tokens": 4096}
    }
    assert options("gemini", "off") == {"thinkingConfig": {"thinkingBudget": 0}}
    assert options("ollama", "on") == {"think": True}
    # Every generated option passes the protocol's own validation.
    for protocol, offered in (
        ("chat", ("off", "low")),
        ("anthropic", ("off", "high")),
        ("gemini", ("off", "high")),
        ("ollama", ("off", "on")),
        ("responses", ("low",)),
    ):
        for level in offered:
            PROTOCOLS[protocol].validate_options(options(protocol, level))
    with pytest.raises(ValueError, match="thinking_control must be a boolean"):
        profile(control="yes")


def test_levels_apply_over_profile_options_and_unknown_levels_change_nothing() -> None:
    base = profile("ollama", options={"num_ctx": 8192, "think": True})
    assert with_thinking(base, "off").options == {"num_ctx": 8192, "think": False}
    assert with_thinking(base, None) is base
    assert with_thinking(base, "high") is base
    assert quickest(base).options["think"] is False
    assert quickest(profile("openai")).options == {"reasoning": {"effort": "low"}}
    assert quickest(profile(control=False)) == profile(control=False)


def test_sized_thinking_comes_on_top_of_the_answer_limit() -> None:
    messages = [Message("user", "q")]
    anthropic = with_thinking(profile("openrouter", protocol="anthropic"), "low")
    _, body = PROTOCOLS["anthropic"].request(anthropic, messages, 1200)
    assert body["max_tokens"] == 1200 + 1024
    gemini = with_thinking(profile("gemini"), "medium")
    _, body = PROTOCOLS["gemini"].request(gemini, messages, 1200)
    assert body["generationConfig"]["maxOutputTokens"] == 1200 + 4096
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 4096}
    off = with_thinking(profile("gemini"), "off")
    _, body = PROTOCOLS["gemini"].request(off, messages, 1200)
    assert body["generationConfig"]["maxOutputTokens"] == 1200


def catalog_config(control: bool = True) -> Config:
    return Config.from_dict(
        {
            "default_profile": "p",
            "model_picker": True,
            "profiles": {"p": {"backend": "local", "model": "m", "thinking_control": control}},
        }
    )


def test_selection_offers_and_validates_the_models_levels() -> None:
    catalog = ModelCatalog(catalog_config())
    (choice,) = catalog.list().choices
    assert choice.thinking_levels == ("off", "low", "medium", "high")
    state = initial_state("q?", (), "p")
    assert catalog.select(state, "p", "m", "low").thinking == "low"
    assert catalog.select(state, "p", "m").thinking is None
    with pytest.raises(OverviewError, match="thinking level"):
        catalog.select(state, "p", "m", "on")
    with pytest.raises(OverviewError, match="thinking level"):
        ModelCatalog(catalog_config(False)).select(state, "p", "m", "low")


def test_answers_think_as_chosen_and_background_requests_think_least() -> None:
    config = Config.from_dict(
        {
            "default_profile": "p",
            "profiles": {
                "p": {"backend": "local", "model": "m", "thinking_control": True, "options": {}}
            },
            "answer_cache_entries": 4,
        }
    )
    transport = ScriptedTransport(
        ["First [1]", '{"questions": ["Next?"]}', '{"query": null}', "Second [1]"]
    )
    service = GenerationService(
        config,
        StateSigner("s" * 32),
        transport,
        lambda *_: build_sources([{"url": "https://b.com", "content": "More"}]),
    )
    sources = build_sources([{"url": "https://a.com", "content": "Evidence"}])
    state = replace(initial_state("q?", sources, "p"), thinking="high")
    done = list(service.run(state, None, client="c"))[-1]
    continuation = service.signer.loads(done.data["token"])
    service.suggest(continuation)
    list(service.run(continuation, "Why?"))
    answer, suggest, plan, follow_up = transport.calls
    high = {"type": "enabled"}, "high"
    assert (answer["thinking"], answer["reasoning_effort"]) == high
    assert (follow_up["thinking"], follow_up["reasoning_effort"]) == high
    for background in (suggest, plan):
        assert background["thinking"] == {"type": "disabled"}
        assert "reasoning_effort" not in background
    # A different level is a different answer to cache.
    assert service.replay(state, None, "c") is not None
    assert service.replay(replace(state, thinking="low"), None, "c") is None

from dataclasses import replace

import pytest

from ai_overview.config import Config, Profile
from ai_overview.routing import model_protocol, selected_profile
from ai_overview.state import initial_state


def profile() -> Profile:
    return Config.from_dict(
        {
            "default_profile": "go",
            "profiles": {"go": {"backend": "opencode_go", "model": "deepseek-v4-flash"}},
        }
    ).profiles["go"]


def test_selected_profile_changes_protocol_and_keeps_credentials() -> None:
    p = replace(profile(), api_key="secret", options={"reasoning_effort": "low"})
    state = replace(initial_state("q?", (), "go"), model="minimax-m3", protocol="anthropic")
    selected = selected_profile(p, state)
    assert selected.endpoint == "https://opencode.ai/zen/go/v1/messages"
    assert selected.protocol == "anthropic"
    assert selected.api_key == "secret"
    assert selected.options == {}
    assert "secret" not in repr(selected)


@pytest.mark.parametrize("model,protocol", [("glm-5.2", "chat"), ("minimax-m3", "anthropic")])
def test_thinking_control_is_scoped_to_configured_model(model: str, protocol: str) -> None:
    p = replace(profile(), options={"thinking": {"type": "disabled"}})
    initial = initial_state("q?", (), "go")
    assert selected_profile(p, initial).options == p.options
    pinned = replace(initial, model=p.model, protocol=p.protocol)
    assert selected_profile(p, pinned).options == p.options
    switched = replace(initial, model=model, protocol=protocol)
    assert selected_profile(p, switched).options == {}


@pytest.mark.parametrize(
    "protocol,suffix",
    [("chat", "chat/completions"), ("responses", "responses"), ("anthropic", "messages")],
)
def test_initial_and_selected_go_models_share_endpoint_rules(protocol: str, suffix: str) -> None:
    configured = Config.from_dict(
        {
            "default_profile": "go",
            "profiles": {
                "go": {"backend": "opencode_go", "model": "chosen", "protocol": protocol},
            },
        }
    ).profiles["go"]
    state = replace(initial_state("q?", (), "go"), model="chosen", protocol=protocol)
    selected = selected_profile(profile(), state)
    assert selected.endpoint == configured.endpoint == f"https://opencode.ai/zen/go/v1/{suffix}"
    custom = replace(profile(), endpoint="https://proxy.example/go/chat/completions")
    assert selected_profile(custom, state).endpoint == f"https://proxy.example/go/{suffix}"


def test_routing_prefers_operator_overrides_and_leaves_unknown_models_unavailable() -> None:
    p = replace(profile(), model_protocols={"custom": "anthropic", "glm-5.2": "responses"})
    assert model_protocol(p, "custom") == "anthropic"
    assert model_protocol(p, "glm-5.2") == "responses"
    assert model_protocol(p, "unknown") is None
    assert model_protocol(p, p.model) == p.protocol


def test_signed_selection_remains_pinned_when_default_changes() -> None:
    p = profile()
    state = replace(initial_state("q?", (), "go"), model=p.model, protocol=p.protocol)
    changed = replace(
        p,
        model="minimax-m3",
        protocol="anthropic",
        endpoint="https://opencode.ai/zen/go/v1/messages",
    )
    resolved = selected_profile(changed, state)
    assert (resolved.model, resolved.protocol, resolved.endpoint) == (
        p.model,
        p.protocol,
        p.endpoint,
    )

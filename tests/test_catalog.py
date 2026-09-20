from dataclasses import replace
from typing import Any

import pytest
from flask import Flask
from test_service import ScriptedTransport

from ai_overview.catalog import ModelCatalog
from ai_overview.config import Config, Profile
from ai_overview.errors import OverviewError
from ai_overview.models import Turn
from ai_overview.providers.transport import read_catalog
from ai_overview.service import GenerationService
from ai_overview.state import StateSigner, initial_state
from ai_overview.web import register


def config(enabled: bool = True) -> Config:
    return Config.from_dict(
        {
            "default_profile": "go",
            "model_picker": enabled,
            "profiles": {
                "go": {
                    "backend": "opencode_go",
                    "model": "deepseek-v4-flash",
                    "discover_models": True,
                }
            },
        }
    )


def test_discovery_is_cached_and_protocols_are_explicit() -> None:
    calls: list[str] = []

    def fetch(url: str, profile: Profile) -> dict[str, Any]:
        calls.append(url)
        return {
            "data": [
                {"id": m}
                for m in ["deepseek-v4-flash", "gpt-5.6-luna", "minimax-m3", "new-unmapped-model"]
            ]
        }

    catalog = ModelCatalog(config(), fetch)
    first = catalog.list()
    assert catalog.list() == first
    assert calls == ["https://opencode.ai/zen/go/v1/models"]
    models = {c.model: c for c in first.choices}
    assert models["deepseek-v4-flash"].protocol == "chat"
    assert models["gpt-5.6-luna"].protocol == "responses"
    assert models["minimax-m3"].protocol == "anthropic"
    assert not models["new-unmapped-model"].available


def test_failed_discovery_preserves_configured_model() -> None:
    calls: list[str] = []

    def fetch(url: str, profile: Profile) -> dict[str, Any]:
        calls.append(url)
        raise OverviewError("timeout", "timeout")

    catalog = ModelCatalog(config(), fetch)
    result = catalog.list()
    assert result.choices[0].model == "deepseek-v4-flash"
    assert result.warnings
    assert catalog.list() == result
    assert len(calls) == 1


def test_selection_requires_initial_state_and_known_model() -> None:
    c = config()
    catalog = ModelCatalog(c)
    initial = initial_state("q?", (), "go")
    selected = catalog.select(initial, "go", "deepseek-v4-flash")
    assert selected.session != initial.session
    assert selected.model == "deepseek-v4-flash"
    assert selected.query == initial.query
    for profile_name, model in [("evil", "deepseek-v4-flash"), ("go", "unknown"), ([], "model")]:
        with pytest.raises(OverviewError):
            catalog.select(initial, profile_name, model)
    with pytest.raises(OverviewError):
        catalog.select(replace(initial, turns=(Turn("q", "a", ()),)), "go", "deepseek-v4-flash")
    with pytest.raises(OverviewError):
        ModelCatalog(config(False)).select(initial, "go", "deepseek-v4-flash")


def test_selection_endpoints_sign_model_without_exposing_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-secret-value")
    c = config()
    signer = StateSigner("s" * 32)
    service = GenerationService(
        c, signer, ScriptedTransport([]), lambda query, options, timeout: ()
    )
    app = Flask(__name__)
    register(app, service)
    client = app.test_client()
    token = signer.dumps(initial_state("q?", (), "go"))
    models = client.post("/ai-overview/models", json={"token": token})
    assert models.status_code == 200
    assert b"test-secret-value" not in models.data
    response = client.post(
        "/ai-overview/select", json={"token": token, "profile": "go", "model": "deepseek-v4-flash"}
    )
    data = response.get_json()
    assert isinstance(data, dict)
    assert signer.loads(data["token"]).model == "deepseek-v4-flash"
    assert client.post("/ai-overview/models", json={"token": "bad"}).status_code == 403
    assert (
        client.post(
            "/ai-overview/models", json={"token": token}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/ai-overview/select", json={"token": token, "profile": "go", "model": "evil"}
        ).status_code
        == 400
    )


def test_catalog_response_limits() -> None:
    assert read_catalog([b'{"data":', b"[]}"]) == {"data": []}
    for chunks in [[b"a" * 1_000_001], [b"[]"], [b"invalid"]]:
        with pytest.raises(OverviewError):
            read_catalog(chunks)

import threading
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
                    "model": "deepseek-v4.1-flash",
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
                for m in ["deepseek-v4.1-flash", "gpt-5.6-luna", "minimax-m3", "new-unmapped-model"]
            ]
        }

    catalog = ModelCatalog(config(), fetch)
    first = catalog.list()
    assert catalog.list() == first
    assert calls == ["https://opencode.ai/zen/go/v1/models"]
    models = {c.model: c for c in first.choices}
    assert models["deepseek-v4.1-flash"].protocol == "chat"
    assert models["gpt-5.6-luna"].protocol == "responses"
    assert models["minimax-m3"].protocol == "anthropic"
    assert models["new-unmapped-model"].protocol == "anthropic"
    assert first.warnings == ()


def test_retired_configured_model_stays_selectable_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    catalog = ModelCatalog(config(), lambda url, profile: {"data": [{"id": "glm-5.3"}]})
    result = catalog.list()
    assert [c.model for c in result.choices] == ["deepseek-v4.1-flash", "glm-5.3"]
    assert result.warnings == (
        "deepseek-v4.1-flash is no longer in the go model list; update the configured model.",
    )
    assert catalog.list().warnings == result.warnings
    assert "deepseek-v4.1-flash" in caplog.text


def test_failed_discovery_preserves_configured_model() -> None:
    calls: list[str] = []

    def fetch(url: str, profile: Profile) -> dict[str, Any]:
        calls.append(url)
        raise OverviewError("timeout", "timeout")

    catalog = ModelCatalog(config(), fetch)
    result = catalog.list()
    assert result.choices[0].model == "deepseek-v4.1-flash"
    assert result.warnings
    assert catalog.list() == result
    assert len(calls) == 1


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_failed_refresh_backs_off_and_shows_saved_choices() -> None:
    clock = Clock()
    calls: list[str] = []
    replies: list[Any] = [{"data": [{"id": "deepseek-v4.1-flash"}, {"id": "glm-5.3"}]}]

    def fetch(url: str, profile: Profile) -> dict[str, Any]:
        calls.append(url)
        if not replies:
            raise OverviewError("timeout", "timeout")
        return replies.pop(0)

    catalog = ModelCatalog(config(), fetch, clock)
    saved = catalog.list()
    assert saved.warnings == ()
    clock.now += 299
    assert catalog.list() == saved
    assert len(calls) == 1

    clock.now += 2
    failed = catalog.list()
    assert failed.choices == saved.choices
    assert failed.warnings == ("Could not refresh models for go; showing saved choices.",)
    clock.now += 14
    assert catalog.list() == failed
    assert len(calls) == 2

    clock.now += 2
    replies.append({"data": [{"id": "deepseek-v4.1-flash"}]})
    recovered = catalog.list()
    assert [c.model for c in recovered.choices] == ["deepseek-v4.1-flash"]
    assert recovered.warnings == ()
    assert len(calls) == 3


def test_slow_refresh_does_not_block_requests_served_from_cache() -> None:
    clock = Clock()
    calls: list[str] = []
    started = threading.Event()
    release = threading.Event()

    def fetch(url: str, profile: Profile) -> dict[str, Any]:
        calls.append(url)
        if len(calls) == 1:
            return {"data": [{"id": "deepseek-v4.1-flash"}, {"id": "glm-5.3"}]}
        started.set()
        # A request stuck behind this fetch would return its fresh list, failing below.
        assert release.wait(10)
        return {"data": [{"id": "deepseek-v4.1-flash"}, {"id": "kimi-k3"}]}

    catalog = ModelCatalog(config(), fetch, clock)
    saved = catalog.list()
    clock.now += 301
    refreshed: list[Any] = []
    refresher = threading.Thread(target=lambda: refreshed.append(catalog.list()))
    refresher.start()
    try:
        assert started.wait(10)
        # The refresh is in flight: others get the saved entry and start no second fetch.
        assert catalog.list() == saved
        selected = catalog.select(initial_state("q?", (), "go"), "go", "glm-5.3")
        assert selected.model == "glm-5.3"
        assert len(calls) == 2
    finally:
        release.set()
        refresher.join(10)
    assert not refresher.is_alive()
    assert [c.model for c in refreshed[0].choices] == ["deepseek-v4.1-flash", "kimi-k3"]
    assert catalog.list() == refreshed[0]
    assert len(calls) == 2


def test_concurrent_first_requests_share_one_fetch() -> None:
    calls: list[str] = []
    started = threading.Event()
    release = threading.Event()

    def fetch(url: str, profile: Profile) -> dict[str, Any]:
        calls.append(url)
        started.set()
        assert release.wait(10)
        return {"data": [{"id": "deepseek-v4.1-flash"}, {"id": "glm-5.3"}]}

    catalog = ModelCatalog(config(), fetch)
    results: list[Any] = []
    workers = [threading.Thread(target=lambda: results.append(catalog.list())) for _ in range(4)]
    workers[0].start()
    assert started.wait(10)
    for worker in workers[1:]:
        worker.start()
    release.set()
    for worker in workers:
        worker.join(10)
    assert len(results) == 4
    assert all(r == results[0] for r in results)
    assert [c.model for c in results[0].choices] == ["deepseek-v4.1-flash", "glm-5.3"]
    assert len(calls) == 1


def test_selection_requires_initial_state_and_known_model() -> None:
    c = config()
    catalog = ModelCatalog(c)
    initial = initial_state("q?", (), "go")
    selected = catalog.select(initial, "go", "deepseek-v4.1-flash")
    assert selected.session != initial.session
    assert selected.model == "deepseek-v4.1-flash"
    assert selected.query == initial.query
    for profile_name, model in [("evil", "deepseek-v4.1-flash"), ("go", "unknown"), ([], "model")]:
        with pytest.raises(OverviewError):
            catalog.select(initial, profile_name, model)
    with pytest.raises(OverviewError):
        catalog.select(replace(initial, turns=(Turn("q", "a", ()),)), "go", "deepseek-v4.1-flash")
    with pytest.raises(OverviewError):
        ModelCatalog(config(False)).select(initial, "go", "deepseek-v4.1-flash")


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
        "/ai-overview/select",
        json={"token": token, "profile": "go", "model": "deepseek-v4.1-flash"},
    )
    data = response.get_json()
    assert isinstance(data, dict)
    assert signer.loads(data["token"]).model == "deepseek-v4.1-flash"
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

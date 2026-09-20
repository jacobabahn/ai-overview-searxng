import json
from dataclasses import dataclass, replace
from typing import Any

import pytest

from ai_overview.config import Config
from ai_overview.errors import OverviewError
from ai_overview.evidence import build_sources, eligible, safe_url
from ai_overview.models import Conversation
from ai_overview.state import StateSigner, initial_state


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("why?", True),
        ("why?  ", True),
        ("what? next", False),
        ("why", False),
        ("", False),
    ],
)
def test_activation(query: str, expected: bool) -> None:
    assert eligible(query) is expected
    assert not eligible(query, page=2)
    assert not eligible(query, output_format="json")
    assert not eligible(query, categories=["images"])


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,x",
        "//example.com",
        "https://user:pass@example.com",
        "https://a\\b.com",
        "https://a.com\n",
        "https://a.com:invalid",
    ],
)
def test_source_url_rejections(url: str) -> None:
    assert safe_url(url) is None


def test_evidence_deduplicates_and_bounds_unicode() -> None:
    results = [
        {"url": "https://example.com/#a", "title": "<b>Title</b>", "content": "é" * 3000},
        {"url": "https://example.com/#b", "content": "duplicate"},
        {"url": "javascript:alert(1)", "content": "bad"},
        {"url": "https://empty.com", "title": "no snippet"},
    ]
    sources = build_sources(results, budget=1000)
    assert len(sources) == 1
    assert sources[0].title == "Title"
    assert sources[0].url == "https://example.com/"
    assert len(sources[0].snippet.encode()) < 1000


def test_typed_searxng_results_without_mapping_methods() -> None:
    @dataclass
    class TypedResult:
        url: str
        title: str
        content: str

    result = TypedResult("https://example.com", "Title", "Evidence from a typed result")
    sources = build_sources([result])
    assert sources[0].snippet == result.content
    assert sources[0].title == "Title"


def test_signed_state_tampering_and_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    signer = StateSigner("s" * 32, ttl=10)
    state = initial_state("why?", (), "local")
    token = signer.dumps(state)
    assert signer.loads(token) == state
    with pytest.raises(OverviewError):
        signer.loads(token[:-5] + "wrong")
    with pytest.raises(OverviewError):
        signer.loads({"query": "arbitrary"})
    monkeypatch.setattr("itsdangerous.timed.TimestampSigner.get_timestamp", lambda self: 9999999999)
    with pytest.raises(OverviewError):
        signer.loads(token)


def test_state_roundtrip_preserves_source_snapshots() -> None:
    state = initial_state(
        "why?", build_sources([{"url": "https://a.com", "content": "evidence"}]), "local"
    )
    signer = StateSigner("s" * 32)
    restored: Conversation = signer.loads(signer.dumps(state))
    assert restored.sources[0].snippet == "evidence"
    assert replace(restored, query="other?").session == restored.session


@pytest.mark.parametrize(
    "backend", ["local", "ollama", "openai", "openrouter", "gemini", "opencode_go"]
)
def test_profile_defaults(backend: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_KEY", "private-value")
    config = Config.from_dict(
        {
            "default_profile": "test",
            "profiles": {
                "test": {"backend": backend, "model": "test-model", "api_key_env": "TEST_KEY"}
            },
        }
    )
    assert config.profiles["test"].api_key == "private-value"
    assert "private-value" not in repr(config)


@pytest.mark.parametrize("patch", [{"max_turns": 0}, {"typo": 1}, {"evidence_bytes": 999999}])
def test_invalid_config(patch: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        Config.from_dict(
            {
                "default_profile": "test",
                "profiles": {"test": {"backend": "local", "model": "test"}},
                **patch,
            }
        )


def test_provider_payload_overrides_are_rejected() -> None:
    with pytest.raises(ValueError):
        Config.from_dict(
            json.loads(
                '{"default_profile":"test","profiles":{"test":{"backend":"local","model":"test","options":{"messages":[]}}}}'
            )
        )

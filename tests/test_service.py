import json
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Any, Optional

import pytest
from flask import Flask

from ai_overview.config import Config, Profile
from ai_overview.errors import OverviewError
from ai_overview.evidence import build_sources
from ai_overview.models import SearchOptions, Source
from ai_overview.service import GenerationService
from ai_overview.state import StateSigner, initial_state
from ai_overview.web import register, render_panel


@dataclass
class ScriptedTransport:
    answers: list[str]
    calls: list[dict[str, Any]] = field(default_factory=list)

    @contextmanager
    def stream(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        profile: Profile,
        *,
        deadline: Optional[float] = None,
    ) -> Iterator[Iterable[bytes]]:
        self.calls.append(body)
        text = self.answers.pop(0)
        yield [
            (
                "data: "
                + json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": None}]})
                + "\n\n"
            ).encode(),
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
        ]


def make_service(answers: list[str]) -> tuple[GenerationService, list[str], ScriptedTransport]:
    config = Config.from_dict(
        {"default_profile": "test", "profiles": {"test": {"backend": "local", "model": "test"}}}
    )
    queries: list[str] = []

    def retrieve(query: str, options: SearchOptions, timeout: float) -> tuple[Source, ...]:
        queries.append(query)
        return build_sources([{"url": "https://new.example", "content": "Fresh evidence"}])

    transport = ScriptedTransport(answers)
    return GenerationService(config, StateSigner("s" * 32), transport, retrieve), queries, transport


def test_followup_search_and_per_turn_citations() -> None:
    service, queries, transport = make_service(
        ["First [1]", '{"query":"new standalone question"}', "Second [1]"]
    )
    state = initial_state(
        "initial?",
        build_sources([{"url": "https://old.example", "content": "Old evidence"}]),
        "test",
    )
    initial = list(service.run(state, None))
    continuation = service.signer.loads(initial[-1].data["token"])
    assert queries == []
    following = list(service.run(continuation, "What about those?"))
    completed = service.signer.loads(following[-1].data["token"])
    assert queries == ["new standalone question"]
    assert completed.turns[0].sources[0].url == "https://old.example"
    assert completed.turns[1].sources[0].url == "https://new.example"
    assert len(transport.calls) == 3


def test_followup_reuses_evidence() -> None:
    service, queries, _ = make_service(["First [1]", '{"query":null}', "Simpler [1]"])
    state = initial_state(
        "initial?", build_sources([{"url": "https://example.com", "content": "Evidence"}]), "test"
    )
    events = list(service.run(state, None))
    events = list(service.run(service.signer.loads(events[-1].data["token"]), "Explain simply"))
    assert events[-1].name == "done"
    assert not queries


def test_default_model_stays_pinned_after_config_change() -> None:
    service, _, transport = make_service(["First [1]", '{"query":null}', "Simpler [1]"])
    state = initial_state(
        "initial?", build_sources([{"url": "https://example.com", "content": "Evidence"}]), "test"
    )
    events = list(service.run(state, None))
    continuation = service.signer.loads(events[-1].data["token"])
    assert continuation.model == "test"
    service.config = replace(
        service.config,
        profiles={"test": replace(service.config.profiles["test"], model="new-default")},
    )
    list(service.run(continuation, "Explain simply"))
    assert all(call["model"] == "test" for call in transport.calls)


def test_empty_evidence_does_not_call_provider() -> None:
    service, _, transport = make_service([])
    events = list(service.run(initial_state("q?", (), "test"), None))
    assert events[-1].data["code"] == "insufficient_evidence"
    assert not transport.calls


def test_context_limit_does_not_silently_truncate() -> None:
    service, _, _ = make_service([])
    state = initial_state(
        "a" * 60000, build_sources([{"url": "https://a.com", "content": "evidence"}]), "test"
    )
    with pytest.raises(OverviewError) as caught:
        list(service.run(state, None))
    assert caught.value.code == "context_limit"


def test_web_auth_origin_validation_and_stream() -> None:
    service, _, transport = make_service(["Hello [1]"])
    app = Flask(__name__)
    register(app, service)
    client = app.test_client()
    token = service.signer.dumps(
        initial_state(
            "q?", build_sources([{"url": "https://a.com", "content": "evidence"}]), "test"
        )
    )
    assert client.post("/ai-overview/stream", json={"token": "bad"}).status_code == 403
    assert (
        client.post(
            "/ai-overview/stream", json={"token": token}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 400
    )
    assert (
        client.post("/ai-overview/stream", json={"token": token, "profile": "other"}).status_code
        == 400
    )
    response = client.post("/ai-overview/stream", json={"token": token})
    assert b"event: done" in response.data
    assert response.headers["X-Accel-Buffering"] == "no"
    assert len(transport.calls) == 1


def test_shell_escapes_content_and_uses_external_assets() -> None:
    service, _, _ = make_service([])
    app = Flask(__name__)
    register(app, service)
    with app.test_request_context():
        shell = str(
            render_panel(service, initial_state('</script><img onerror="alert(1)">?', (), "test"))
        )
    assert "<img onerror=" not in shell
    assert 'type="module" src=' in shell
    assert "/ai-overview/static/overview.css" in shell


@pytest.mark.parametrize(
    "planning_time,retrieval_time,answer_time,expected_calls,succeeds",
    [(10, 0, 0, 1, False), (8, 3, 0, 1, False), (4, 2, 5, 2, False), (4, 2, 3, 2, True)],
)
def test_followup_shares_deadline_and_never_commits_late_completion(
    monkeypatch: pytest.MonkeyPatch,
    planning_time: int,
    retrieval_time: int,
    answer_time: int,
    expected_calls: int,
    succeeds: bool,
) -> None:
    from ai_overview.models import Event, Turn

    clock = [100.0]
    monkeypatch.setattr("ai_overview.service.time.monotonic", lambda: clock[0])
    service, _, transport = make_service(['{"query":"fresh"}', "Answer [1]"])
    service.config = replace(
        service.config,
        profiles={"test": replace(service.config.profiles["test"], timeout_seconds=10)},
    )
    sources = build_sources([{"url": "https://old.example", "content": "Evidence"}])
    state = replace(initial_state("q?", sources, "test"), turns=(Turn("q?", "First", sources),))
    deadlines: list[Optional[float]] = []
    closed: list[bool] = []
    original_stream = transport.stream

    @contextmanager
    def timed_stream(
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        profile: Profile,
        *,
        deadline: Optional[float] = None,
    ) -> Iterator[Iterable[bytes]]:
        deadlines.append(deadline)
        elapsed = planning_time if len(deadlines) == 1 else answer_time
        try:
            with original_stream(url, headers, body, profile, deadline=deadline) as chunks:

                def delayed() -> Iterator[bytes]:
                    for index, chunk in enumerate(chunks):
                        # Completion can arrive late even after text arrived on time.
                        if index == 1:
                            clock[0] += elapsed
                        yield chunk

                yield delayed()
        finally:
            closed.append(True)

    monkeypatch.setattr(transport, "stream", timed_stream)
    allowances: list[float] = []

    def retrieve(query: str, options: SearchOptions, timeout: float) -> tuple[Source, ...]:
        allowances.append(timeout)
        clock[0] += retrieval_time
        return sources

    service.retrieve = retrieve
    events: list[Event] = []
    if succeeds:
        events.extend(service.run(state, "Why?"))
        assert events[-1].name == "done"
        assert len(service.signer.loads(events[-1].data["token"]).turns) == 2
    else:
        with pytest.raises(OverviewError) as caught:
            events.extend(service.run(state, "Why?"))
        assert caught.value.code == "timeout"
        assert not any(event.name == "done" for event in events)
    assert len(state.turns) == 1
    assert deadlines == [110.0] * expected_calls
    assert len(transport.calls) == len(closed) == expected_calls
    assert allowances == ([] if planning_time >= 10 else [10 - planning_time])


def test_expired_turn_does_not_start_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    monkeypatch.setattr("ai_overview.service.time.monotonic", lambda: clock[0])
    service, _, transport = make_service(["unused"])
    sources = build_sources([{"url": "https://a.example", "content": "Evidence"}])
    stream = service.run(initial_state("q?", sources, "test"), None)
    assert next(stream).name == "sources"
    assert next(stream).name == "status"
    clock[0] += 90
    with pytest.raises(OverviewError) as caught:
        next(stream)
    assert caught.value.code == "timeout"
    assert not transport.calls

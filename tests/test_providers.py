import json
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Optional

import pytest

from ai_overview.config import Config, Profile
from ai_overview.errors import OverviewError
from ai_overview.models import Message
from ai_overview.providers import Provider
from ai_overview.providers.parsing import sse
from ai_overview.providers.transport import HTTPXTransport


@dataclass
class RecordingTransport:
    payload: bytes
    calls: list[tuple[str, dict[str, str], dict[str, Any]]] = field(default_factory=list)
    closed: bool = False

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
        self.calls.append((url, headers, body))
        try:
            yield (self.payload[i : i + 1] for i in range(len(self.payload)))
        finally:
            self.closed = True


def frame(value: dict[str, Any]) -> bytes:
    return ("data: " + json.dumps(value, ensure_ascii=False) + "\r\n\r\n").encode()


def profile(backend: str = "local", protocol: Optional[str] = None) -> Profile:
    raw: dict[str, Any] = {
        "backend": backend,
        "model": "test-model",
        "api_key_env": "TEST_PROVIDER_KEY",
    }
    if protocol:
        raw["protocol"] = protocol
    return Config.from_dict({"default_profile": "test", "profiles": {"test": raw}}).profiles["test"]


def payload(protocol: str, finish: bool = True) -> bytes:
    if protocol == "anthropic":
        result = frame(
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "café [1]"}}
        )
        return result + (
            frame({"type": "message_delta", "delta": {"stop_reason": "end_turn"}})
            + frame({"type": "message_stop"})
            if finish
            else b""
        )
    if protocol == "chat":
        result = frame({"choices": [{"delta": {"content": "café [1]"}, "finish_reason": None}]})
        return result + (
            frame({"choices": [{"delta": {}, "finish_reason": "stop"}]}) if finish else b""
        )
    if protocol == "responses":
        result = frame({"type": "response.output_text.delta", "delta": "café [1]"})
        return result + (
            frame({"type": "response.completed", "response": {"status": "completed"}})
            if finish
            else b""
        )
    if protocol == "gemini":
        result = frame(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "hidden", "thought": True}, {"text": "café [1]"}]
                        }
                    }
                ]
            }
        )
        return result + (frame({"candidates": [{"finishReason": "STOP"}]}) if finish else b"")
    result = (
        json.dumps({"message": {"content": "café [1]"}, "done": False}, ensure_ascii=False).encode()
        + b"\n"
    )
    return result + (b'{"done":true,"done_reason":"stop"}\n' if finish else b"")


@pytest.mark.parametrize(
    "backend", ["local", "ollama", "openai", "openrouter", "gemini", "opencode_go"]
)
def test_fragmented_stream_and_request_mapping(
    backend: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret")
    p = profile(backend)
    transport = RecordingTransport(payload(p.protocol))
    answer = "".join(
        Provider(p, transport).stream(
            [Message("system", "instructions"), Message("user", "question")], "session-123"
        )
    )
    assert answer == "café [1]"
    assert transport.closed
    url, headers, body = transport.calls[0]
    if backend == "gemini":
        assert "alt=sse" in url
        assert headers["x-goog-api-key"] == "secret"
        assert "Authorization" not in headers
        assert body["contents"][0]["parts"][0]["text"] == "question"
    if backend == "opencode_go":
        assert headers["x-opencode-session"] == "session-123"
        assert headers["User-Agent"].startswith("searxng-ai-overview/")
    if backend == "openai":
        assert body["store"] is False
        assert body["max_output_tokens"] == p.max_output_tokens


@pytest.mark.parametrize("protocol", ["chat", "responses", "gemini", "ollama", "anthropic"])
def test_premature_eof_is_never_success(protocol: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret")
    backend = protocol if protocol in {"gemini", "ollama"} else "local"
    transport = RecordingTransport(payload(protocol, finish=False))
    with pytest.raises(OverviewError, match="disconnected"):
        list(Provider(profile(backend, protocol), transport).stream([Message("user", "q")], "s"))
    assert transport.closed


def test_cancel_closes_transport() -> None:
    transport = RecordingTransport(payload("chat"))
    stream = Provider(profile(), transport).stream([Message("user", "q")], "s")
    assert next(stream) == "café [1]"
    stream.close()
    assert transport.closed


def test_go_anthropic_request_and_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret")
    transport = RecordingTransport(payload("anthropic"))
    p = profile("opencode_go", "anthropic")
    answer = "".join(
        Provider(p, transport).stream(
            [Message("system", "instructions"), Message("user", "q")], "session"
        )
    )
    assert answer == "café [1]"
    url, headers, body = transport.calls[0]
    assert url.endswith("/messages")
    assert headers["x-api-key"] == "secret"
    assert headers["x-opencode-session"] == "session"
    assert body["system"] == "instructions"
    assert body["messages"] == [{"role": "user", "content": "q"}]
    broken = RecordingTransport(frame({"type": "message_stop"}))
    with pytest.raises(OverviewError):
        list(Provider(p, broken).stream([Message("user", "q")], "session"))


def test_multiline_sse_and_oversize() -> None:
    assert list(sse([b": heartbeat\n", b"data: first\ndata: second\n\n"])) == ["first\nsecond"]
    with pytest.raises(OverviewError):
        list(sse([b"data: " + b"a" * 300000]))


@pytest.mark.parametrize(
    "data",
    [
        frame({"choices": [{"delta": {}, "finish_reason": "length"}]}),
        frame({"error": {"message": "sensitive upstream body"}}),
        b"data: not-json\n\n",
        b"data: [DONE]\n\n",
    ],
)
def test_invalid_or_truncated_provider_response(data: bytes) -> None:
    with pytest.raises(OverviewError) as caught:
        list(Provider(profile(), RecordingTransport(data)).stream([Message("user", "q")], "s"))
    assert "sensitive" not in str(caught.value)


def test_http_transport_timeout_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def fail(*args: Any, **kwargs: Any) -> None:
        raise httpx.ReadTimeout("secret upstream URL")

    monkeypatch.setattr(httpx.Client, "stream", fail)
    with pytest.raises(OverviewError) as caught:
        with HTTPXTransport().stream("http://localhost", {}, {}, profile()):
            pass
    assert caught.value.code == "timeout"
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("mode", ["enabled", "disabled"])
def test_chat_thinking_control_reaches_provider(mode: str) -> None:
    config = Config.from_dict(
        {
            "default_profile": "test",
            "profiles": {
                "test": {
                    "backend": "local",
                    "model": "deepseek-v4-flash",
                    "options": {"thinking": {"type": mode}},
                }
            },
        }
    )
    transport = RecordingTransport(payload("chat"))
    p = config.profiles["test"]
    assert "".join(Provider(p, transport).stream([Message("user", "q")], "s")) == "café [1]"
    assert transport.calls[0][2]["thinking"] == {"type": mode}


@pytest.mark.parametrize("thinking", [False, None, {}, {"type": "auto"}, {"type": []}])
def test_invalid_chat_thinking_control(thinking: Any) -> None:
    with pytest.raises(ValueError, match="Chat thinking"):
        Config.from_dict(
            {
                "default_profile": "test",
                "profiles": {
                    "test": {
                        "backend": "local",
                        "model": "test",
                        "options": {"thinking": thinking},
                    }
                },
            }
        )


def test_http_transport_caps_io_timeout_to_remaining_turn_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    monkeypatch.setattr("ai_overview.providers.transport.time.monotonic", lambda: 100.0)
    observed: list[httpx.Timeout] = []

    def fail(client: httpx.Client, *args: Any, **kwargs: Any) -> None:
        observed.append(client.timeout)
        raise httpx.ReadTimeout("upstream details")

    monkeypatch.setattr(httpx.Client, "stream", fail)
    with pytest.raises(OverviewError) as caught:
        with HTTPXTransport().stream("http://localhost", {}, {}, profile(), deadline=102.5):
            pass
    assert caught.value.code == "timeout"
    assert observed[0].read == observed[0].connect == 2.5
    with pytest.raises(OverviewError):
        with HTTPXTransport().stream("http://localhost", {}, {}, profile(), deadline=100):
            pass
    assert len(observed) == 1

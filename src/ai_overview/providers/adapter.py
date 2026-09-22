from collections.abc import Generator
from dataclasses import asdict, dataclass
from typing import Any, Optional
from urllib.parse import quote

from ..config import Profile
from ..errors import OverviewError
from ..models import Message
from .parsing import json_object, lines, sse
from .transport import Transport, bounded


@dataclass(frozen=True, slots=True)
class Delta:
    text: str = ""
    done: bool = False


class Provider:
    def __init__(self, profile: Profile, transport: Transport) -> None:
        self.profile = profile
        self.transport = transport

    def request(
        self,
        messages: list[Message],
        session: str,
        max_tokens: Optional[int] = None,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        p = self.profile
        if p.backend not in {"ollama", "local"} and not p.api_key:
            raise OverviewError("configuration", "The selected provider needs an API key.")
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "searxng-ai-overview/0.1.0",
        }
        headers.update(p.headers)
        if p.api_key:
            headers["Authorization"] = f"Bearer {p.api_key}"
        if p.backend == "opencode_go":
            headers["x-opencode-session"] = session
        limit = max_tokens or p.max_output_tokens
        url = p.endpoint
        body: dict[str, Any]
        if p.protocol == "chat":
            body = {
                "model": p.model,
                "messages": [asdict(m) for m in messages],
                "stream": True,
                "max_tokens": limit,
                **p.options,
            }
        elif p.protocol == "responses":
            body = {
                "model": p.model,
                "input": [asdict(m) for m in messages],
                "stream": True,
                "max_output_tokens": limit,
                "store": False,
                **p.options,
            }
        elif p.protocol == "ollama":
            body = {
                "model": p.model,
                "messages": [asdict(m) for m in messages],
                "stream": True,
                "options": {k: v for k, v in p.options.items() if k != "think"},
            }
            body["options"]["num_predict"] = limit
            if "think" in p.options:
                body["think"] = p.options["think"]
        elif p.protocol == "anthropic":
            headers.pop("Authorization", None)
            headers["x-api-key"] = p.api_key
            headers["anthropic-version"] = "2023-06-01"
            body = {
                "model": p.model,
                "stream": True,
                "max_tokens": limit,
                "system": "\n\n".join(m.content for m in messages if m.role == "system"),
                "messages": [asdict(m) for m in messages if m.role != "system"],
                **p.options,
            }
        else:
            headers.pop("Authorization", None)
            headers["x-goog-api-key"] = p.api_key
            model = quote(p.model.removeprefix("models/"), safe="")
            url = f"{p.endpoint.rstrip('/')}/models/{model}:streamGenerateContent?alt=sse"
            body = {
                "systemInstruction": {
                    "parts": [
                        {"text": "\n\n".join(m.content for m in messages if m.role == "system")}
                    ]
                },
                "contents": [
                    {
                        "role": "model" if m.role == "assistant" else "user",
                        "parts": [{"text": m.content}],
                    }
                    for m in messages
                    if m.role != "system"
                ],
                "generationConfig": {"maxOutputTokens": limit, **p.options},
            }
        return url, headers, body

    def stream(
        self,
        messages: list[Message],
        session: str,
        max_tokens: Optional[int] = None,
        *,
        deadline: Optional[float] = None,
    ) -> Generator[str, None, None]:
        url, headers, body = self.request(messages, session, max_tokens)
        protocol = self.profile.protocol
        byte_count = 0
        anthropic_finished = False
        with self.transport.stream(url, headers, body, self.profile, deadline=deadline) as chunks:
            if deadline is not None:
                chunks = bounded(chunks, deadline)
            frames = lines(chunks) if protocol == "ollama" else sse(chunks)
            for frame in frames:
                if not frame.strip():
                    continue
                if frame == "[DONE]":
                    # Successful finish metadata is required before this sentinel.
                    raise OverviewError(
                        "interrupted", "The provider ended without a completion status."
                    )
                value = json_object(frame)
                if protocol == "anthropic":
                    if value.get("type") == "message_delta":
                        reason = value.get("delta", {}).get("stop_reason")
                        _finish(reason, {"end_turn", "stop_sequence"})
                        anthropic_finished = reason in {"end_turn", "stop_sequence"}
                    if value.get("type") == "message_stop" and not anthropic_finished:
                        raise OverviewError(
                            "interrupted", "The provider ended without a completion status."
                        )
                try:
                    delta = self._decode(value)
                except (KeyError, TypeError, IndexError, AttributeError):
                    raise OverviewError(
                        "invalid_stream", "The provider returned an invalid event."
                    ) from None
                if delta.text:
                    if not isinstance(delta.text, str):
                        raise OverviewError("invalid_stream", "The provider returned invalid text.")
                    byte_count += len(delta.text.encode())
                    if byte_count > self.profile.max_output_bytes:
                        raise OverviewError(
                            "output_limit",
                            "The answer reached its size limit. Try a narrower question.",
                        )
                    yield delta.text
                if delta.done:
                    return
        raise OverviewError(
            "interrupted", "The provider disconnected before completing the answer."
        )

    def _decode(self, value: dict[str, Any]) -> Delta:
        protocol = self.profile.protocol
        if protocol == "anthropic":
            kind = value.get("type")
            if kind == "content_block_delta" and value.get("delta", {}).get("type") == "text_delta":
                return Delta(value["delta"]["text"])
            if (
                kind == "content_block_start"
                and value.get("content_block", {}).get("type") == "text"
            ):
                return Delta(value["content_block"].get("text", ""))
            return Delta(done=kind == "message_stop")
        if protocol == "chat":
            choices = value.get("choices", [])
            if not choices:
                return Delta()
            choice = choices[0]
            finish = choice.get("finish_reason")
            _finish(finish, {"stop"})
            return Delta(choice.get("delta", {}).get("content") or "", finish == "stop")
        if protocol == "responses":
            kind = value.get("type", "")
            if kind == "response.output_text.delta":
                return Delta(value["delta"])
            if kind in {"response.failed", "error", "response.incomplete"}:
                raise OverviewError(
                    "incomplete", "The provider could not finish the answer. Try again."
                )
            if kind.startswith("response.refusal"):
                raise OverviewError("refused", "The provider declined this request.")
            if kind == "response.completed":
                status = value.get("response", {}).get("status")
                if status != "completed":
                    raise OverviewError("incomplete", "The provider did not complete the answer.")
                return Delta(done=True)
            return Delta()
        if protocol == "ollama":
            finish = value.get("done_reason")
            _finish(finish, {"stop"})
            return Delta(value.get("message", {}).get("content", ""), value.get("done") is True)
        if value.get("promptFeedback", {}).get("blockReason"):
            raise OverviewError("refused", "The provider declined this request.")
        candidates = value.get("candidates", [])
        if not candidates:
            return Delta()
        candidate = candidates[0]
        finish = candidate.get("finishReason")
        _finish(finish, {"STOP"})
        text = "".join(
            part.get("text", "")
            for part in candidate.get("content", {}).get("parts", [])
            if not part.get("thought")
        )
        return Delta(text, finish == "STOP")


def _finish(reason: Optional[str], success: set[str]) -> None:
    if reason and reason not in success:
        if reason in {"length", "MAX_TOKENS", "max_tokens"}:
            raise OverviewError(
                "output_limit", "The model reached its output limit before finishing."
            )
        raise OverviewError("incomplete", "The provider stopped before completing the answer.")

"""One adapter per wire protocol: options, request shape, framing, and decoding."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import quote

from ..errors import OverviewError
from ..thinking import thinking_budget
from .parsing import lines, sse

if TYPE_CHECKING:
    from ..config import Profile
    from ..models import Message


@dataclass(frozen=True, slots=True)
class Delta:
    text: str = ""
    done: bool = False


class ProtocolAdapter:
    name: str
    # Extra request fields a profile may set in `options`.
    options: frozenset[str]
    # Options tied to the configured model, dropped when a selection changes it.
    model_options: frozenset[str] = frozenset()
    # Path under an OpenCode Go root; None when Go does not serve this protocol.
    go_suffix: Optional[str] = None

    def validate_options(self, options: dict[str, Any]) -> None:
        """Raise ValueError for option values this protocol cannot send."""

    def authorize(self, headers: dict[str, str], api_key: str) -> None:
        """Add this protocol's credentials to the request headers."""
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

    def request(
        self, profile: Profile, messages: list[Message], limit: int
    ) -> tuple[str, dict[str, Any]]:
        """Return the URL and JSON body for one streamed generation."""
        raise NotImplementedError

    def frames(self, chunks: Iterable[bytes]) -> Iterator[str]:
        return sse(chunks)

    def decoder(self) -> Callable[[dict[str, Any]], Delta]:
        """Return a decoder for one response; it may track state across events."""
        return self.decode

    def decode(self, value: dict[str, Any]) -> Delta:
        raise NotImplementedError


class Chat(ProtocolAdapter):
    name = "chat"
    options = frozenset({"temperature", "top_p", "reasoning_effort", "thinking"})
    # Thinking payloads are model-specific, even across chat endpoints.
    model_options = frozenset({"thinking"})
    go_suffix = "chat/completions"

    def validate_options(self, options: dict[str, Any]) -> None:
        if "thinking" in options:
            thinking = options["thinking"]
            if (
                not isinstance(thinking, dict)
                or set(thinking) != {"type"}
                or thinking["type"] not in ("enabled", "disabled")
            ):
                raise ValueError("Chat thinking must contain type: enabled or disabled")

    def request(
        self, profile: Profile, messages: list[Message], limit: int
    ) -> tuple[str, dict[str, Any]]:
        return profile.endpoint, {
            "model": profile.model,
            "messages": [asdict(m) for m in messages],
            "stream": True,
            "max_tokens": limit,
            **profile.options,
        }

    def decode(self, value: dict[str, Any]) -> Delta:
        choices = value.get("choices", [])
        if not choices:
            return Delta()
        choice = choices[0]
        finish = choice.get("finish_reason")
        _finish(finish, {"stop"})
        return Delta(choice.get("delta", {}).get("content") or "", finish == "stop")


class Responses(ProtocolAdapter):
    name = "responses"
    options = frozenset({"temperature", "top_p", "reasoning"})
    go_suffix = "responses"

    def request(
        self, profile: Profile, messages: list[Message], limit: int
    ) -> tuple[str, dict[str, Any]]:
        return profile.endpoint, {
            "model": profile.model,
            "input": [asdict(m) for m in messages],
            "stream": True,
            "max_output_tokens": limit,
            "store": False,
            **profile.options,
        }

    def decode(self, value: dict[str, Any]) -> Delta:
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


class Anthropic(ProtocolAdapter):
    name = "anthropic"
    options = frozenset({"temperature", "top_p", "thinking"})
    model_options = frozenset({"thinking"})
    go_suffix = "messages"

    def authorize(self, headers: dict[str, str], api_key: str) -> None:
        # A configured Authorization header belongs to bearer protocols only.
        headers.pop("Authorization", None)
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"

    def request(
        self, profile: Profile, messages: list[Message], limit: int
    ) -> tuple[str, dict[str, Any]]:
        return profile.endpoint, {
            "model": profile.model,
            "stream": True,
            # Thinking spends from max_tokens, so its budget comes on top of the answer's.
            "max_tokens": limit + thinking_budget(profile.options),
            "system": "\n\n".join(m.content for m in messages if m.role == "system"),
            "messages": [asdict(m) for m in messages if m.role != "system"],
            **profile.options,
        }

    def decoder(self) -> Callable[[dict[str, Any]], Delta]:
        finished = False

        def decode(value: dict[str, Any]) -> Delta:
            nonlocal finished
            if value.get("type") == "message_delta":
                reason = value.get("delta", {}).get("stop_reason")
                _finish(reason, {"end_turn", "stop_sequence"})
                finished = reason in {"end_turn", "stop_sequence"}
            if value.get("type") == "message_stop" and not finished:
                raise OverviewError(
                    "interrupted", "The provider ended without a completion status."
                )
            return self.decode(value)

        return decode

    def decode(self, value: dict[str, Any]) -> Delta:
        kind = value.get("type")
        if kind == "content_block_delta" and value.get("delta", {}).get("type") == "text_delta":
            return Delta(value["delta"]["text"])
        if kind == "content_block_start" and value.get("content_block", {}).get("type") == "text":
            return Delta(value["content_block"].get("text", ""))
        return Delta(done=kind == "message_stop")


class Gemini(ProtocolAdapter):
    name = "gemini"
    options = frozenset({"temperature", "topP", "thinkingConfig"})

    def authorize(self, headers: dict[str, str], api_key: str) -> None:
        headers.pop("Authorization", None)
        headers["x-goog-api-key"] = api_key

    def request(
        self, profile: Profile, messages: list[Message], limit: int
    ) -> tuple[str, dict[str, Any]]:
        model = quote(profile.model.removeprefix("models/"), safe="")
        url = f"{profile.endpoint.rstrip('/')}/models/{model}:streamGenerateContent?alt=sse"
        return url, {
            "systemInstruction": {
                "parts": [{"text": "\n\n".join(m.content for m in messages if m.role == "system")}]
            },
            "contents": [
                {
                    "role": "model" if m.role == "assistant" else "user",
                    "parts": [{"text": m.content}],
                }
                for m in messages
                if m.role != "system"
            ],
            "generationConfig": {
                "maxOutputTokens": limit + thinking_budget(profile.options),
                **profile.options,
            },
        }

    def decode(self, value: dict[str, Any]) -> Delta:
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


class Ollama(ProtocolAdapter):
    name = "ollama"
    options = frozenset({"temperature", "top_p", "num_ctx", "think"})

    def validate_options(self, options: dict[str, Any]) -> None:
        if "think" in options and type(options["think"]) is not bool:
            raise ValueError("Ollama think must be a boolean")

    def request(
        self, profile: Profile, messages: list[Message], limit: int
    ) -> tuple[str, dict[str, Any]]:
        # `think` is a top-level field; the rest are model options.
        options = {k: v for k, v in profile.options.items() if k != "think"}
        body: dict[str, Any] = {
            "model": profile.model,
            "messages": [asdict(m) for m in messages],
            "stream": True,
            "options": {**options, "num_predict": limit},
        }
        if "think" in profile.options:
            body["think"] = profile.options["think"]
        return profile.endpoint, body

    def frames(self, chunks: Iterable[bytes]) -> Iterator[str]:
        return lines(chunks)

    def decode(self, value: dict[str, Any]) -> Delta:
        finish = value.get("done_reason")
        _finish(finish, {"stop"})
        return Delta(value.get("message", {}).get("content", ""), value.get("done") is True)


PROTOCOLS: dict[str, ProtocolAdapter] = {
    p.name: p for p in (Chat(), Responses(), Anthropic(), Gemini(), Ollama())
}


def _finish(reason: Optional[str], success: set[str]) -> None:
    if reason and reason not in success:
        if reason in {"length", "MAX_TOKENS", "max_tokens"}:
            raise OverviewError(
                "output_limit", "The model reached its output limit before finishing."
            )
        raise OverviewError("incomplete", "The provider stopped before completing the answer.")

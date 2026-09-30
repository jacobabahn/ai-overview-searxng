from collections.abc import Generator
from typing import Any, Optional

from ..config import Profile
from ..errors import OverviewError
from ..models import Message
from .parsing import json_object
from .protocols import PROTOCOLS
from .transport import USER_AGENT, Transport, bounded


class Provider:
    def __init__(self, profile: Profile, transport: Transport) -> None:
        self.profile = profile
        self.protocol = PROTOCOLS[profile.protocol]
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
            "User-Agent": USER_AGENT,
            **p.headers,
        }
        self.protocol.authorize(headers, p.api_key)
        if p.backend == "opencode_go":
            headers["x-opencode-session"] = session
        url, body = self.protocol.request(p, messages, max_tokens or p.max_output_tokens)
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
        decode = self.protocol.decoder()
        byte_count = 0
        with self.transport.stream(url, headers, body, self.profile, deadline=deadline) as chunks:
            if deadline is not None:
                chunks = bounded(chunks, deadline)
            for frame in self.protocol.frames(chunks):
                if not frame.strip():
                    continue
                if frame == "[DONE]":
                    # Successful finish metadata is required before this sentinel.
                    raise OverviewError(
                        "interrupted", "The provider ended without a completion status."
                    )
                value = json_object(frame)
                try:
                    delta = decode(value)
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

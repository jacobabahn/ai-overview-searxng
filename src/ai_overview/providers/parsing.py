"""Bounded parsers independent of HTTP chunk boundaries."""

import codecs
import json
from collections.abc import Iterable, Iterator
from typing import Any

from ..errors import OverviewError

MAX_FRAME = 262144
MAX_STREAM = 4194304


def lines(chunks: Iterable[bytes]) -> Iterator[str]:
    decoder = codecs.getincrementaldecoder("utf-8")()
    buffer = ""
    size = 0
    try:
        for chunk in chunks:
            size += len(chunk)
            if size > MAX_STREAM:
                raise OverviewError(
                    "stream_limit", "The provider response exceeded its size limit."
                )
            buffer += decoder.decode(chunk)
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if len(line) > MAX_FRAME:
                    raise OverviewError("invalid_stream", "The provider sent an oversized event.")
                yield line.rstrip("\r")
            if len(buffer) > MAX_FRAME:
                raise OverviewError("invalid_stream", "The provider sent an oversized event.")
        buffer += decoder.decode(b"", final=True)
        if buffer:
            yield buffer.rstrip("\r")
    except UnicodeError:
        raise OverviewError("invalid_stream", "The provider returned invalid text.") from None


def sse(chunks: Iterable[bytes]) -> Iterator[str]:
    data = []
    size = 0
    for line in lines(chunks):
        if not line:
            if data:
                yield "\n".join(data)
            data, size = [], 0
        elif line.startswith("data:"):
            value = line[5:]
            value = value[1:] if value.startswith(" ") else value
            size += len(value)
            if size > MAX_FRAME:
                raise OverviewError("invalid_stream", "The provider sent an oversized event.")
            data.append(value)
    # An incomplete SSE frame is not a complete provider message.
    if data:
        raise OverviewError(
            "interrupted", "The provider disconnected before finishing its response."
        )


def json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        raise OverviewError(
            "invalid_stream", "The provider returned an invalid response."
        ) from None
    if not isinstance(value, dict):
        raise OverviewError("invalid_stream", "The provider returned an invalid response.")
    if value.get("error"):
        raise OverviewError("provider_error", "The provider could not complete this request.")
    return value

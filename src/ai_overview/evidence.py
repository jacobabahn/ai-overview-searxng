import html
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, replace
from html.parser import HTMLParser
from typing import Any, Optional, Protocol
from urllib.parse import urlsplit, urlunsplit

from .models import Source


class SnippetResult(Protocol):
    url: str
    title: str
    content: str


def result_field(result: Mapping[str, Any] | SnippetResult, name: str) -> Any:
    return result.get(name) if isinstance(result, Mapping) else getattr(result, name, None)


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain(value: Any, limit: int = 3000) -> str:
    parser = TextExtractor()
    parser.feed(str(value or "")[: limit * 4])
    return " ".join(html.unescape(" ".join(parser.parts)).split())[:limit]


def safe_url(value: Any) -> Optional[str]:
    if not isinstance(value, str) or len(value) > 2048:
        return None
    if any(ord(c) < 33 for c in value) or "\\" in value:
        return None
    try:
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            return None
        _ = url.port
        return urlunsplit((url.scheme, url.netloc, url.path, url.query, ""))
    except ValueError:
        return None


def encoded_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def build_sources(
    results: Iterable[Mapping[str, Any] | SnippetResult],
    max_sources: int = 8,
    budget: int = 12000,
) -> tuple[Source, ...]:
    sources: list[Source] = []
    seen = set()
    for result in results:
        url = safe_url(result_field(result, "url"))
        if not url or url in seen:
            continue
        snippet = plain(result_field(result, "content"))
        # A title alone is not evidence for a factual synthesis.
        if not snippet:
            continue
        source = Source(
            id=len(sources) + 1,
            url=url,
            title=plain(result_field(result, "title"), 300) or urlsplit(url).hostname or url,
            snippet=snippet,
        )
        while source.snippet and encoded_size([asdict(s) for s in [*sources, source]]) > budget:
            source = replace(source, snippet=source.snippet[:-100])
        if not source.snippet:
            continue
        sources.append(source)
        seen.add(url)
        if len(sources) == max_sources:
            break
    return tuple(sources)


def eligible(
    query: str,
    page: int = 1,
    categories: Iterable[str] = ("general",),
    output_format: str = "html",
) -> bool:
    return (
        isinstance(query, str)
        and query.strip().endswith("?")
        and len(query) <= 2000
        and page == 1
        and output_format == "html"
        and "general" in (categories or ("general",))
    )

"""Offline search results for the real SearXNG integration test."""

from typing import Any

from searx.result_types import EngineResults  # ty: ignore[unresolved-import]

engine_type = "offline"
categories = ["general"]
disabled = False


def search(query: str, params: dict[str, Any]) -> EngineResults:
    res = EngineResults()
    if "empty" in query:
        return res
    res.add(
        res.types.MainResult(
            url="https://example.org/sky",
            title="Why the sky is blue",
            content="Air scatters blue wavelengths of sunlight more strongly than red wavelengths.",
        )
    )
    res.add(
        res.types.MainResult(
            url="https://example.org/sunset",
            title="Sunsets",
            content="Sunlight travels through more atmosphere at sunset, scattering away more blue light.",
        )
    )
    if "stacked" in query:
        res.add(
            res.types.Answer(
                answer="Seattle University is a private Jesuit university in Seattle, Washington.",
                url="https://en.wikipedia.org/wiki/Seattle_University",
            )
        )
    return res

"""Offline search results for the real SearXNG integration test."""

from typing import Any

engine_type = "offline"
categories = ["general"]
disabled = False


def search(query: str, params: dict[str, Any]) -> list[dict[str, str]]:
    if "empty" in query:
        return []
    results = [
        {
            "url": "https://example.org/sky",
            "title": "Why the sky is blue",
            "content": "Air scatters blue wavelengths of sunlight more strongly than red wavelengths.",
        },
        {
            "url": "https://example.org/sunset",
            "title": "Sunsets",
            "content": "Sunlight travels through more atmosphere at sunset, scattering away more blue light.",
        },
    ]
    if "stacked" in query:
        results.append(
            {
                "answer": "Seattle University is a private Jesuit university in Seattle, Washington.",
                "url": "https://en.wikipedia.org/wiki/Seattle_University",
            }
        )
    return results

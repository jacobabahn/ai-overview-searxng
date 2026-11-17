"""One offline result, so the engine's score per result is exactly 1 per search."""

from typing import Any

engine_type = "offline"
categories = ["general"]
disabled = False


def search(query: str, params: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "url": "https://example.org/score",
            "title": "Score fixture",
            "content": "A single result whose score is counted once per search.",
        }
    ]

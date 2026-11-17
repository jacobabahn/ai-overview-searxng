"""The overview plugin must leave SearXNG's result container open in post_search.

SearXNG closes the container once, after every plugin's post_search. Closing it
earlier drops answers from plugins that run later and adds each engine's score
counters twice. Run against compose.test.yml.
"""

import re
import time

import httpx

BASE = "http://127.0.0.1:8899"
LATE_ANSWER = "Answer from the plugin that runs after the overview."


def wait_ready() -> None:
    deadline = time.monotonic() + 30
    while True:
        try:
            if httpx.get(f"{BASE}/healthz", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("Test SearXNG did not become ready on port 8899")
        time.sleep(0.2)


def search(query: str, **params: str) -> str:
    response = httpx.get(f"{BASE}/search", params={"q": query, **params}, timeout=20)
    response.raise_for_status()
    return response.text


def score_per_result(engine: str) -> str:
    response = httpx.get(f"{BASE}/stats", params={"engine": engine}, timeout=10)
    response.raise_for_status()
    match = re.search(r'<td class="engine-score">\s*<span>([^<]+)</span>', response.text)
    assert match, "the stats page shows no score for the engine"
    return match.group(1).strip()


def main() -> None:
    wait_ready()

    # The fixture plugin runs after ai_overview; its answer must still be shown,
    # next to the overview panel.
    page = search("why is the sky blue plugin-order?")
    assert 'class="ai-overview' in page, "the overview panel is missing"
    assert LATE_ANSWER in page, "a later plugin's post_search answer was dropped"

    # The score fixture returns one result at position 1, so each search adds a
    # score of 1 for one result: 1.0 per result when counted once, 2.0 when the
    # container is closed twice. Granian runs one worker, so /stats sees every search.
    for _ in range(3):
        page = search("why is the sky blue?", engines="score fixture")
        assert 'class="ai-overview' in page, "the overview panel is missing"
        assert "Score fixture" in page
    score = score_per_result("score fixture")
    assert score == "1.0", f"score counted {score} per result, expected 1.0"
    print("Result container checks passed")


if __name__ == "__main__":
    main()

"""Request limits in the actual SearXNG UI: the notice, and what does not count.

Run against compose.test.yml, whose overview.yml sets `rate_limit.per_reader`.
Granian runs one worker, so the in-memory counters see every request.
"""

import json
import time
from pathlib import Path

import httpx
import yaml
from playwright.sync_api import Page, Request, expect, sync_playwright

BASE = "http://127.0.0.1:8899"
LIMIT = yaml.safe_load(Path(__file__).with_name("overview.yml").read_text())["rate_limit"][
    "per_reader"
]
NOTICE = "You’ve reached the AI Summary limit for now. Try again in about an hour."


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


def search(page: Page, query: str) -> None:
    page.goto(f"{BASE}/search?q={query.replace(' ', '+').replace('?', '%3F')}")
    expect(page.locator(".ai-overview")).to_have_attribute("data-phase", "idle", timeout=20000)


def spend(page: Page, token: str, count: int) -> None:
    """Regenerate a first answer `count` times, with the browser's cookies."""
    for _ in range(count):
        response = page.request.post(
            f"{BASE}/ai-overview/stream",
            data=json.dumps({"token": token, "fresh": True}),
            headers={"Content-Type": "application/json"},
        )
        assert response.ok and "event: done" in response.text(), response.text()[-300:]


def main() -> None:
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    wait_ready()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        panel = page.locator(".ai-overview")
        status = panel.locator(".ai-status")
        # The panel drops its token from the page once mounted; keep the one it sends.
        tokens: list[str] = []

        def record(request: Request) -> None:
            if request.url.endswith("/ai-overview/stream"):
                tokens.append((request.post_data_json or {})["token"])

        page.on("request", record)

        search(page, "why is the sky blue?")
        cookie = next(c for c in page.context.cookies() if c["name"] == "ai_overview_reader")
        assert cookie["httpOnly"] and cookie["path"] == "/", cookie
        expect(panel.locator(".ai-answer")).to_contain_text("scatters blue light")
        spend(page, tokens[0], LIMIT - 1)

        # The reader's next follow-up is refused before any work, with a quiet notice.
        panel.get_by_role("textbox").fill("What about sunsets?")
        panel.get_by_role("textbox").press("Enter")
        expect(status).to_have_text(NOTICE)
        expect(status).to_have_attribute("data-tone", "limit")
        expect(panel.locator(".ai-retry")).to_be_hidden()
        expect(panel).to_have_attribute("data-phase", "idle")
        # The question stays in the composer, to ask again later.
        expect(panel.get_by_role("textbox")).to_have_value("What about sunsets?")
        expect(page.locator("#urls .result")).to_have_count(2)
        for scheme in ("light", "dark"):
            page.emulate_media(color_scheme=scheme)
            page.screenshot(
                path=str(output / f"limit-follow-up-{scheme}.png"), animations="disabled"
            )
        page.emulate_media(color_scheme="light")

        # A reload replays the cached first answer, which costs nothing.
        search(page, "why is the sky blue?")
        expect(panel.locator(".ai-answer")).to_contain_text("scatters blue light")
        expect(status).to_be_hidden()

        # A new search needs a new generation: the panel says so, results are untouched.
        search(page, "why is the sea blue?")
        expect(status).to_have_text(NOTICE)
        expect(panel.locator(".ai-retry")).to_be_hidden()
        expect(page.locator("#urls .result")).to_have_count(2)
        for scheme in ("light", "dark"):
            page.emulate_media(color_scheme=scheme)
            page.screenshot(path=str(output / f"limit-first-{scheme}.png"), animations="disabled")
        panel.get_by_role("button", name="Collapse overview").click()
        expect(panel.locator(".ai-collapsed-preview")).to_have_text(NOTICE)

        # Another browser has its own allowance.
        other = browser.new_page()
        search(other, "why is the sea blue?")
        expect(other.locator(".ai-overview .ai-answer")).to_contain_text("scatters blue light")
        assert not errors, errors
        browser.close()
    print("Limit checks passed: notice, no retry, cache hits free, per-browser allowance.")


if __name__ == "__main__":
    main()

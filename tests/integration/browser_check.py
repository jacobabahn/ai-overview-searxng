"""Run against compose.test.yml: uv run python tests/integration/browser_check.py."""

import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright


def main() -> None:
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    deadline = time.monotonic() + 30
    while True:
        try:
            if httpx.get("http://127.0.0.1:8899/healthz", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("Test SearXNG did not become ready on port 8899")
        time.sleep(0.2)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8899/search?q=why+is+the+sky+blue%3F")
        panel = page.locator(".ai-overview")
        expect(panel).to_be_visible()
        expect(panel.locator(".ai-status")).to_have_text(
            "Check the sources for details.", timeout=20000
        )
        expect(panel.locator(".ai-answer a")).to_have_count(2)
        expect(page.locator("#urls .result")).to_have_count(2)
        first_href = panel.locator(".ai-answer a").first.get_attribute("href")
        panel.get_by_label("Ask a follow-up").fill("Why is sunset different?")
        panel.get_by_role("button", name="Ask", exact=True).click()
        expect(panel.locator(".ai-answer")).to_have_count(2)
        expect(panel.locator(".ai-status")).to_have_text(
            "Check the sources for details.", timeout=20000
        )
        assert panel.locator(".ai-answer a").first.get_attribute("href") == first_href
        picker = panel.get_by_label("Overview model")
        expect(picker).to_be_hidden()
        panel.get_by_role("button", name="Settings", exact=True).click()
        expect(picker).to_be_visible()
        expect(picker).to_be_enabled()
        target = picker.locator("option", has_text="go-fixture / glm-5.2").get_attribute("value")
        assert target is not None
        picker.select_option(target)
        expect(panel.locator(".ai-answer")).to_have_count(1)
        expect(panel.locator(".ai-status")).to_have_text(
            "Check the sources for details.", timeout=20000
        )
        expect(picker.locator("option:checked")).to_have_text("go-fixture / glm-5.2")
        expect(picker).to_be_hidden()
        expect(picker.locator("option", has_text="unknown-model")).to_have_attribute("disabled", "")
        page.reload()
        expect(panel.locator(".ai-status")).to_have_text(
            "Check the sources for details.", timeout=20000
        )
        expect(picker.locator("option:checked")).to_have_text("go-fixture / glm-5.2")
        page.screenshot(path=str(output / "overview-desktop.png"), full_page=True)
        panel.get_by_role("button", name="Collapse").click()
        expect(panel.locator(".ai-content")).to_be_hidden()
        panel.get_by_role("button", name="Expand").click()

        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(output / "overview-mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.emulate_media(color_scheme="dark")
        page.screenshot(path=str(output / "overview-dark.png"), full_page=True)
        page.emulate_media(color_scheme="light")

        # Model text is always text, and unknown citation IDs never become links.
        assert page.evaluate("""async () => {
          const {renderCitations} = await import('/ai-overview/static/overview.js');
          const box = document.createElement('div');
          renderCitations(box, '<img src=x onerror=alert(1)> [1] [99]',
            [{id:1, url:'https://example.com', title:'Source'}]);
          return box.querySelectorAll('img').length === 0 &&
            box.querySelectorAll('a').length === 1 && box.textContent.includes('[99]');
        }""")

        page.goto("http://127.0.0.1:8899/search?q=why+is+the+sky+blue")
        expect(page.locator(".ai-overview")).to_have_count(0)
        page.goto("http://127.0.0.1:8899/search?q=empty%3F")
        expect(page.locator(".ai-status")).to_contain_text(
            "not enough search snippets", timeout=15000
        )
        page.goto("http://127.0.0.1:8899/search?q=fail-stream%3F")
        expect(page.locator(".ai-status")).to_contain_text("usage limit", timeout=15000)
        expect(page.get_by_role("button", name="Retry")).to_be_visible()

        page.goto("http://127.0.0.1:8899/search?q=slow-stream%3F")
        expect(page.locator(".ai-answer")).to_contain_text("sky", timeout=15000)
        page.get_by_role("button", name="Stop", exact=True).click()
        expect(page.locator(".ai-status")).to_have_text("Stopped. This answer is incomplete.")
        expect(page.get_by_role("button", name="Retry")).to_be_visible()
        assert not errors, errors
        browser.close()
    print(
        "Browser checks passed: generation, citations, fresh-search follow-up, mobile, collapse, XSS, activation, empty/error states, cancellation."
    )


if __name__ == "__main__":
    main()

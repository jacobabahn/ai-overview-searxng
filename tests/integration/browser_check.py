"""Run against compose.test.yml: uv run python tests/integration/browser_check.py."""

import json
import time
from pathlib import Path

import httpx
from playwright.sync_api import Route, expect, sync_playwright


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
        # A stalled catalog must not block the default overview.
        pending_catalog: list[Route] = []
        page.route("**/ai-overview/models", lambda route: pending_catalog.append(route))
        page.goto("http://127.0.0.1:8899/search?q=why+is+the+sky+blue%3F")
        panel = page.locator(".ai-overview")
        expect(panel).to_be_visible()
        expect(panel.locator(".ai-status")).to_have_text("", timeout=20000)
        assert len(pending_catalog) == 1
        expect(panel.get_by_label("Overview model")).to_be_disabled()
        pending_catalog.pop().continue_()
        page.unroute("**/ai-overview/models")
        expect(panel.get_by_label("Overview model")).to_be_enabled()
        expect(panel.locator(".ai-answer a")).to_have_count(2)
        expect(page.locator(".ai-prototype-switcher")).to_have_count(0)
        expect(panel.locator("h2")).to_have_text("✦AI Summary")
        expect(panel.locator(".ai-provenance")).to_have_text("Based on search snippets")
        expect(panel.locator(".ai-more")).to_be_visible()
        expect(panel.locator(".ai-follow-up")).to_be_hidden()
        panel.get_by_role("button", name="More", exact=True).click()
        expect(panel.locator(".ai-follow-up")).to_be_visible()
        panel.get_by_role("button", name="Less", exact=True).click()
        expect(panel.locator(".ai-follow-up")).to_be_hidden()
        panel.get_by_role("button", name="More", exact=True).click()
        panel.get_by_label("Ask a follow-up").focus()
        page.keyboard.press("Escape")
        expect(panel.get_by_label("Ask a follow-up")).to_be_focused()
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        panel.get_by_role("button", name="Copy answer").click()
        expect(panel.locator(".ai-copy-status")).to_have_text("Answer copied.")
        assert "[1]" in page.evaluate("navigator.clipboard.readText()")
        expect(page.locator("#urls .result")).to_have_count(2)
        panel.locator(".ai-answer a").first.click()
        expect(panel.locator(".ai-sources").first).to_have_attribute("open", "")
        expect(panel.locator(".ai-sources li").first).to_be_focused()
        expect(panel.locator(".ai-sources li p").first).not_to_be_empty()
        panel.locator(".ai-sources summary").first.click()
        first_href = panel.locator(".ai-answer a").first.get_attribute("href")
        panel.get_by_label("Ask a follow-up").fill("Why is sunset different?")
        panel.get_by_role("button", name="Ask", exact=True).click()
        expect(panel.locator(".ai-answer")).to_have_count(2)
        expect(panel.locator(".ai-status")).to_have_text("", timeout=20000)
        expect(panel.get_by_label("Ask a follow-up")).to_be_focused()
        assert panel.locator(".ai-answer a").first.get_attribute("href") == first_href
        picker = panel.get_by_label("Overview model")
        expect(picker).to_be_hidden()
        panel.get_by_role("button", name="Overview options", exact=True).click()
        panel.get_by_role("button", name="Model settings", exact=True).click()
        expect(picker).to_be_visible()
        expect(picker).to_be_enabled()
        target = picker.locator("option", has_text="go-fixture / glm-5.2").get_attribute("value")
        assert target is not None
        picker.select_option(target)
        expect(panel.locator(".ai-answer")).to_have_count(2)
        panel.get_by_role("button", name="Use model and restart", exact=True).click()
        expect(panel.locator(".ai-answer")).to_have_count(1)
        expect(panel.locator(".ai-status")).to_have_text("", timeout=20000)
        expect(picker.locator("option:checked")).to_have_text("go-fixture / glm-5.2")
        expect(picker).to_be_hidden()
        expect(picker.locator("option", has_text="unknown-model")).to_have_attribute("disabled", "")
        page.reload()
        expect(panel.locator(".ai-status")).to_have_text("", timeout=20000)
        expect(picker.locator("option:checked")).to_have_text("go-fixture / glm-5.2")
        page.screenshot(path=str(output / "overview-desktop.png"), full_page=True)
        panel.get_by_role("button", name="Collapse overview").click()
        expect(panel.locator(".ai-content")).to_be_hidden()
        expect(panel.locator(".ai-collapsed-preview")).to_contain_text("sky")
        panel.get_by_role("button", name="Overview options").click()
        panel.get_by_role("button", name="Model settings").click()
        expect(panel.locator(".ai-content")).to_be_hidden()
        page.keyboard.press("Escape")
        expect(panel.locator(".ai-model-settings")).to_be_hidden()
        panel.get_by_role("button", name="Expand overview").click()

        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(output / "overview-mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.emulate_media(color_scheme="dark")
        page.screenshot(path=str(output / "overview-dark.png"), full_page=True)
        page.emulate_media(color_scheme="light")
        panel.get_by_role("button", name="Overview options").click()
        panel.get_by_role("button", name="Model settings").click()
        page.screenshot(path=str(output / "overview-settings-mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.keyboard.press("Escape")
        panel.get_by_role("button", name="Overview options").click()
        with page.expect_request(lambda request: request.url.endswith("/stream")):
            panel.get_by_role("button", name="Regenerate overview").click()
        expect(panel.locator(".ai-status")).to_have_text("", timeout=20000)
        expect(panel.locator(".ai-answer")).to_have_count(1)
        expect(panel.locator(".ai-follow-up")).to_be_hidden()
        panel.get_by_role("button", name="More", exact=True).click()
        expect(panel.locator(".ai-follow-up")).to_be_visible()

        # A failed model selection keeps the existing answer and reports the error.
        page.route(
            "**/ai-overview/select",
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body='{"message":"Model settings are temporarily unavailable."}',
            ),
        )
        panel.get_by_role("button", name="Overview options").click()
        panel.get_by_role("button", name="Regenerate overview").click()
        expect(panel.locator(".ai-status")).to_contain_text("temporarily unavailable")
        expect(panel.locator(".ai-answer")).to_have_count(1)
        page.unroute("**/ai-overview/select")

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
        page.get_by_role("button", name="Stop generating", exact=True).click()
        expect(page.locator(".ai-status")).to_have_text("Stopped. This answer is incomplete.")
        expect(page.get_by_role("button", name="Retry")).to_be_visible()
        # Selection and its restart reserve one operation, even if Retry is dispatched
        # programmatically while the selection response is delayed.
        pending_selection: list[Route] = []
        pending_generation: list[Route] = []
        page.route("**/ai-overview/select", lambda route: pending_selection.append(route))
        page.route("**/ai-overview/stream", lambda route: pending_generation.append(route))
        panel.get_by_role("button", name="Overview options").click()
        panel.get_by_role("button", name="Model settings").click()
        expect(picker).to_be_enabled()
        target = picker.locator("option", has_text="fixture / fixture").get_attribute("value")
        assert target is not None
        picker.select_option(target)
        with page.expect_request(lambda request: request.url.endswith("/select")):
            panel.get_by_role("button", name="Use model and restart").click()
        expect(panel.get_by_role("button", name="Retry")).to_be_disabled()
        panel.locator(".ai-retry").evaluate(
            "button => button.dispatchEvent(new MouseEvent('click'))"
        )
        assert not pending_generation
        assert len(pending_selection) == 1
        pending_selection.pop().fulfill(
            content_type="application/json", body='{"token":"selected-search"}'
        )
        expect(panel).to_have_attribute("data-loading", "true")
        # Flush browser tasks before inspecting the routed generation request.
        page.wait_for_function("document.querySelector('.ai-stop').hidden === false")
        assert len(pending_generation) == 1
        generation = pending_generation.pop()
        assert generation.request.post_data_json == {"token": "selected-search"}
        generation.fulfill(
            content_type="text/event-stream",
            body='event: text_delta\ndata: {"text":"Selected model answer"}\n\n'
            'event: done\ndata: {"token":"selected-continuation","can_follow_up":true}\n\n',
        )
        expect(panel.locator(".ai-status")).to_have_text("")
        expect(panel.locator(".ai-answer")).to_have_count(1)
        expect(panel.locator(".ai-answer")).to_have_text("Selected model answer")
        panel.get_by_role("button", name="More", exact=True).click()
        panel.get_by_label("Ask a follow-up").fill("Why?")
        with page.expect_request(lambda request: request.url.endswith("/stream")):
            panel.get_by_role("button", name="Ask", exact=True).click()
        assert len(pending_generation) == 1
        followup = pending_generation.pop()
        assert followup.request.post_data_json == {
            "token": "selected-continuation",
            "question": "Why?",
        }
        followup.fulfill(
            content_type="text/event-stream",
            body='event: done\ndata: {"token":"next","can_follow_up":true}\n\n',
        )
        expect(panel.locator(".ai-status")).to_have_text("")
        page.unroute("**/ai-overview/select")
        page.unroute("**/ai-overview/stream")
        # Long answers disclose on demand and on keyboard focus into citations.
        long_answer = "Air scatters blue light more strongly than red light. " * 20 + "[1]"
        stream = "".join(
            f"event: {name}\ndata: {json.dumps(data)}\n\n"
            for name, data in [
                (
                    "sources",
                    {
                        "sources": [
                            {
                                "id": 1,
                                "url": "https://example.org/sky",
                                "title": "Why the sky is blue",
                                "snippet": "Blue light scatters.",
                            }
                        ]
                    },
                ),
                ("text_delta", {"text": long_answer}),
                ("done", {"token": "fixture", "can_follow_up": True}),
            ]
        )
        page.route(
            "**/ai-overview/stream",
            lambda route: route.fulfill(
                content_type="text/event-stream",
                body=stream,
            ),
        )
        page.goto("http://127.0.0.1:8899/search?q=long-answer%3F")
        expect(panel.locator(".ai-status")).to_have_text("", timeout=20000)
        expect(panel.get_by_role("button", name="More", exact=True)).to_be_visible()
        expect(panel.locator(".ai-follow-up")).to_be_hidden()
        answer = panel.locator(".ai-answer")
        assert answer.evaluate("el => el.scrollHeight > el.clientHeight")
        panel.get_by_role("button", name="More", exact=True).click()
        assert answer.evaluate("el => el.scrollHeight <= el.clientHeight + 1")
        panel.get_by_role("button", name="Less", exact=True).click()
        answer.locator("a").focus()
        expect(panel).to_have_attribute("data-expanded", "false")
        expect(panel.locator(".ai-follow-up")).to_be_hidden()
        assert answer.evaluate("el => el.scrollHeight <= el.clientHeight + 1")
        page.set_viewport_size({"width": 320, "height": 740})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.emulate_media(reduced_motion="reduce")
        panel.get_by_role("button", name="Overview options").click()
        assert (
            panel.locator(".ai-options").evaluate("el => getComputedStyle(el).animationName")
            == "none"
        )
        page.keyboard.press("Escape")
        expect(panel.get_by_role("button", name="Overview options")).to_be_focused()
        assert not errors, errors
        browser.close()
    print(
        "Browser checks passed: generation, citations, fresh-search follow-up, mobile, collapse, XSS, activation, empty/error states, cancellation."
    )


if __name__ == "__main__":
    main()

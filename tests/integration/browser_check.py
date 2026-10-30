"""Run against compose.test.yml: uv run python tests/integration/browser_check.py."""

import json
import re
import time
from pathlib import Path

import httpx
from playwright.sync_api import Page, Request, Route, expect, sync_playwright


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
        expect(panel.locator("h2")).to_have_text("✦AI Summary")
        expect(panel.locator(".ai-provenance")).to_have_text("Based on search snippets")
        expect(panel.locator(".ai-provenance")).to_be_hidden()
        expect(panel.locator(".ai-more")).to_be_hidden()
        expect(panel.locator(".ai-follow-up")).to_be_visible()
        panel.get_by_role("button", name="Copy answer").focus()
        page.keyboard.press("Escape")
        expect(panel.get_by_role("button", name="Copy answer")).to_be_focused()
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        panel.get_by_role("button", name="Copy answer").click()
        expect(panel.locator(".ai-copy-status")).to_have_text("Answer copied.")
        assert "[1]" in page.evaluate("navigator.clipboard.readText()")
        expect(page.locator("#urls .result")).to_have_count(2)
        panel.locator(".ai-answer a").first.click()
        expect(panel.locator(".ai-sources").first).to_have_attribute("open", "")
        expect(panel.locator(".ai-sources .ai-provenance").first).to_be_visible()
        expect(panel.locator(".ai-sources li").first).to_be_focused()
        expect(panel.locator(".ai-sources li p").first).not_to_be_empty()
        panel.locator(".ai-sources summary").first.click()
        first_href = panel.locator(".ai-answer a").first.get_attribute("href")
        composer = panel.get_by_role("textbox", name="Ask a follow-up")
        expect(panel.get_by_role("button", name="Ask", exact=True)).to_be_disabled()
        composer.fill("Why is sunset different?")
        composer.press("Enter")
        expect(composer).to_have_value("")
        expect(panel.locator(".ai-question")).to_have_text("Why is sunset different?")
        expect(panel.locator(".ai-answer")).to_have_count(2)
        expect(panel.locator(".ai-status")).to_have_text("", timeout=20000)
        expect(panel.locator(".ai-follow-up")).to_be_visible()
        expect(composer).to_be_focused()
        expect(panel.get_by_role("button", name="Copy conversation")).to_be_enabled()
        assert panel.locator(".ai-answer a").first.get_attribute("href") == first_href
        panel.get_by_role("button", name="Show less", exact=True).click()
        expect(panel.locator(".ai-turns > article").nth(1)).to_be_hidden()
        panel.get_by_role("button", name="Show conversation", exact=True).click()
        expect(panel.locator(".ai-turns > article").nth(1)).to_be_visible()
        expect(panel.locator(".ai-answer")).to_have_count(2)
        picker = panel.get_by_label("Overview model")
        expect(picker).to_be_hidden()
        panel.get_by_role("button", name="Summary settings", exact=True).click()
        expect(picker).to_be_visible()
        expect(picker).to_be_enabled()
        target = picker.locator("option", has_text="go-fixture / glm-5.2").get_attribute("value")
        assert target is not None
        expect(panel.get_by_role("button", name="Close settings")).to_be_focused()
        expect(panel.locator(".ai-apply-model")).to_be_hidden()
        picker.select_option(target)
        expect(panel.locator(".ai-regenerate")).to_be_hidden()
        page.keyboard.press("Escape")
        expect(panel.get_by_role("button", name="Summary settings")).to_be_focused()
        panel.get_by_role("button", name="Summary settings").click()
        expect(picker.locator("option:checked")).to_have_text("fixture / fixture")
        expect(panel.locator(".ai-apply-model")).to_be_hidden()
        panel.get_by_role("button", name="Close settings").click()
        expect(panel.get_by_role("button", name="Summary settings")).to_be_focused()
        panel.get_by_role("button", name="Summary settings").click()
        panel.locator(".ai-regenerate").focus()
        page.keyboard.press("Tab")
        expect(panel.locator(".ai-options")).to_be_hidden()
        panel.get_by_role("button", name="Summary settings").click()
        panel.locator("h2").click()
        expect(panel.locator(".ai-options")).to_be_hidden()
        panel.get_by_role("button", name="Summary settings").click()
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
        # The model's thinking levels: choosing one restarts with it, and it is remembered.
        panel.get_by_role("button", name="Summary settings").click()
        thinking = panel.get_by_role("combobox", name="Thinking")
        expect(thinking.locator("option")).to_have_text(
            ["Model default", "Off", "Low", "Medium", "High"]
        )
        thinking.select_option("off")
        with page.expect_request(lambda request: request.url.endswith("/select")) as chosen:
            panel.get_by_role("button", name="Apply and restart", exact=True).click()
        assert json.loads(chosen.value.post_data or "{}")["thinking"] == "off"
        expect(panel.locator(".ai-status")).to_have_text("", timeout=20000)
        expect(panel.locator(".ai-current-model")).to_have_text("Current: glm-5.2, thinking off")
        page.reload()
        expect(panel.locator(".ai-status")).to_have_text("", timeout=20000)
        expect(panel.locator(".ai-current-model")).to_have_text("Current: glm-5.2, thinking off")
        page.screenshot(path=str(output / "overview-desktop.png"), full_page=True)
        panel.get_by_role("button", name="Collapse overview").click()
        expect(panel.locator(".ai-content")).to_be_hidden()
        expect(panel.locator(".ai-collapsed-preview")).to_contain_text("sky")
        panel.get_by_role("button", name="Summary settings").click()
        expect(panel.locator(".ai-content")).to_be_hidden()
        page.keyboard.press("Escape")
        expect(panel.locator(".ai-options")).to_be_hidden()
        panel.get_by_role("button", name="Expand overview").click()

        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(output / "overview-mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.emulate_media(color_scheme="dark")
        page.screenshot(path=str(output / "overview-dark.png"), full_page=True)
        page.emulate_media(color_scheme="light")
        panel.get_by_role("button", name="Summary settings").click()
        page.screenshot(path=str(output / "overview-settings-mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.keyboard.press("Escape")
        panel.get_by_role("button", name="Summary settings").click()
        with page.expect_request(lambda request: request.url.endswith("/stream")) as regen:
            panel.get_by_role("button", name="Regenerate overview").click()
        # Regenerate bypasses the answer cache for this browser.
        client = page.evaluate("localStorage.getItem('searxng-ai-overview-client')")
        body = regen.value.post_data_json or {}
        assert body.get("fresh") is True and body.get("client") == client
        expect(panel.locator(".ai-status")).to_have_text("", timeout=20000)
        expect(panel.locator(".ai-answer")).to_have_count(1)
        expect(panel.locator(".ai-follow-up")).to_be_visible()
        expect(panel.locator(".ai-more")).to_be_hidden()

        # A failed model selection keeps the existing answer and reports the error.
        page.route(
            "**/ai-overview/select",
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body='{"message":"Model settings are temporarily unavailable."}',
            ),
        )
        panel.get_by_role("button", name="Summary settings").click()
        panel.get_by_role("button", name="Regenerate overview").click()
        expect(panel.locator(".ai-status")).to_contain_text("temporarily unavailable")
        expect(panel.locator(".ai-answer")).to_have_count(1)
        panel.get_by_role("button", name="Summary settings").click()
        previous = picker.input_value()
        other = picker.locator("option", has_text="fixture / fixture").get_attribute("value")
        assert other is not None
        picker.select_option(other)
        panel.get_by_role("button", name="Use model and restart").click()
        expect(panel.locator(".ai-model-status")).to_contain_text("temporarily unavailable")
        expect(panel.locator(".ai-options")).to_be_visible()
        expect(picker).to_have_value(other)
        expect(panel.locator(".ai-answer")).to_have_count(1)
        expect(panel.locator(".ai-apply-model")).to_be_enabled()
        page.keyboard.press("Escape")
        panel.get_by_role("button", name="Summary settings").click()
        expect(picker).to_have_value(previous)
        page.keyboard.press("Escape")
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
        panel.get_by_role("button", name="Summary settings").click()
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
        assert generation.request.post_data_json == {"token": "selected-search", "client": client}
        generation.fulfill(
            content_type="text/event-stream",
            body='event: text_delta\ndata: {"text":"Selected model answer"}\n\n'
            'event: done\ndata: {"token":"selected-continuation","can_follow_up":true}\n\n',
        )
        expect(panel.locator(".ai-status")).to_have_text("")
        expect(panel.locator(".ai-answer")).to_have_count(1)
        expect(panel.locator(".ai-answer")).to_have_text("Selected model answer")
        expect(panel.locator(".ai-more")).to_be_hidden()
        expect(panel.locator(".ai-follow-up")).to_be_visible()
        with page.expect_request(lambda request: request.url.endswith("/stream")):
            panel.get_by_role("textbox", name="Ask a follow-up").fill("Why?")
            panel.get_by_role("button", name="Ask", exact=True).click()
        # While the follow-up streams, the composer's button stops it.
        expect(
            panel.locator(".ai-follow-up").get_by_role("button", name="Stop generating")
        ).to_be_visible()
        assert len(pending_generation) == 1
        followup = pending_generation.pop()
        assert followup.request.post_data_json == {
            "token": "selected-continuation",
            "question": "Why?",
            "client": client,
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
        expect(panel.get_by_role("button", name="Show full answer", exact=True)).to_be_visible()
        expect(panel.locator(".ai-follow-up")).to_be_hidden()
        answer = panel.locator(".ai-answer")
        assert answer.evaluate("el => el.scrollHeight > el.clientHeight")
        # Measure a paused midpoint: expansion must interpolate without moving the top.
        page.emulate_media(reduced_motion="no-preference")
        dimensions = panel.evaluate("""panel => {
          const turns = panel.querySelector('.ai-turns');
          const before = turns.getBoundingClientRect();
          panel.querySelector('.ai-more').click();
          const animation = turns.getAnimations()[0];
          animation.pause();
          animation.currentTime = 130;
          const middle = turns.getBoundingClientRect();
          return {before: before.height, middle: middle.height,
            full: turns.scrollHeight, topBefore: before.top, topAfter: middle.top};
        }""")
        assert dimensions["before"] < dimensions["middle"] < dimensions["full"]
        assert abs(dimensions["topBefore"] - dimensions["topAfter"]) < 1
        page.screenshot(path=str(output / "overview-expanding.png"), full_page=True)
        panel.locator(".ai-turns").evaluate("el => el.getAnimations()[0].finish()")
        expect(panel.locator(".ai-follow-up")).to_be_visible()
        assert answer.evaluate("el => el.scrollHeight <= el.clientHeight + 1")
        # Rapid reversal leaves one animation and settles at the intended size.
        panel.evaluate("""panel => {
          const button = panel.querySelector('.ai-more');
          button.click(); button.click(); button.click();
        }""")
        expect(panel).to_have_attribute("data-expanded", "false")
        panel.locator(".ai-turns").evaluate(
            "async el => { await Promise.all(el.getAnimations().map(a => a.finished)); }"
        )
        assert answer.evaluate("el => el.scrollHeight > el.clientHeight")
        answer.locator("a").focus()
        expect(panel).to_have_attribute("data-expanded", "false")
        expect(panel.locator(".ai-follow-up")).to_be_hidden()
        assert answer.evaluate("el => el.scrollHeight <= el.clientHeight + 1")
        page.set_viewport_size({"width": 320, "height": 740})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.emulate_media(reduced_motion="reduce")
        panel.get_by_role("button", name="Show full answer", exact=True).click()
        assert panel.locator(".ai-turns").evaluate("el => el.getAnimations().length") == 0
        panel.get_by_role("button", name="Show less", exact=True).click()
        expect(panel.locator(".ai-follow-up")).to_be_hidden()
        panel.get_by_role("button", name="Summary settings").click()
        assert (
            panel.locator(".ai-options").evaluate("el => getComputedStyle(el).animationName")
            == "none"
        )
        page.keyboard.press("Escape")
        expect(panel.get_by_role("button", name="Summary settings")).to_be_focused()
        # A paragraph break on line four must not strand the ellipsis on an empty line.
        paragraph_answer = "First line.\nSecond line.\nThird line.\n\n" + long_answer
        page.unroute("**/ai-overview/stream")
        paragraph_stream = (
            "event: text_delta\ndata: "
            + json.dumps({"text": paragraph_answer})
            + '\n\nevent: done\ndata: {"token":"fixture","can_follow_up":true}\n\n'
        )
        page.route(
            "**/ai-overview/stream",
            lambda route: route.fulfill(content_type="text/event-stream", body=paragraph_stream),
        )
        page.goto("http://127.0.0.1:8899/search?q=paragraph+wrapping%3F")
        expect(panel.locator(".ai-status")).to_have_text("")
        answer = panel.locator(".ai-answer")
        for width in [320, 390, 1280]:
            page.set_viewport_size({"width": width, "height": 900})
            # Check actual glyph positions, not just the white-space CSS declaration.
            last_line_has_text = answer.evaluate(r"""answer => {
              const box = answer.getBoundingClientRect();
              const lineHeight = parseFloat(getComputedStyle(answer).lineHeight);
              const walker = document.createTreeWalker(answer, NodeFilter.SHOW_TEXT);
              let node;
              while ((node = walker.nextNode())) {
                for (let i = 0; i < node.length; i++) {
                  if (/\s/.test(node.textContent[i])) continue;
                  const range = document.createRange();
                  range.setStart(node, i); range.setEnd(node, i + 1);
                  const rect = range.getBoundingClientRect();
                  if (rect.height && rect.bottom <= box.bottom + 1 &&
                      rect.bottom > box.bottom - lineHeight) return true;
                }
              }
              return false;
            }""")
            assert last_line_has_text
        panel.get_by_role("button", name="Show full answer", exact=True).click()
        expect(answer).to_have_text(paragraph_answer)
        assert (
            answer.locator("p").first.evaluate("el => getComputedStyle(el).whiteSpace")
            == "pre-wrap"
        )
        panel.get_by_role("button", name="Show less", exact=True).click()
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(output / "overview-ellipsis-fixed.png"), full_page=True)

        # Instant answers and AI Summary must not share one continuous card.
        page.goto("http://127.0.0.1:8899/search?q=stacked+answers%3F")
        cards = page.locator("#answers > .answer")
        expect(cards).to_have_count(2)
        for width, scheme in [(390, "dark"), (1280, "light")]:
            page.set_viewport_size({"width": width, "height": 900})
            page.emulate_media(color_scheme="dark" if scheme == "dark" else "light")
            geometry = page.locator("#answers").evaluate("""group => {
              const cards = [...group.querySelectorAll(':scope > .answer')];
              const first = cards[0].getBoundingClientRect();
              const second = cards[1].getBoundingClientRect();
              return {gap: second.top - first.bottom,
                background: getComputedStyle(group).backgroundColor,
                radii: cards.map(c => getComputedStyle(c).borderRadius)};
            }""")
            assert geometry["gap"] >= 12
            assert geometry["background"] == "rgba(0, 0, 0, 0)"
            assert geometry["radii"] == ["10px", "10px"]
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(output / f"overview-stacked-{scheme}.png"), full_page=True)
        check_chat_mode(page, output)
        assert not errors, errors
        browser.close()
    print(
        "Browser checks passed: generation, citations, fresh-search follow-up, chat mode, mobile, collapse, XSS, activation, empty/error states, cancellation."
    )


def check_chat_mode(page: Page, output: Path) -> None:
    """The Chat category swaps results for the conversation and back, in page memory."""
    page.unroute("**/ai-overview/stream")
    page.set_viewport_size({"width": 1280, "height": 900})
    page.emulate_media(color_scheme="light", reduced_motion="reduce")
    tab = page.locator("#ai-chat-tab")
    general = page.locator('#categories_container button[name="category_general"]')
    panel = page.locator(".ai-overview")
    composer = panel.get_by_role("textbox", name="Ask a follow-up")
    results = page.locator("#urls")
    page.goto("http://127.0.0.1:8899/search?q=why+is+the+sky+blue%3F")
    expect(tab).to_be_visible()
    expect(panel.locator(".ai-follow-up")).to_be_visible(timeout=20000)
    expect(tab).to_have_attribute("type", "button")
    expect(tab).to_have_attribute("aria-pressed", "false")
    expect(tab.locator(".category_name")).to_have_text("chat")
    expect(page.locator("#categories_container .category_button")).to_have_count(2)
    page.evaluate("window.chatModeMarker = true")
    searches: list[str] = []

    def record_search(request: Request) -> None:
        if "/search" in request.url:
            searches.append(request.url)

    page.on("request", record_search)
    url = page.url
    page.evaluate("window.scrollTo(0, 120)")
    scroll = page.evaluate("window.scrollY")

    def expect_chat() -> None:
        expect(tab).to_have_attribute("aria-pressed", "true")
        expect(tab).to_have_class("category category_button selected")
        expect(general).not_to_have_class("selected")
        for hidden in ["#urls", "#sidebar", ".search_filters"]:
            expect(page.locator(hidden)).to_be_hidden()
        expect(panel.locator(".ai-more-row")).to_be_hidden()
        expect(panel.locator(".ai-collapse")).to_be_hidden()
        expect(panel.locator(".ai-follow-up")).to_be_visible()

    def expect_results() -> None:
        expect(tab).to_have_attribute("aria-pressed", "false")
        expect(general).to_have_class("category category_button selected")
        expect(results).to_be_visible()
        expect(results.locator(".result")).to_have_count(2)
        expect(page.locator(".search_filters")).to_be_visible()
        assert page.url == url and page.evaluate("window.chatModeMarker") is True

    tab.click()
    expect_chat()
    expect(composer).to_be_focused()
    # Wide screens annotate the thread: the search becomes its first question and
    # each turn's sources sit open beside the answer, lit by the citation in use.
    expect(panel.locator(".ai-chat-query")).to_have_text("why is the sky blue?")
    # Citations name their site for tooltips and screen readers.
    expect(panel.locator('.ai-answer a[data-source-id="1"]').first).to_have_attribute(
        "aria-label", re.compile(r"^Source 1, example\.org: ")
    )
    suggestions = panel.get_by_role("list", name="Ask next")
    expect(suggestions.get_by_role("button")).to_have_text(
        ["Why are clouds white?", "Is the sky blue on Mars?"]
    )
    expect(panel.locator(".ai-sources").first).to_have_attribute("open", "")
    panel.locator('.ai-answer a[data-source-id="1"]').first.hover()
    expect(panel.locator('.ai-sources li[data-source-id="1"]').first).to_have_class("ai-chat-cited")
    page.screenshot(path=str(output / "overview-chat-desktop.png"), full_page=True)
    page.emulate_media(color_scheme="dark")
    page.screenshot(path=str(output / "overview-chat-desktop-dark.png"), full_page=True)
    page.emulate_media(color_scheme="light")
    page.keyboard.press("Escape")
    expect_results()
    assert page.evaluate("window.scrollY") == scroll
    expect(panel.locator(".ai-chat-query")).to_have_count(0)
    expect(panel.locator(".ai-sources").first).not_to_have_attribute("open", "")
    expect(panel.locator(".ai-turns > article")).to_have_count(1)

    # A follow-up asked in chat mode survives the return to results.
    tab.click()
    composer.fill("Why is sunset different?")
    composer.press("Enter")
    expect(panel.locator(".ai-answer")).to_have_count(2)
    expect(panel.locator(".ai-status")).to_have_text("", timeout=20000)
    expect(composer).to_be_focused()
    general.click()
    expect_results()
    expect(panel.locator(".ai-turns > article")).to_have_count(2)
    expect(panel.locator(".ai-turns > article").nth(1)).to_be_visible()
    expect(panel.locator(".ai-chat-suggestions")).to_be_hidden()
    # A non-chat history entry remains only for the page itself.
    assert page.evaluate("history.state?.aiOverviewChat") in (None, False)

    # Back leaves chat mode instead of the page; Forward returns to it.
    tab.click()
    expect_chat()
    page.go_back()
    expect_results()
    page.go_forward()
    expect_chat()
    page.go_back()
    expect_results()

    page.set_viewport_size({"width": 390, "height": 844})
    tab.scroll_into_view_if_needed()
    tab.click()
    expect_chat()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path=str(output / "overview-chat-mobile.png"), full_page=True)
    page.emulate_media(color_scheme="dark")
    page.screenshot(path=str(output / "overview-chat-mobile-dark.png"), full_page=True)
    page.emulate_media(color_scheme="light")
    tab.focus()
    page.keyboard.press("Escape")
    expect_results()
    assert not searches, searches
    page.remove_listener("request", record_search)
    page.reload()
    expect(tab).to_be_visible(timeout=20000)
    expect(tab).to_have_attribute("aria-pressed", "false")
    expect(results).to_be_visible()
    # A suggestion asks itself; a search ending in "??" opens straight into chat.
    tab.click()
    expect(suggestions.get_by_role("button")).to_have_count(2)
    # While chatting, suggestions are written alongside the answer and arrive on its
    # stream; asked questions are left out, and no separate request is made.
    asked: list[Request] = []

    def record_ask(request: Request) -> None:
        if "/ai-overview/" in request.url and request.method == "POST":
            asked.append(request)

    page.on("request", record_ask)
    suggestions.get_by_role("button", name="Why are clouds white?").click()
    expect(panel.locator(".ai-question").last).to_have_text("Why are clouds white?")
    expect(panel.locator(".ai-status")).to_have_text("", timeout=20000)
    expect(suggestions.get_by_role("button")).to_have_text(["Is the sky blue on Mars?"])
    page.remove_listener("request", record_ask)
    assert [request.url.rsplit("/", 1)[-1] for request in asked] == ["stream"]
    assert json.loads(asked[0].post_data or "{}")["suggest"] is True
    with page.expect_request(lambda request: request.url.endswith("/stream")) as opened:
        page.goto("http://127.0.0.1:8899/search?q=why+is+the+sky+blue%3F%3F")
    # Already chatting when the first answer is requested, before the crossfade ends.
    assert json.loads(opened.value.post_data or "{}").get("suggest") is True
    expect(tab).to_have_attribute("aria-pressed", "true", timeout=20000)
    expect(panel.locator(".ai-chat-query")).to_have_text("why is the sky blue?")
    expect(results).to_be_hidden()
    # Beside a finished answer, the margin keeps four cited notes and folds the rest;
    # following a folded citation unfolds the list and focuses its note.
    page.set_viewport_size({"width": 1280, "height": 900})
    sources = [
        {"id": i, "url": f"https://example.org/{i}", "title": f"Source {i}", "snippet": "Evidence."}
        for i in range(1, 9)
    ]
    folded = "".join(
        f"event: {name}\ndata: {json.dumps(data)}\n\n"
        for name, data in [
            ("sources", {"sources": sources}),
            ("text_delta", {"text": "Blue [1]. Red [2]. Violet [3]. Dust [4]. Eyes [6]."}),
            ("done", {"token": "fixture", "can_follow_up": True}),
        ]
    )
    page.route(
        "**/ai-overview/stream",
        lambda route: route.fulfill(content_type="text/event-stream", body=folded),
    )
    page.goto("http://127.0.0.1:8899/search?q=folded+sources%3F")
    expect(tab).to_be_visible(timeout=20000)
    tab.click()
    notes = panel.locator(".ai-sources li")
    expect(panel.locator(".ai-chat-more")).to_have_text("4 more sources")
    expect(notes.filter(visible=True)).to_have_count(4)
    # Pointing at a citation or a note highlights it without resizing the margin.
    margin = panel.locator(".ai-sources").first
    height = margin.evaluate("element => element.offsetHeight")
    panel.locator('.ai-answer a[data-source-id="6"]').hover()
    notes.first.hover()
    expect(notes.filter(visible=True)).to_have_count(4)
    assert margin.evaluate("element => element.offsetHeight") == height, (
        "hovering resized the source margin"
    )
    panel.locator('.ai-answer a[data-source-id="6"]').click()
    expect(panel.locator(".ai-chat-more")).to_have_text("Fewer sources")
    expect(notes.filter(visible=True)).to_have_count(8)
    expect(panel.locator('.ai-sources li[data-source-id="6"]')).to_be_focused()
    page.keyboard.press("Escape")
    expect(panel.locator(".ai-chat-more")).to_have_count(0)
    page.unroute("**/ai-overview/stream")
    # Notes fold from the start and appear as the streaming answer first cites them,
    # so finishing the answer never collapses the margin.
    page.add_init_script(
        """
        if (location.search.includes("live+fold")) {
          const original = window.fetch;
          window.fetch = (input, init) => {
            if (!String(input.url ?? input).endsWith("/stream")) return original(input, init);
            const encoder = new TextEncoder();
            const event = (name, data) => encoder.encode(`event: ${name}\\ndata: ${JSON.stringify(data)}\\n\\n`);
            const sources = Array.from({length: 8}, (_, i) => ({
              id: i + 1, url: `https://example.org/${i + 1}`, title: `Source ${i + 1}`, snippet: "Evidence."}));
            const body = new ReadableStream({async start(controller) {
              controller.enqueue(event("sources", {sources}));
              await new Promise(resolve => (window.continueStream = resolve));
              controller.enqueue(event("text_delta", {text: "Eyes [6]."}));
              await new Promise(resolve => (window.continueStream = resolve));
              controller.enqueue(event("text_delta", {text: " Blue [1]. Red [2]. Violet [3]. Dust [4]."}));
              controller.enqueue(event("done", {token: "fixture", can_follow_up: true}));
              controller.close();
            }});
            return Promise.resolve(new Response(body, {headers: {"Content-Type": "text/event-stream"}}));
          };
        }
        """
    )
    page.goto("http://127.0.0.1:8899/search?q=live+fold%3F%3F")
    expect(tab).to_have_attribute("aria-pressed", "true", timeout=20000)
    expect(panel.locator(".ai-chat-more")).to_have_text("Show 8 sources")
    expect(notes.filter(visible=True)).to_have_count(0)
    page.evaluate("window.continueStream()")
    expect(panel.locator(".ai-chat-more")).to_have_text("7 more sources")
    expect(notes.filter(visible=True)).to_have_count(1)
    page.evaluate("window.continueStream()")
    expect(panel.locator(".ai-follow-up")).to_be_visible()
    # The first four cited, in citation order: [4] is the fifth and stays folded.
    expect(panel.locator(".ai-chat-more")).to_have_text("4 more sources")
    expect(notes.filter(visible=True)).to_have_count(4)
    expect(panel.locator('.ai-sources li[data-source-id="4"]')).to_be_hidden()
    expect(panel.locator('.ai-sources li[data-source-id="6"]')).to_be_visible()
    # Offered while the first answer streams: the answer streams full-width, and the
    # composer appears once the conversation can continue.
    page.goto("http://127.0.0.1:8899/search?q=slow-stream%3F")
    expect(tab).to_be_visible()
    expect(panel.locator(".ai-answer")).to_contain_text("sky", timeout=15000)
    # Entering mid-answer starts its suggestions without waiting for it to finish.
    with page.expect_request(lambda request: request.url.endswith("/suggest")):
        tab.click()
    expect(page.locator("html[data-ai-chat]")).to_have_count(1)
    expect(panel.locator(".ai-follow-up")).to_be_hidden()
    page.get_by_role("button", name="Stop generating", exact=True).click()


if __name__ == "__main__":
    main()

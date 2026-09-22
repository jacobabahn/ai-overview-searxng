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
        expect(panel.locator(".ai-more")).to_be_hidden()
        expect(panel.locator(".ai-follow-up")).to_be_hidden()
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
        expect(panel.locator(".ai-sources li").first).to_be_focused()
        expect(panel.locator(".ai-sources li p").first).not_to_be_empty()
        panel.locator(".ai-sources summary").first.click()
        first_href = panel.locator(".ai-answer a").first.get_attribute("href")
        # Exercise retained conversation support without exposing the hidden input.
        panel.locator(".ai-follow-up").evaluate("""form => {
          form.querySelector('input').value = 'Why is sunset different?';
          form.requestSubmit();
        }""")
        expect(panel.locator(".ai-answer")).to_have_count(2)
        expect(panel.locator(".ai-status")).to_have_text("", timeout=20000)
        expect(panel.locator(".ai-follow-up")).to_be_hidden()
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
        with page.expect_request(lambda request: request.url.endswith("/stream")):
            panel.get_by_role("button", name="Regenerate overview").click()
        expect(panel.locator(".ai-status")).to_have_text("", timeout=20000)
        expect(panel.locator(".ai-answer")).to_have_count(1)
        expect(panel.locator(".ai-follow-up")).to_be_hidden()
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
        assert generation.request.post_data_json == {"token": "selected-search"}
        generation.fulfill(
            content_type="text/event-stream",
            body='event: text_delta\ndata: {"text":"Selected model answer"}\n\n'
            'event: done\ndata: {"token":"selected-continuation","can_follow_up":true}\n\n',
        )
        expect(panel.locator(".ai-status")).to_have_text("")
        expect(panel.locator(".ai-answer")).to_have_count(1)
        expect(panel.locator(".ai-answer")).to_have_text("Selected model answer")
        expect(panel.locator(".ai-more")).to_be_hidden()
        expect(panel.locator(".ai-follow-up")).to_be_hidden()
        with page.expect_request(lambda request: request.url.endswith("/stream")):
            panel.locator(".ai-follow-up").evaluate("""form => {
              form.querySelector('input').value = 'Why?';
              form.requestSubmit();
            }""")
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
        expect(panel.locator(".ai-follow-up")).to_be_hidden()
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
        assert answer.evaluate("el => getComputedStyle(el).whiteSpace") == "pre-wrap"
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
        assert not errors, errors
        browser.close()
    print(
        "Browser checks passed: generation, citations, fresh-search follow-up, mobile, collapse, XSS, activation, empty/error states, cancellation."
    )


if __name__ == "__main__":
    main()

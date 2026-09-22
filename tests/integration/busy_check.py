"""Admission backoff and cancellation in the actual SearXNG UI."""

from pathlib import Path

from playwright.sync_api import Route, expect, sync_playwright


def main() -> None:
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.clock.install()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        requests: list[object] = []
        mode = "recover"

        def stream(route: Route) -> None:
            requests.append(route.request.post_data_json)
            if mode == "partial":
                status = 200
                body = 'event: text_delta\ndata: {"text":"A partial answer remains visible."}\n\n'
                body += 'event: error\ndata: {"code":"provider_limit","message":"Provider usage limit reached."}\n\n'
            elif mode == "recover" and len(requests) > 1:
                status = 200
                body = 'event: text_delta\ndata: {"text":"The summary is ready."}\n\n'
                body += 'event: done\ndata: {"token":"finished","can_follow_up":true}\n\n'
            else:
                status = 429
                body = 'event: error\ndata: {"code":"busy","message":"AI Summary is busy."}\n\n'
            route.fulfill(status=status, content_type="text/event-stream", body=body)

        page.route("**/ai-overview/stream", stream)
        page.goto("http://127.0.0.1:8899/search?q=busy+overview%3F")
        panel = page.locator(".ai-overview")
        status = panel.locator(".ai-status")
        cancel = panel.locator(".ai-cancel-wait")
        retry = panel.locator(".ai-retry")
        expect(panel).to_have_attribute("data-phase", "waiting")
        expect(status).to_have_text("AI Summary is busy. Trying again in 2 seconds (1 of 3).")
        expect(cancel).to_be_visible()
        expect(retry).to_be_hidden()
        panel.get_by_role("button", name="Summary settings").click()
        expect(panel.locator(".ai-regenerate")).to_be_disabled()
        expect(panel.locator(".ai-settings-busy")).to_contain_text("Cancel waiting")
        page.keyboard.press("Escape")
        for dark in [False, True]:
            page.emulate_media(color_scheme="dark" if dark else "light")
            page.screenshot(path=str(output / f"busy-{'dark' if dark else 'light'}.png"))
        page.clock.fast_forward(2000)
        expect(panel.locator(".ai-answer")).to_have_text("The summary is ready.")
        expect(panel).to_have_attribute("data-phase", "idle")
        expect(cancel).to_be_hidden()
        expect(retry).to_be_hidden()
        assert len(requests) == 2 and requests[0] == requests[1]
        expect(panel.locator("article")).to_have_count(1)

        mode = "busy"
        requests.clear()
        page.reload()
        for attempt, delay in enumerate([2000, 4000, 8000], 1):
            expect(status).to_contain_text(f"({attempt} of 3)")
            page.clock.fast_forward(delay)
        expect(panel).to_have_attribute("data-phase", "idle")
        expect(status).to_have_text("AI Summary is still busy. Try again in a moment.")
        expect(retry).to_be_enabled()
        assert len(requests) == 4
        page.clock.fast_forward(60000)
        assert len(requests) == 4
        retry.click()
        expect(status).to_contain_text("(1 of 3)")
        cancel.click()
        expect(status).to_have_text("Waiting canceled. You can retry when you’re ready.")
        expect(retry).to_be_focused()
        page.clock.fast_forward(60000)
        assert len(requests) == 5

        retry.click()
        expect(panel).to_have_attribute("data-phase", "waiting")
        panel.get_by_role("button", name="Collapse overview").click()
        expect(panel.locator(".ai-collapsed-preview")).to_contain_text("AI Summary is busy")
        panel.get_by_role("button", name="Cancel waiting").click()
        expect(panel).to_have_attribute("data-phase", "idle")
        expect(panel.get_by_role("button", name="Expand overview")).to_be_focused()
        page.clock.fast_forward(60000)
        assert len(requests) == 6

        # Leaving the page cancels the timer instead of starting another request.
        page.reload()
        expect(panel).to_have_attribute("data-phase", "waiting")
        page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
        expect(panel).to_have_attribute("data-phase", "idle")
        count = len(requests)
        page.clock.fast_forward(60000)
        assert len(requests) == count

        mode = "partial"
        requests.clear()
        page.reload()
        expect(status).to_have_text("Provider usage limit reached.")
        expect(panel.locator(".ai-answer")).to_have_text("A partial answer remains visible.")
        expect(retry).to_be_visible()
        expect(cancel).to_be_hidden()
        page.clock.fast_forward(60000)
        assert len(requests) == 1
        assert not errors, errors
        browser.close()
    print("Busy checks passed: recovery, bounded backoff, cancellation, focus, provider errors.")


if __name__ == "__main__":
    main()

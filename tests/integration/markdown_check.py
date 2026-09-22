"""Markdown browser checks against the offline SearXNG instance."""

from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright


def send(page: Page, name: str, data: dict[str, object]) -> None:
    page.evaluate(
        """({name, data}) => window.markdownStream.enqueue(new TextEncoder().encode(
          `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`))""",
        {"name": name, "data": data},
    )


def main() -> None:
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        # A controllable stream lets us inspect the UI between real text deltas.
        page.add_init_script("""(() => {
          const originalFetch = window.fetch;
          window.fetch = (url, options) => {
            if (!String(url).endsWith('/ai-overview/stream')) return originalFetch(url, options);
            return Promise.resolve(new Response(new ReadableStream({
              start(controller) { window.markdownStream = controller; }
            }), {headers: {'Content-Type': 'text/event-stream'}}));
          };
        })();""")
        page.goto("http://127.0.0.1:8899/search?q=python+example%3F")
        page.wait_for_function("window.markdownStream !== undefined")
        send(
            page,
            "sources",
            {
                "sources": [
                    {
                        "id": 1,
                        "url": "https://example.org/python",
                        "title": "Python example",
                        "snippet": "Use a list to store values.",
                    }
                ]
            },
        )
        intro = "**Example** [1]\n\nUse `items[1]` to read the second item.\n\n- Create a list\n- Read an item\n\n"
        code = "items = [1, 2, 3]\nprint(items[1])\n# " + "long comment " * 20
        opening = intro + "```python\n" + code
        send(page, "text_delta", {"text": opening})
        panel = page.locator(".ai-overview")
        answer = panel.locator(".ai-answer")
        expect(answer.locator("strong")).to_have_text("Example")
        expect(answer.locator("li")).to_have_count(2)
        expect(answer.locator("a[data-source-id]")).to_have_count(1)
        expect(answer.locator("p code")).to_have_text("items[1]")
        expect(answer.locator(".ai-code-preview")).to_be_visible()
        expect(answer.locator(".ai-code-block")).to_be_hidden()
        panel.get_by_role("button", name="Show full answer").click()
        block = answer.locator(".ai-code-block")
        expect(block.locator("pre code")).to_have_text(code)
        expect(block.locator("a")).to_have_count(0)
        expect(block.locator("pre code span")).to_have_count(0)
        expect(block.locator(".ai-code-toolbar span")).to_have_text("python")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        pre = block.locator("pre")
        assert pre.evaluate("el => el.scrollWidth > el.clientWidth")
        pre.evaluate("el => { el.scrollLeft = 100; window.originalCodeBlock = el.parentElement; }")
        block.get_by_role("button", name="Copy code").click()
        expect(block.locator(".ai-code-status")).to_have_text("Code copied.")
        assert page.evaluate("navigator.clipboard.readText()") == code
        # Update the unfinished block without losing its focused control or scroll.
        addition = "\nprint('done')"
        send(page, "text_delta", {"text": addition})
        code += addition
        expect(block.locator("pre code")).to_have_text(code)
        assert pre.evaluate(
            "el => el.parentElement === window.originalCodeBlock && el.scrollLeft === 100"
        )
        expect(block.get_by_role("button", name="Copy code")).to_be_focused()
        send(page, "text_delta", {"text": "\n```\n\nThat prints the second item. [1]"})
        expect(block.locator(".hljs-string")).to_have_text("'done'")
        expect(block.locator(".hljs-comment")).to_have_count(1)
        pre.evaluate("el => { window.firstHighlightedToken = el.querySelector('span'); }")
        send(page, "text_delta", {"text": "\n"})
        send(page, "done", {"token": "finished", "can_follow_up": True})
        assert pre.evaluate(
            "el => el.querySelector('span') === window.firstHighlightedToken && el.scrollLeft === 100"
        )
        expect(panel.locator(".ai-stop")).to_be_hidden()
        expect(answer.locator("a[data-source-id]")).to_have_count(2)
        assert pre.evaluate("el => el.parentElement === window.originalCodeBlock")
        block.get_by_role("button", name="Copy code").click()
        assert page.evaluate("navigator.clipboard.readText()") == code
        panel.get_by_role("button", name="Copy answer").click()
        assert (
            page.evaluate("navigator.clipboard.readText()")
            == opening + addition + "\n```\n\nThat prints the second item. [1]\n"
        )
        # HTTP deployments use a selection-based fallback when the async API is absent.
        page.evaluate(
            "() => { window.originalWriteText = navigator.clipboard.writeText; navigator.clipboard.writeText = undefined; }"
        )
        block.get_by_role("button", name="Copy code").click()
        expect(block.locator(".ai-code-status")).to_have_text("Code copied.")
        assert page.evaluate("navigator.clipboard.readText()") == code
        expect(block.get_by_role("button", name="Copy code")).to_be_focused()
        # Clipboard failure is visible and leaves the code selectable.
        page.evaluate(
            "() => { navigator.clipboard.writeText = async () => { throw new Error('denied'); }; }"
        )
        block.get_by_role("button", name="Copy code").click()
        expect(block.locator(".ai-code-status")).to_contain_text("Select the code")
        pre.evaluate("el => { el.scrollLeft = 0; }")
        page.evaluate("() => { navigator.clipboard.writeText = window.originalWriteText; }")
        block.get_by_role("button", name="Copy code").click()
        for width, dark in [(390, False), (390, True), (1280, False)]:
            page.set_viewport_size({"width": width, "height": 900})
            page.emulate_media(color_scheme="dark" if dark else "light")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(
                path=str(output / f"markdown-{width}-{'dark' if dark else 'light'}.png"),
                full_page=True,
            )
        # HTML, images, and unsafe links stay inert; even HTML-language fences are text.
        assert page.evaluate(r"""async () => {
          const {renderMarkdown} = await import('/ai-overview/static/markdown.js');
          const {renderCitations} = await import('/ai-overview/static/overview.js');
          const box = document.createElement('div');
          const attack = '<img src=x onerror=alert(1)>\n\n<script>alert(1)</script>\n\n' +
            '[click](javascript:alert(1)) ![image](https://example.org/image.png)\n\n' +
            '```html\n<img src=x onerror=alert(1)> [1]\n```';
          renderMarkdown(box, attack, [{id:1, url:'https://example.org', title:'Source'}], renderCitations);
          return !box.querySelector('img, script, a, iframe') &&
            box.querySelector('pre code').textContent === '<img src=x onerror=alert(1)> [1]';
        }""")
        # Supported languages and aliases produce spans without changing the code.
        assert page.evaluate(r"""async () => {
          const {renderMarkdown} = await import('/ai-overview/static/markdown.js');
          const {renderCitations} = await import('/ai-overview/static/overview.js');
          const box = document.createElement('div');
          const examples = {
            python: 'def greet(name):\n    return "Hi " + name',
            py: 'print(True)',
            javascript: 'const value = "text";', js: 'let n = 42;',
            typescript: 'const n: number = 42;', ts: 'interface User { name: string }',
            html: '<div onclick="alert(1)">Hello & goodbye</div>',
            css: '.example { color: red; }', json: '{"value": true}',
            bash: 'echo "$HOME"', sh: 'echo "$HOME"', sql: 'SELECT name FROM users;',
          };
          for (const [language, text] of Object.entries(examples)) {
            renderMarkdown(box, '```' + language + '\n' + text + '\n```', [], renderCitations);
            const code = box.querySelector('pre code');
            if (!code.querySelector('span') || code.textContent !== text ||
                code.querySelector('div, script, img, a, [onclick]')) return false;
          }
          for (const language of ['unknown-language', 'text', '']) {
            renderMarkdown(box, '```' + language + '\nplain [1] <tag>\n```', [], renderCitations);
            const code = box.querySelector('pre code');
            if (code.children.length || code.textContent !== 'plain [1] <tag>') return false;
          }
          // An unclosed fence is plain during streaming, highlighted at completion.
          const unfinished = '```python\nprint("done")';
          renderMarkdown(box, unfinished, [], renderCitations, {complete: false});
          if (box.querySelector('pre code span')) return false;
          renderMarkdown(box, unfinished, [], renderCitations);
          if (!box.querySelector('pre code .hljs-string')) return false;
          const large = '# a long comment\n'.repeat(4000);
          renderMarkdown(box, '```python\n' + large + '```', [], renderCitations);
          return !box.querySelector('pre code span');
        }""")
        # Explicit SearXNG themes override the system preference.
        string_token = block.locator(".hljs-string")
        page.emulate_media(color_scheme="dark")
        page.evaluate("document.documentElement.className = 'theme-light'")
        expect(string_token).to_have_css("color", "rgb(17, 99, 41)")
        page.emulate_media(color_scheme="light")
        page.evaluate("document.documentElement.className = 'theme-dark'")
        expect(string_token).to_have_css("color", "rgb(139, 213, 160)")
        assert not errors, errors
        browser.close()
    print("Markdown checks passed: streaming, copy, citations, mobile, dark mode, inert HTML.")


if __name__ == "__main__":
    main()

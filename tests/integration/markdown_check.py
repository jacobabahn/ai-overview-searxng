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
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        requests: list[str] = []
        page.on("request", lambda request: requests.append(request.url))
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

        def grammars() -> list[str]:
            return sorted(
                url.rsplit("/highlight-", 1)[1][:-3] for url in requests if "/highlight-" in url
            )

        page.goto("http://127.0.0.1:8899/search?q=python+example%3F")
        page.wait_for_function("window.markdownStream !== undefined")
        # A page without code fetches no highlighter at all.
        assert not grammars(), grammars()
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
        # The preview shows the answer as written, code included, cut off by height.
        expect(panel).to_have_attribute("data-clipped", "true")
        assert answer.evaluate("el => el.scrollHeight > el.clientHeight")
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
        # The button confirms in place, keeping its accessible name.
        expect(block.locator(".ai-code-toolbar button")).to_have_text("Copied")
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
        expect(block.locator(".ai-code-status")).to_be_visible()
        expect(block.locator(".ai-code-toolbar button")).to_have_text("Copy code")
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
        # Grammars load on demand: the first answer needed Python and nothing else.
        assert grammars() == ["core", "python"], grammars()
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
        assert (
            page.evaluate(r"""async () => {
          const {renderMarkdown} = await import('/ai-overview/static/markdown.js');
          const {renderCitations} = await import('/ai-overview/static/overview.js');
          const box = document.createElement('div');
          const painted = async selector => {
            for (let tries = 0; tries < 100 && !box.querySelector(selector); tries++) {
              await new Promise(resolve => setTimeout(resolve, 20));
            }
            return box.querySelector(selector);
          };
          const examples = {
            python: 'def greet(name):\n    return "Hi " + name',
            py: 'print(True)',
            javascript: 'const value = "text";', js: 'let n = 42;',
            typescript: 'const n: number = 42;', ts: 'interface User { name: string }',
            html: '<div onclick="alert(1)">Hello & goodbye</div>',
            css: '.example { color: red; }', json: '{"value": true}', jsonc: '{"value": true}',
            bash: 'echo "$HOME"', sh: 'echo "$HOME"', shell: 'echo "$HOME"', zsh: 'echo "$HOME"',
            sql: 'SELECT name FROM users;',
            go: 'func main() { fmt.Println("<b>hi</b>") }', rust: 'fn main() { println!("hi"); }',
            java: 'public class Example {}', c: 'int main(void) { return 0; }',
            'c++': 'std::vector<int> items;', 'c#': 'public class Example {}',
            php: '<?php echo "<script>alert(1)</script>";', ruby: 'def greet; "hi"; end',
            kotlin: 'fun main() {}', swift: 'let value = 1', yaml: 'name: value', yml: 'name: value',
            toml: 'name = "value"', dockerfile: 'FROM alpine\nRUN echo hi', diff: '-old\n+new',
            markdown: '# Title\n\n<img src=x onerror=alert(1)>', lua: 'local value = 1',
            console: '$ echo hi',
          };
          for (const [language, text] of Object.entries(examples)) {
            renderMarkdown(box, '```' + language + '\n' + text + '\n```', [], renderCitations);
            const code = box.querySelector('pre code');
            if (!await painted('pre code span') || code.textContent !== text ||
                code.querySelector('div, script, img, a, [onclick]')) return language;
          }
          // An inline script and style in HTML use the grammars they embed.
          renderMarkdown(box, '```html\n<script>let n = 42;</script>\n```', [], renderCitations);
          if (!await painted('pre code .hljs-keyword')) return 'embedded';
          for (const language of ['unknown-language', 'text', '', 'constructor', '../overview']) {
            renderMarkdown(box, '```' + language + '\nplain [1] <tag>\n```', [], renderCitations);
            await new Promise(resolve => setTimeout(resolve, 60));
            const code = box.querySelector('pre code');
            if (code.children.length || code.textContent !== 'plain [1] <tag>') return language;
          }
          // An unclosed fence is plain during streaming, highlighted at completion.
          const unfinished = '```python\nprint("done")';
          renderMarkdown(box, unfinished, [], renderCitations, {complete: false});
          if (box.querySelector('pre code span')) return 'unfinished';
          renderMarkdown(box, unfinished, [], renderCitations);
          if (!box.querySelector('pre code .hljs-string')) return 'finished';
          const large = '# a long comment\n'.repeat(4000);
          renderMarkdown(box, '```python\n' + large + '```', [], renderCitations);
          await new Promise(resolve => setTimeout(resolve, 60));
          return box.querySelector('pre code span') ? 'large' : true;
        }""")
            is True
        )
        # Every grammar came from this instance, and unknown labels fetched nothing.
        assert all(url.startswith("http://127.0.0.1:8899/") for url in requests), requests
        assert not [url for url in requests if "unknown" in url or "constructor" in url]
        assert "go" in grammars() and "shell" in grammars()
        # Explicit SearXNG themes override the system preference.
        string_token = block.locator(".hljs-string")
        page.emulate_media(color_scheme="dark")
        page.evaluate("document.documentElement.className = 'theme-light'")
        expect(string_token).to_have_css("color", "rgb(17, 99, 41)")
        page.emulate_media(color_scheme="light")
        page.evaluate("document.documentElement.className = 'theme-dark'")
        expect(string_token).to_have_css("color", "rgb(139, 213, 160)")
        # A code block inside a list item is moved to a new parent on every delta; it
        # must fade in once and then stay visible while later text streams.
        page.evaluate("document.documentElement.className = ''")
        page.evaluate("window.markdownStream = undefined")
        page.goto("http://127.0.0.1:8899/search?q=nested+code%3F")
        page.wait_for_function("window.markdownStream !== undefined")
        send(
            page,
            "text_delta",
            {"text": "1. Create the environment:\n\n   ```bash\n   python -m venv"},
        )
        nested = panel.locator(".ai-answer li .ai-code-block")
        expect(nested).to_have_count(1)
        assert float(nested.evaluate("el => getComputedStyle(el).opacity")) < 1
        expect(nested).to_have_css("opacity", "1")
        for piece in [" .venv\n", "   ```\n\n", "2. Then ", "activate ", "it."]:
            send(page, "text_delta", {"text": piece})
            page.wait_for_timeout(40)
            assert nested.evaluate("el => getComputedStyle(el).opacity") == "1", piece
        expect(panel.locator(".ai-answer li")).to_have_count(2)
        send(page, "done", {"token": "finished", "can_follow_up": True})
        # On a fresh page, the first JavaScript block also gets the grammars it embeds:
        # tagged css and html templates are highlighted, not left as plain strings.
        page.evaluate("window.markdownStream = undefined")
        requests.clear()
        page.goto("http://127.0.0.1:8899/search?q=template+example%3F")
        page.wait_for_function("window.markdownStream !== undefined")
        templates = 'const style = css`a { color: red; }`;\nconst view = html`<p class="x">hi</p>`;'
        send(page, "text_delta", {"text": "```js\n" + templates + "\n```\n"})
        send(page, "done", {"token": "finished", "can_follow_up": True})
        tagged = panel.locator(".ai-answer .ai-code-block")
        expect(tagged.locator(".language-css .hljs-attribute")).to_have_text("color")
        expect(tagged.locator(".language-xml .hljs-name").first).to_have_text("p")
        expect(tagged.locator("pre code")).to_have_text(templates)
        assert grammars() == ["core", "css", "graphql", "javascript", "xml"], grammars()
        # A grammar that arrives late paints the block that is already on screen: the
        # whole Rust block is delivered at once while its grammar is held back.
        page.evaluate("window.markdownStream = undefined")
        page.goto("http://127.0.0.1:8899/search?q=rust+example%3F")
        page.wait_for_function("window.markdownStream !== undefined")
        held = []
        page.route("**/highlight-rust.js", lambda route: held.append(route))
        rust = 'fn main() {\n    println!("hi");\n}'
        send(page, "text_delta", {"text": "```rust\n" + rust + "\n```\n\nDone."})
        late = panel.locator(".ai-answer .ai-code-block")
        expect(late.locator("pre code")).to_have_text(rust)
        expect(late.locator(".ai-code-toolbar span")).to_have_text("rust")
        page.wait_for_timeout(200)
        assert len(held) == 1
        expect(late.locator("pre code span")).to_have_count(0)
        late.locator("pre").evaluate("el => { window.lateBlock = el.parentElement; }")
        held[0].continue_()
        expect(late.locator(".hljs-keyword").first).to_have_text("fn")
        expect(late.locator("pre code")).to_have_text(rust)
        assert late.locator("pre").evaluate("el => el.parentElement === window.lateBlock")
        # A grammar that cannot be fetched leaves the code plain, and the answer intact.
        page.unroute("**/highlight-rust.js")
        page.route("**/highlight-swift.js", lambda route: route.abort())
        send(page, "text_delta", {"text": "\n\n```swift\nlet value = 1\n```\n"})
        send(page, "done", {"token": "finished", "can_follow_up": True})
        swift = late.nth(1)
        expect(swift.locator("pre code")).to_have_text("let value = 1")
        page.wait_for_timeout(200)
        expect(swift.locator("pre code span")).to_have_count(0)
        errors[:] = [e for e in errors if "Failed to load resource" not in e]
        assert not errors, errors
        browser.close()
    print(
        "Markdown checks passed: streaming, copy, citations, mobile, dark mode, inert HTML, "
        "on-demand grammars."
    )


if __name__ == "__main__":
    main()

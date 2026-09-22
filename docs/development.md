# Development

Run commands from the repository root. Requirements: Python 3.11+, uv, and
Node.js 22.7+ (for dependency-free JavaScript lifecycle tests). Docker Compose
is required only for the SearXNG integration checks.

```sh
uv sync --locked
make check
make demo
```

Open <http://127.0.0.1:8765>. The demo uses labeled prerecorded answers and does
not call search engines or model providers. There is no frontend build step.

## Integration tests

The fixture instance runs real SearXNG with an offline search engine and a local
provider fixture. It is separate from any existing instance.

```sh
uv run playwright install chromium
make integration
```

On Linux, Playwright may also need system libraries; install them with
`uv run playwright install --with-deps chromium` if needed.
The browser check waits for <http://127.0.0.1:8899/healthz> and covers citations,
follow-up retrieval, model selection, desktop/mobile layouts, keyboard behavior,
empty evidence, provider errors, retry, and Stop. Screenshots go to ignored
`artifacts/`. Remove the test containers and volumes afterward:

```sh
make integration-down
```

Compose files accept `SEARXNG_IMAGE` to test a different image version or digest.
The default is the version used during initial development.

## Packaging and CI

```sh
uv build
```

The wheel includes browser assets and templates. Build output goes to ignored
`dist/`. GitHub Actions runs linting, formatting, type checking, Python tests,
JavaScript tests, and package builds. Docker/browser integration and live
provider calls are separate checks and are not part of that workflow.

Provider fixture tests cover backend request construction and streaming parsers;
they do not establish live provider compatibility or answer quality. When
reporting a problem, include the SearXNG image version, backend, model ID, and
reproduction steps. Remove credentials, signed conversation state, and private
search content from logs and screenshots.

## Design references

- [Architecture](ARCHITECTURE.md): implementation boundaries and tradeoffs.
- [Initial specification](SPEC.md): historical planning notes.
- [Design audit](DESIGN_AUDIT.md): historical interface review.

## Markdown rendering

The browser vendors Marked 18.0.13 in `static/marked.js` with its MIT license in
`static/marked.LICENSE.txt`, sourced from the published npm package. No CDN or
frontend build step is needed. `markdown.js` uses only the lexer and creates DOM
nodes for paragraphs, headings, lists, emphasis, and code. Generated HTML remains
literal text; Markdown links render their labels without becoming clickable.
Citations are handled only in prose, never in code. Copy answer preserves the
original Markdown, while Copy code copies only that block's contents.

When updating Marked, verify the npm archive integrity and replace both vendored
files. Run the browser integration checks for streaming, copy behavior, and XSS.

Syntax highlighting vendors the core and eight language modules from
`@highlightjs/cdn-assets` 11.12.0, with its BSD-3-Clause license in
`static/highlight.LICENSE.txt`. The npm archive's SHA-512 integrity is
`KvOKXODaiFmId9xaq3xc5xCL66wVLUuOngDbO9B/kewbFTqdGbn2nJxNhN3H5R1cgDTVj6R8vH0zgiNDEGjpDw==`.
These are unmodified ESM files, renamed `highlight-<module>.js` for packaging.

`syntax.js` registers Python, JavaScript, TypeScript, XML/HTML, CSS, JSON, Bash,
and SQL (including their registered aliases). Code stays plain while a fence is
open; a closing fence or completed answer triggers highlighting. Unknown or
unlabeled languages, grammar errors, and blocks over 50,000 characters fall back
to plain text. The renderer rebuilds only text and span nodes from the escaped
highlighting output and verifies that their text exactly matches the original.
Highlighting never introduces executable HTML or changes clipboard contents.

## Busy-state recovery

Only an HTTP 429 stream response carrying the local `busy` error code, before
any content/status event, is retried automatically. The browser keeps the same
signed token and question and retries after 2, 4, and 8 seconds. Waiting remains
an exclusive conversation operation; canceling, Stop, or leaving the page aborts
its timer. After three retries, the UI offers manual Retry with a fresh budget.
Provider limits, transport errors, and partial responses are never auto-replayed.

`tests/integration/busy_check.py` uses a controlled browser clock to cover waiting,
recovery, exhaustion, cancellation, keyboard focus, and preserved partial answers.
It runs as part of `make integration`.

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

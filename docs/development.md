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
empty evidence, provider errors, retry, and Stop. The container check makes
sure the plugin leaves SearXNG's result container open in `post_search`: a
fixture plugin forced to run after it still shows its answer, and a one-result
fixture engine's score on `/stats` is counted once per search. Screenshots go to ignored
`artifacts/`. Remove the test containers and volumes afterward:

```sh
make integration-down
```

Compose files accept `SEARXNG_IMAGE` to test a different image version or digest.
The default is the pinned version the examples use.

CI runs `make integration` against that pinned image on every push and pull
request (the `integration` job in `.github/workflows/check.yml`). A separate
workflow, `.github/workflows/integration-latest.yml`, runs the same checks
against `searxng/searxng:latest` weekly and on manual dispatch, so upstream
changes to the SearXNG internals the plugin uses show up without blocking
pushes or pull requests. When either fails, the run prints the Compose logs.

These jobs run entirely on the GitHub runner, the same way as locally: Compose
pulls the published SearXNG image, mounts `src/ai_overview` from the checkout
into it, and the checks drive that instance with headless Chromium. No image
is built, and no real search engine or model provider is contacted.

## Packaging and CI

```sh
uv build
```

The wheel includes browser assets and templates. Build output goes to ignored
`dist/`. GitHub Actions runs linting, formatting, type checking, Python tests,
JavaScript tests, package builds, and the Docker/browser integration checks
described above. Live provider calls are not part of CI.

Provider fixture tests cover backend request construction and streaming parsers;
they do not establish live provider compatibility or answer quality. When
reporting a problem, include the SearXNG image version, backend, model ID, and
reproduction steps. Remove credentials, signed conversation state, and private
search content from logs and screenshots.

See [Architecture](ARCHITECTURE.md) for implementation boundaries and the
streaming and state contracts.

## Releasing

A release is a git tag and a GitHub release; nothing goes to PyPI.

1. Set `__version__` in `src/ai_overview/__init__.py` to the new version.
2. In `CHANGELOG.md`, move the entries under "Unreleased" into a new
   `## [X.Y.Z] - YYYY-MM-DD` section with the release date, and add its link
   at the bottom. Update the tag in the README's install step.
3. Merge that to `main`, then tag the merged commit and push the tag:

   ```sh
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

The tag starts `.github/workflows/release.yml`. It stops unless the tag is `v`
plus `__version__` and the changelog has a dated section for it, runs the same
`check` and `integration` jobs as CI, then builds the wheel and sdist and
creates the GitHub release with them attached and that section as its notes.
`python scripts/release_notes.py vX.Y.Z` runs the same tag and changelog check
locally and prints the notes.

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

Syntax highlighting vendors the core and 39 language modules from
`@highlightjs/cdn-assets` 11.12.0, with its BSD-3-Clause license in
`static/highlight.LICENSE.txt`. The npm archive's SHA-512 integrity is
`KvOKXODaiFmId9xaq3xc5xCL66wVLUuOngDbO9B/kewbFTqdGbn2nJxNhN3H5R1cgDTVj6R8vH0zgiNDEGjpDw==`.
These are unmodified ESM files (`es/core.min.js` and `es/languages/<module>.min.js`),
renamed `highlight-<module>.js` for packaging.

The packaged languages are Bash, C, C++, C#, CSS, Dart, Diff, Dockerfile, Elixir,
Go, GraphQL, Haskell, HTTP, INI/TOML, Java, JavaScript, JSON, Kotlin, Lua,
Makefile, Markdown, Nginx, Objective-C, Perl, PHP, PowerShell, Protocol Buffers,
Python, R, Ruby, Rust, Scala, SCSS, shell sessions, SQL, Swift, TypeScript,
XML/HTML, and YAML. `syntax.js` maps a fence label to a module through a static
table of each grammar's name and aliases (`js`, `py`, `c++`, `yml`, `toml`, ...).
`shell` selects Bash, since answers use it for plain commands; `console` and
`shellsession` select the prompt-and-output grammar.

Nothing is fetched until a code block needs it. The first labelled block imports
the core and its grammar from the instance's own `static/` path, along with any
grammar it embeds, directly or through another grammar: CSS and JavaScript for
HTML; CSS, HTML and GraphQL for tagged templates in JavaScript and TypeScript;
Bash for Dockerfiles and shell sessions; HTML for Markdown. Each module is
fetched once per page, and a block is painted only when its grammar and the ones
it embeds have settled. Left out on purpose: Ruby in YAML, Markdown in Dart doc
comments, Mojolicious in Perl, and detection of an HTTP message's body. The fetch
starts while the block is still streaming, and a block that is complete before
its grammar arrives is painted when it does. A page without code loads only
`syntax.js`.

To add a language, copy its module from the same release, add it to the table in
`syntax.js` with the aliases the grammar declares, and list any grammar it embeds.
The tests in `tests/browser/` fail when a packaged grammar's aliases or
sub-languages and those tables disagree.

Code stays plain while a fence is open; a closing fence or completed answer
triggers highlighting. Unknown or unlabeled languages, grammars that fail to load,
grammar errors, and blocks over 50,000 characters stay plain text; a label never
becomes part of a URL, and language auto-detection is not used. The renderer
rebuilds only text and span nodes from the escaped highlighting output and
verifies that their text exactly matches the original. Highlighting never
introduces executable HTML or changes clipboard contents.

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

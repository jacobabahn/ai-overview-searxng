# AI overviews for SearXNG

A modular Python plugin for the Simple theme. End a search with `?` to stream a
snippet-based overview with citations. Ask follow-ups in the same panel; the
plugin resolves the question and retrieves fresh results when needed.

[Product spec](SPEC.md) · [Architecture](ARCHITECTURE.md)

## Development

Uses **uv, Ruff, ty, pytest, typed dataclasses**, and a small framework-free browser
component. Python 3.11+ and Node.js 22.7+ for development checks; SearXNG supplies its own
Python runtime in Docker. Node runs dependency-free browser lifecycle tests;
the extension still needs no frontend build step.

```sh
uv sync
make check
make demo
```

Open <http://127.0.0.1:8765>. The demo uses clearly labeled prerecorded answers;
it does not call a search engine or model provider.

Run the real SearXNG integration with an offline search engine and local fixture
provider, isolated from your existing instance:

```sh
uv run playwright install chromium
docker compose -f compose.test.yml up -d
# Once http://127.0.0.1:8899 is ready:
uv run python tests/integration/browser_check.py
```

The browser check covers citations, follow-up retrieval, mobile layout,
collapse/expand, activation, empty evidence, provider failures, and Stop. It saves
screenshots to `artifacts/`. Stop and remove the test containers/volumes with
`make integration-down`.

## Install in an existing Docker instance

The integration targets SearXNG's class-based plugin API. Development uses
SearXNG `2026.9.19-e831fc2a1`; pin your image version/digest for repeatability.

1. Copy `examples/overview.yml` to a private configuration location. Set the
   default profile, its exact model ID, and endpoint. Hosted model names are
   intentionally placeholders; select models available to your account.
2. Add the package mount to the SearXNG service:

   ```yaml
   volumes:
     - /absolute/path/ai-overview-searxng/src/ai_overview:/usr/local/searxng/ai_overview:ro
     - /absolute/path/overview.yml:/etc/searxng/overview.yml:ro
   ```

3. Merge `examples/settings.yml` into your SearXNG settings. Keep your existing
   engines, preferences, and strong `server.secret_key`. Disable the old
   `ai_answers` plugin to avoid duplicate overview panels. The dedicated
   `outgoing.networks.ai_overview` entry permits local HTTP model servers without
   changing other search-engine networks. It inherits proxy/TLS settings.
4. Pass the selected API key through the container environment. Keys stay on the
   server. Local profiles need no key unless your inference server requires one;
   then configure `api_key_env` explicitly.
5. Recreate the service to apply mount and environment changes. Enable **AI
   overview** in SearXNG Preferences if saved browser preferences override the
   default. Search the General category for `why is the sky blue?`.

See `compose.example.yml` for a complete service example. It is not a replacement
for your existing Compose configuration. When a local inference server runs on
the Docker host, `localhost` inside the SearXNG container will not reach it; use
an accessible host address and bind the inference server accordingly.

For a non-container installation, install this package into SearXNG's Python
environment and register `ai_overview.plugin.SXNGPlugin` in settings.

## Provider profiles

### Try OpenCode Go now

For a separate instance with real searches, the model picker, and your Go key:

```sh
uv run python scripts/configure_live.py
docker compose -f compose.live.yml up -d --force-recreate
```

The first command prompts for your key without echoing it. It stores private
configuration in `.local/` (ignored by Git, directory mode 700, files mode 600).
Open <http://127.0.0.1:8898>, search with a trailing `?`, and use **Model** in the
overview panel. The fixture demo on port 8899 remains separate. To reuse an
existing container's Go key and search configuration instead of entering a key:

```sh
uv run python scripts/configure_live.py --from-container searxng
```

Configure the picker in `overview.yml`:

```yaml
default_profile: opencode
model_picker: true
profiles:
  opencode:
    backend: opencode_go
    model: deepseek-v4-flash
    api_key_env: OPENCODE_GO_API_KEY
    discover_models: true
    max_output_tokens: 4096
    planning_max_output_tokens: 4096
```

Model IDs come from Go's public `/zen/go/v1/models` endpoint, fetched on the server
and cached for five minutes. This catalog does not validate your key or guarantee
account access. Protocol routing follows Go's documented endpoints; unknown IDs
are shown disabled until configured through `model_protocols` (values: `chat`,
`responses`, `anthropic`). A failed refresh retains saved/configured choices and
shows a message. The API key and endpoint configuration never reach the browser.

The picker also includes other configured profiles. It remembers only the
selected profile/model in local storage. Switching models starts a fresh overview
from the original results and clears its follow-up conversation. Existing
conversations retain their signed model selection.

| Backend | Protocol | Endpoint configuration |
| --- | --- | --- |
| `ollama` | Native chat / NDJSON | Full `/api/chat` URL |
| `local` | Chat Completions / SSE | Full `/v1/chat/completions` URL |
| `openai` | Responses / SSE | Default supplied; override with full endpoint |
| `gemini` | Native generateContent / SSE | API root ending in `/v1beta`, without model or query |
| `openrouter` | Chat Completions / SSE | Default supplied |
| `opencode_go` | Chat Completions, Responses, or Anthropic Messages | Default selected by protocol |

All profiles require an explicit `model`. Set `max_output_tokens` to accommodate
your model's answer and reasoning budget. Model-specific reasoning controls can
go in validated `options`; supported fields are listed in `routing.py`.
`planning_max_output_tokens` separately sets the follow-up planning budget
(default 1,200), including any reasoning tokens counted by the provider.

For chat models supporting DeepSeek's thinking control, configure it in the
profile's `options` in `overview.yml` and restart SearXNG:

```yaml
options:
  thinking:
    type: disabled  # enabled to turn thinking on; omit to use the provider default
```

This applies to both overview and follow-up planning requests. The field follows
[DeepSeek's API](https://api-docs.deepseek.com/guides/thinking_mode/); support through
other providers/gateways must be verified. It is not a universal chat option.
The model picker does not carry `thinking` to a different model or protocol;
use a separate configured profile to customize that model. Existing reasoning
controls for Responses, Gemini, and Anthropic remain available in `options`.

Overviews aim for 100–180 words, fewer for simple questions, with more detail when
needed or requested. Default-model generation starts while the model catalog loads
in the background. Restoring a different saved model still waits for validation.

Go requests identify this extension honestly and include a stable conversation
session header. Its documentation describes coding-agent traffic as the intended
workload; general search synthesis is not established as supported usage.

With `model_picker: false` (the default), the configured default profile is used.
There is no automatic provider fallback.

## Behavior and limits

- Only a trailing `?` after whitespace trimming triggers initial generation.
  Only HTML, first-page, General-category results are eligible.
- Sources are deduplicated and bounded snippets; pages are not fetched.
- Follow-up planning adds one model request. It uses the same profile; a factual
  follow-up can add one internal SearXNG search with the original engines,
  language, safe-search setting, and time filter.
- Model output is rendered as text. Numeric citations link to supplied sources;
  arbitrary model HTML and Markdown links are not rendered. Correct source IDs
  do not by themselves guarantee that a claim is supported.
- State is signed, readable data held in page memory. It is not saved to the URL,
  local storage, or a conversation database. Reloading starts a new conversation.
  Tokens expire and are replayable until expiry. This targets private instances.
- Defaults: 8 sources, 12 KB of evidence, 6 turns, 30-minute state TTL, and 2
  simultaneous generations **per worker**. Input budgets count UTF-8 JSON bytes,
  not model tokens; context limits may end a conversation before its turn limit.
- Stop aborts the browser request and closes the provider stream when the WSGI
  server detects disconnection. That may take until the next chunk or network
  timeout; immediate cancellation of provider computation is not guaranteed.
- If a reverse proxy buffers SSE, disable buffering for `/ai-overview/stream`
  and allow a read timeout longer than the configured generation timeout.

## Verification status

Ruff lint/format checks, ty, 78 Python tests, 8 JavaScript lifecycle tests,
and the browser integration checks
passed against SearXNG `2026.9.19-e831fc2a1`. Desktop, mobile, and dark-mode
screenshots are generated by the browser check. A source distribution and wheel
can be built with `uv build`.

Provider tests exercise all six backend configurations and five protocol parsers
using fragmented fixture streams, normal completion, truncation, errors, and
transport cleanup. Live provider calls require the corresponding model/account
or local server and are **not verified by these fixture tests**. A live Go test
also verified catalog discovery (37 model IDs at the time of testing), a
DeepSeek V4 Flash overview using real search snippets, a follow-up, and a browser
switch to MiniMax M2.7 through the Anthropic Messages protocol. Other live
provider/model combinations remain unverified.

This is an initial implementation. Answer-quality evaluation, full-page retrieval,
conversation persistence, and public-instance admission controls remain future work.

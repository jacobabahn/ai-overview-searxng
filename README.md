# AI overviews for SearXNG

Streaming answers with source citations and conversational follow-ups, inside
SearXNG's Simple theme. End a search with `?` to generate an overview from search
snippets. Follow-up questions can retrieve fresh results when needed.

**Early-stage software for personal/private instances.** Supports Ollama, local
OpenAI-compatible servers, OpenAI, Gemini, OpenRouter, and OpenCode Go. Requires
SearXNG's class-based plugin API; the initial integration was tested with
`2026.9.19-e831fc2a1`. Other SearXNG versions may need adjustments.

[Provider configuration](docs/providers.md) ·
[Development and testing](docs/development.md) ·
[Architecture](docs/ARCHITECTURE.md)

## Try the demo

With Python 3.11+ and uv installed:

```sh
git clone https://github.com/jacobabahn/ai-overview-searxng.git
cd ai-overview-searxng
uv sync --locked
make demo
```

Open <http://127.0.0.1:8765>. This demo uses prerecorded fixture answers; no
SearXNG instance, API key, or model server is required.

## Install with Docker Compose

For an existing SearXNG instance:

1. Clone this repository and copy `examples/overview.yml` to a private
   configuration location. Choose a `default_profile` and set its exact model
   ID and endpoint. Example model names are placeholders unless stated otherwise.
2. Add these mounts to your SearXNG service, replacing the host paths:

   ```yaml
   volumes:
     - /absolute/path/ai-overview-searxng/src/ai_overview:/usr/local/searxng/ai_overview:ro
     - /absolute/path/overview.yml:/etc/searxng/overview.yml:ro
   ```

3. Merge [examples/settings.yml](examples/settings.yml) into your SearXNG
   settings. Keep your existing engines, preferences, and strong
   `server.secret_key`. Disable `ai_answers` to avoid duplicate panels. The
   `outgoing.networks.ai_overview` entry permits local HTTP model servers while
   inheriting SearXNG's proxy and TLS settings.
4. Pass your selected provider's API key through the container environment, using
   the variable named by `api_key_env`. Local profiles need no key unless the
   inference server requires one. Credentials stay on the server.
5. Recreate the service to apply the mounts and environment. If saved browser
   preferences override the default, enable **AI overview** in SearXNG
   Preferences. Search the General category for `why is the sky blue?`.

[compose.example.yml](compose.example.yml) shows the service wiring. It expects
`overview.yml` and a complete `settings.yml` in the repository root; both paths
are ignored by Git. The settings example is a fragment to merge, not a complete
standalone configuration. Pin your SearXNG image version or digest when deploying.

For a model server running on the Docker host, container `localhost` will not
reach it. The Compose example provides `host.docker.internal`; bind the model
server to an address reachable from the container.

For a non-container installation, install this package into SearXNG's Python
environment and register `ai_overview.plugin.SXNGPlugin` in settings.

## Configure providers

[examples/overview.yml](examples/overview.yml) includes all supported backends.
Use `model_picker: true` to let users choose configured profiles in the panel.
There is no automatic provider fallback.

See the [provider guide](docs/providers.md) for endpoints, output budgets,
reasoning controls, a local Ollama example, and the optional OpenCode Go live
setup. Provider/model availability depends on your account or local installation.

## Privacy and limits

The selected model provider receives the question, selected search snippets,
and conversation context. A hosted provider therefore receives that data even
when SearXNG itself is self-hosted. Local model profiles can keep generation on
your own infrastructure.


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


Public-instance admission controls, full-page retrieval, persistent conversations,
and systematic answer-quality evaluation are not implemented.

## Contributing

See [development and testing](docs/development.md) for local checks, integration
tests, and packaging. Include reproduction steps with bug reports and keep
credentials and private search content out of issues and pull requests.

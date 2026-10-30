# Provider configuration

Run commands from the repository root. Use environment variables for one model
or [examples/overview.yml](../examples/overview.yml) for named profiles. Model IDs
must be available to your provider account or installed on your local server.

## Environment-only configuration

For one model, set environment variables in the SearXNG process or Compose
service instead of mounting `overview.yml`:

| Variable | Purpose |
| --- | --- |
| `AI_OVERVIEW_BACKEND` | Required: `ollama`, `local`, `openai`, `gemini`, `openrouter`, or `opencode_go`. Selects environment mode. |
| `AI_OVERVIEW_MODEL` | Required: exact model ID. |
| `AI_OVERVIEW_ENDPOINT` | Optional endpoint override; defaults are the same as YAML profiles. |
| `AI_OVERVIEW_API_KEY` | Optional key; overrides the backend's standard key variable when set, even if empty. |
| `AI_OVERVIEW_PROTOCOL` | Optional protocol override, such as `anthropic` for a compatible Go model. |
| `AI_OVERVIEW_MAX_OUTPUT_TOKENS` | Positive integer; default 1,200. |
| `AI_OVERVIEW_TIMEOUT_SECONDS` | Positive integer; default 90. |
| `AI_OVERVIEW_READ_TIMEOUT_SECONDS` | Positive integer; default 15. |
| `AI_OVERVIEW_OPTIONS` | JSON object of validated provider options, e.g. `'{"think":false,"num_ctx":8192}'` for Ollama. |
| `AI_OVERVIEW_ANSWER_CACHE_ENTRIES` | Non-negative integer; default 256. `0` disables the answer cache. |
| `AI_OVERVIEW_ANSWER_CACHE_TTL_SECONDS` | Positive integer; default 1,800. |

Hosted backends also read their usual key variables: `OPENAI_API_KEY`,
`GEMINI_API_KEY`, `OPENROUTER_API_KEY`, and `OPENCODE_GO_API_KEY`. An authenticated
local server can use `AI_OVERVIEW_API_KEY`.

An explicit `AI_OVERVIEW_CONFIG` path takes priority over environment mode.
Otherwise setting `AI_OVERVIEW_BACKEND` selects environment mode, even if the
default YAML file exists. Without either, `/etc/searxng/overview.yml` is loaded.
The two sources are never merged; a missing explicit file or invalid environment
setting fails configuration. Restart SearXNG after changing settings.

Environment mode creates one profile named `default` with the model picker off.
Use YAML for multiple profiles, discovery, custom headers, or advanced limits.
The `LLM_*` variable names from AI Answers are not aliases for these settings.

## YAML configuration

Create `overview.yml` in the repository root and mount it alongside the plugin
in your SearXNG service, without setting `AI_OVERVIEW_BACKEND`:

```yaml
volumes:
  - /absolute/path/ai-overview-searxng/overview.yml:/etc/searxng/overview.yml:ro
```

The minimal equivalent of the README's Ollama setup is:

```yaml
default_profile: ollama
profiles:
  ollama:
    backend: ollama
    model: your-installed-model
    endpoint: http://host.docker.internal:11434/api/chat
```

Hosted profiles read their backend's usual key variable from the container
environment; `api_key_env` names a different one. Set `model_picker: true` to
expose the configured profiles under **Summary settings**. Outside a container,
the default path is `/etc/searxng/overview.yml`; point `AI_OVERVIEW_CONFIG`
elsewhere to override it. `overview.yml` and `settings.yml` in the repository
root are ignored by Git.

## Backends and budgets

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
go in validated `options`; supported fields are listed per protocol in
[protocols.py](../src/ai_overview/providers/protocols.py).
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

With `model_picker: false` (the default), the configured default profile is used.
There is no automatic provider fallback.

Set `thinking_control: true` on a profile to add a Thinking choice under the model
picker (it needs `model_picker: true`). Readers pick Default, or a level the
selected model's protocol can express, sent in that protocol's own terms:

| Protocol | Levels | Sent as |
|---|---|---|
| `chat` | Off, Low, Medium, High | `thinking: {type: disabled}`, or `{type: enabled}` with `reasoning_effort` |
| `responses` | Low, Medium, High | `reasoning: {effort}` |
| `anthropic` | Off, Low, Medium, High | `thinking` with a 1,024 / 4,096 / 16,384-token budget |
| `gemini` | Off, Low, Medium, High | `thinkingConfig.thinkingBudget`, the same budgets |
| `ollama` | Off, On | `think` |

A budget is added to the request's output limit, so thinking doesn't eat into the
answer. Planning and suggestion requests on such a profile always use its least
thinking. Only enable it for models that accept these fields; a provider that
rejects them fails the request.

Set `chat_mode: true` to add a Chat entry beside General in the category row. It
turns the results page into a full-width conversation with the AI Summary, and a
search ending in `??` opens straight into it. It is off by default.

In chat mode, each completed answer offers up to three suggested next questions.
They come from one small extra request to the same profile, which sees only the
conversation and that turn's search snippets, and use `planning_max_output_tokens`.
Set `follow_up_suggestions: false` to skip that request.

That request normally starts once the answer is complete. For a provider that
serves requests in parallel, such as a hosted API, set `parallel_suggestions: true`
on the profile to start it alongside the answer while chatting, from the question
and its snippets, so the suggestions are ready when the answer ends. Leave it off
for a local server that runs one request at a time, where it would delay the answer.

## Local Ollama

For an Ollama model you have already installed, configure the profile below.
Replace `your-installed-model` with its exact name from `ollama list`:

```yaml
default_profile: ollama
model_picker: true
profiles:
  ollama:
    backend: ollama
    model: your-installed-model
    endpoint: http://ollama:11434/api/chat
    max_output_tokens: 1200
    planning_max_output_tokens: 512
    timeout_seconds: 240
    read_timeout_seconds: 120
    options:
      num_ctx: 8192
      think: false
```

This endpoint assumes an Ollama service on the same Docker network as SearXNG.
For a host installation, use a reachable host address such as
`host.docker.internal` with the [Compose example](../compose.example.yml).
`options.think` accepts a boolean and is sent as Ollama's top-level `think`
parameter for both answers and follow-up planning. Omit it for models without
thinking support. Disabling thinking avoids spending the output budget on hidden
reasoning. The longer timeouts allow for loading and processing snippets on
modest hardware; actual speed depends on the model and available acceleration.
Keep any existing provider profiles alongside this one to retain them in the picker.

Follow-up planning options apply to the retained conversation API; the current
summary interface does not expose a follow-up input.

## OpenCode Go live instance

For a separate instance with real searches, the model picker, and your Go key:

```sh
uv run python scripts/configure_live.py
docker compose -f compose.live.yml up -d --force-recreate
```

The first command prompts for your key without echoing it. It stores private
configuration in `.local/` (ignored by Git, directory mode 700, files mode 600).
Open <http://127.0.0.1:8898>, search with a trailing `?`, and open **Summary settings**
to choose a model. The integration fixture on port 8899 remains separate. To reuse an
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

Go requests identify this extension honestly and include a stable conversation
session header. Its documentation describes coding-agent traffic as the intended
workload; general search synthesis is not established as supported usage.

# Architecture

## Decision

Build an installable Python package loaded by SearXNG, with separate JavaScript
and CSS assets. Target the Simple theme and Docker Compose. Start with snippets.
The existing instance runs SearXNG revision `e831fc2a1` and already mounts the
reference AI Answers plugin. Develop and test separately before replacing it.

```mermaid
sequenceDiagram
    participant B as Browser
    participant S as SearXNG plugin
    participant G as Generation service
    participant P as Provider adapter
    B->>S: Search ending in ?
    S-->>B: Results + overview shell + signed context
    B->>G: POST /ai-overview/stream
    G->>P: Prompt + selected evidence
    P-->>G: Normalized text events
    G-->>B: Sources, text deltas, signed continuation
    B->>G: Follow-up + signed continuation
    G->>P: Resolve follow-up and decide whether to search
    opt New evidence needed
        G->>S: Internal search, with overview plugin excluded
        S-->>G: Fresh results
    end
    G->>P: Conversation + evidence + question
    G-->>B: Stream next answer with its own citations
```

## Boundaries

- `plugin.py`: SearXNG lifecycle, query eligibility, initial result snapshot,
  and internal follow-up searches. SearXNG imports are confined to this module
  and the SearXNG HTTP transport implementation.
- `web.py`: Flask blueprint, request validation, signed state, streaming response,
  and packaged static assets. Can run in a development app without SearXNG.
- `evidence.py`: normalize and deduplicate HTTP(S) sources; bound snippet context.
- `service.py`: prompt construction, follow-up planning, evidence selection,
  normalized events, and successful conversation updates.
- `providers/`: request translation and incremental response parsing for Chat
  Completions, Responses, Gemini, and Ollama's native chat protocol.
- `config.py`: named profiles, server-side credentials, endpoints, and limits.
- `catalog.py`: cached Go model discovery, documented protocol routes, and
  validation of model choices before signing a new conversation.
- `static/`: framework-free browser component and scoped theme-aware styles.

Use typed dataclasses for profiles, sources, search options, conversations,
turns, messages, and events. Use uv for dependencies, Ruff for formatting,
imports, linting, and required annotations, and ty for static type checks.
Ordinary optional values use `typing.Optional[T]`. Ruff's `UP045` rule is disabled
to preserve this convention. Stream failures currently use typed
exceptions; an Option/Result library has been discussed but not adopted.
Use small explicit interfaces. No agent
framework, vector database, or frontend build pipeline is needed for this scope.

## State and authorization

The initial search creates a short-lived, signed envelope containing the query,
selected sources, search options, profile name, and random conversation ID.
After a successful answer, return a newly signed continuation containing a
bounded transcript and the most recent evidence. Never accept client-supplied
provider settings, source bundles, or assistant history independently of it.

The envelope is readable, not encrypted. It lives in page memory, never the URL
or persistent browser storage. It is a bearer capability and can be replayed
until expiration. Require same-origin JSON requests and bound request size,
turn count, generation time, output size, and per-worker concurrency. This fits
the private-instance target; public deployment would need shared admission
controls. Tokens use a purpose-specific signing salt and a configured secret.

Only complete answers advance conversation state. Cancellation or failure keeps
the last successful continuation for retry. Each displayed turn retains its own
source map; citations cannot silently change when follow-ups retrieve new pages.

## Providers and transport

| Profile backend | Initial protocol |
| --- | --- |
| OpenAI | Responses |
| OpenRouter | Chat Completions |
| Local compatible server | Chat Completions |
| OpenCode Go | Chat Completions, Responses, or Anthropic Messages for the selected model |
| Gemini | Native streamed generateContent |
| Ollama | Native streamed chat |

Profiles declare model IDs explicitly. Extra provider parameters are restricted
so they cannot replace messages, streaming mode, endpoints, or model selection.
Credentials come from environment variable references. No automatic fallback.
Local inference never implicitly contacts a hosted model service.

`model_picker: true` adds a selector. `discover_models: true` on a Go profile
loads the public catalog through the same configured network without sending
API keys. The catalog lacks protocol metadata, so use documented model-to-protocol
mappings plus operator overrides. Unknown routes are disabled. Successful lists
are cached per worker for five minutes; failed refreshes retain old/configured
choices with a warning and a short retry delay.

`POST /ai-overview/models` and `/select` require signed search state and same-origin
requests. Selection is allowed only from initial state and the server's choice
list; it returns a signed model/protocol and fresh conversation ID. The stream
endpoint never accepts an unsigned model or endpoint override. Only the chosen
profile/model preference is persisted in local storage.

HTTP transport is injectable: use SearXNG's network layer in the plugin to retain
its proxy/TLS policy, and HTTPX for standalone development and adapter testing.
SearXNG uses a configured `outgoing.networks.ai_overview` network to support
local HTTP endpoints without enabling HTTP for unrelated engine requests.
Both feed byte chunks into bounded incremental SSE/NDJSON parsers. A provider
must report successful completion; unexpected EOF is an interrupted answer.
Provider payloads and credentials are never included in browser errors.

## Follow-ups and budgets

Initial generation uses the existing search results without another search or
planning request. A follow-up makes a small planning request to the same profile,
asking for a standalone search query or a decision to reuse evidence. This uses
plain JSON text, not model tool calls. Invalid plans fall back to a bounded search
using the original query and follow-up. Limit retrieval to one search per turn.

Use conservative UTF-8 byte budgets for prompt input, plus provider output-token
limits and explicit stream/output bounds. These are not exact tokenizer counts;
the operator must fit the profile to the chosen model. Do not truncate the latest
question or silently remove conversation turns: stop at the configured limit
and invite a new search. Context passed to the model retains source snapshots
for prior turns so old citation numbers remain interpretable.

## Browser contract

Use `fetch` with a POST body and streaming SSE response. Events are `status`,
`sources`, `text_delta`, `done`, and `error`. A `done` event includes the next
signed continuation. AbortController handles Stop and page navigation.

Render model output as text, with validated numeric citations converted to
links. No model-provided HTML or arbitrary Markdown links. Display partial text
on failure with an explicit interrupted/failed status. Screen readers receive
status updates rather than announcements for every token.

Visual direction: inherit SearXNG typography and CSS colors; fallbacks are white
`#ffffff`, text `#222222`, muted text `#555555`, link blue `#3050ff`, and border
`#d8d8d8`. Use a left-aligned reading column and a compact source list. Citations
are the visual emphasis. Avoid decorative cards, animation, and external fonts.

```text
AI overview                                  Collapse
Short answer with citations [1] [2]

Sources (expand for titles and links)
----------------------------------------------------
Ask a follow-up…                                Ask
```

## Build and verification

1. Implement configuration, evidence, signed state, and protocol adapters.
2. Connect the complete overview/follow-up flow to a standalone fixture demo.
3. Add the SearXNG plugin and test against the installed image in isolation.
4. Provide Compose settings, provider examples, and instructions to replace the
   reference plugin once the new integration is ready.

Test fragmented UTF-8/stream frames, normal completion and truncation, timeouts,
token tampering/expiry, empty evidence, source sanitization, follow-up retrieval,
and browser cancellation. Exercise the real SearXNG integration with a local
mock provider before using live credentials. Live provider/model verification
remains separately recorded; fixtures cannot establish account access or answer
quality.

## Sources

- [SearXNG plugin API](https://docs.searxng.org/dev/plugins/development.html)
- [OpenAI streaming](https://developers.openai.com/api/docs/guides/streaming-responses)
- [Gemini generation API](https://ai.google.dev/api/generate-content)
- [Ollama chat API](https://docs.ollama.com/api/chat)
- [OpenRouter chat API](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion)
- [OpenCode Go](https://opencode.ai/docs/go/)

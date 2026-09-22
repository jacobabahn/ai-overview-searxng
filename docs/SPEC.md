# SearXNG AI Overviews — working specification

Historical design draft. This records the initial discussion, not the current
configuration reference. See the [README](../README.md) for supported behavior.

## Intent

Add a useful, source-linked overview to SearXNG search results. Ordinary search
must remain usable while the overview is generated and if generation fails.
The reference project is a source of implementation ideas; matching its feature
set or single-file distribution is not a requirement.

## User direction

- Target a personal/private SearXNG instance.
- Confirmed deployment: Docker Compose with the Simple theme. Start with search
  snippets, with full-page retrieval deferred.
- Use uv, Ruff linting/formatting, type annotations, typed dataclasses, and ty.
- Tentative activation rule: automatically generate when the trimmed query ends
  in `?`. An embedded question mark alone does not trigger generation.
- Include conversational follow-ups in the first version.
- Support OpenCode Go, Ollama, other local model servers, OpenAI, Gemini, and
  OpenRouter in the first version. OpenCode Go remains a backend the user would
  like to use, rather than the sole initial integration.

## Decisions still to make

| Decision | Options | Why it matters |
| --- | --- | --- |
| Default model | Default provider/model and representative models per backend | Determines initial configuration and compatibility testing |

The initial implementation uses an in-process plugin and selective follow-up
retrieval. See [Architecture](ARCHITECTURE.md) for implementation decisions and the
[README](../README.md) for
verification status and installation.

OpenCode Go is one of the requested integrations. Its official documentation
specifies a client-specific user agent and a stable `x-opencode-session` header
per conversation. Keep that identifier stable across initial generation and
follow-ups. Choose the endpoint and stream parser for the selected model's
protocol, rather than assuming all Go models use the same protocol.

The documentation describes Go as intended for coding-agent traffic. General
search synthesis is outside that described use; successful API access should
not be treated as confirmation that the workload is supported. This remains a
provider suitability question, not a reason to couple the product to Go.

## Provider support

All requested providers are first-version scope. Provider selection must not
change overview, citation, or follow-up behavior.

| Backend | Required behavior |
| --- | --- |
| OpenCode Go | Configurable model with conversation session headers and client identification |
| Ollama | Connect to a configured local or remote Ollama server and installed model |
| Other local servers | Support configurable OpenAI-compatible endpoints, such as LM Studio or llama.cpp servers |
| OpenAI | Support a configured API model and server-side credential |
| Gemini | Support a configured API model and server-side credential |
| OpenRouter | Support a configured model identifier and server-side credential |

Here, local model support means connecting to an inference server. Downloading
models, managing inference processes, and hardware configuration are outside
the extension's scope. Compatibility is tested against selected server versions
and models; it is not a promise to support every model or local runtime.

Proposed configuration uses named provider/model profiles with one default.
Each profile specifies the backend, model, optional endpoint override, credential
reference, context budget, output limit, and timeout. Credentials are optional
for local servers that do not require authentication. Custom headers remain
server-side. Provider-specific options are validated by the relevant adapter.

Keep a conversation on the profile/model with which it began. An optional
`model_picker` setting exposes configured profiles and discovered OpenCode Go
models. Switching models starts a new conversation from the original results.
Remember only the selected profile/model in browser storage, never credentials
or conversation text. Do not silently fall back from a local model to a hosted provider, or switch
paid providers after an error. Any fallback policy must be explicitly configured.

Use shared protocol adapters where compatible, with backend-specific mappings
when needed. Select and verify the API protocol for each integration before
implementation. Normalize text streaming, completion, errors, and cancellation
into the application event format. Do not require model tool calling for the
baseline overview and follow-up experience.

## Proposed first-version experience

- An overview panel appears above eligible search results, initially limited to
  the general category and first result page.
- Search results render without waiting for model generation.
- The panel shows a short synthesis, inline source references, and a source list.
- It supports collapse/expand, stop generation, and retry after failure.
- Loading, complete, insufficient evidence, interrupted, and failed states are
  distinguishable. A failed or interrupted answer is never shown as complete.
- The answer follows the search language where practical. Mobile layouts,
  keyboard controls, and the instance's light/dark styling are supported.
- A follow-up input appears within the overview panel. Follow-ups do not require
  a trailing question mark.
- Saved histories and sharing are optional later scope.

Proposed activation semantics: trim surrounding whitespace and check for a
trailing ASCII `?`, while preserving the query sent to SearXNG. Searches without
that suffix make no automatic model request.

## Follow-up behavior (proposed)

Maintain conversation state for the current results page, bounded by a token
budget and turn limit. A new top-level search starts a new conversation.
Persisting conversations across reloads is not required initially.

Use fresh SearXNG retrieval when a follow-up introduces a new topic, constraint,
or factual question. Reuse evidence for purely explanatory or formatting
requests. Resolve references such as "which of those" using conversation context
before constructing a standalone search query. Start with at most one additional
search per follow-up; the exact routing mechanism remains open.

Give each answer its own evidence snapshot so later retrieval cannot renumber or
change earlier citations. Follow-up failures preserve the previous conversation
and offer a retry. Show when a follow-up is searching versus generating.

## Evidence and answer behavior

Start with the results already returned by SearXNG. Deduplicate sources, assign
stable identifiers, and construct a bounded evidence bundle containing titles,
URLs, snippets, and available metadata. Preserve the mapping from identifiers
to the exact sources used for that generation.

Confirmed baseline: snippet-based synthesis. Page extraction would be a separate
retrieval mode with explicit limits on time, number of pages, and content size.
The UI must not imply an article was read when only its snippet was available.

Ask the model to support factual claims with supplied evidence, acknowledge
conflicting sources, and say when evidence is insufficient. Treat source text
as untrusted data. Resolve citation identifiers against the supplied source map;
unknown identifiers must not become fabricated links. Valid identifiers alone
do not establish that a source supports a claim; evaluate that separately using
representative searches.

## Proposed architecture

1. **SearXNG integration:** collect the query and result snapshot; render the
   panel; authorize a subsequent generation request.
2. **Evidence builder:** select and truncate sources within a context budget.
3. **Generation service:** assemble the prompt, enforce generation limits, and
   coordinate streaming and cancellation.
4. **Provider adapters:** translate a common request into backend requests and
   normalize streamed responses and errors.
5. **Browser UI:** consume one application event format and render text and
   validated citations safely.

Adapters should represent protocol families. Endpoint, model, authentication,
and extra headers belong in provider configuration where possible. A new
provider using an existing protocol should not require copying a parser.

Proposed stream events: `sources`, `text_delta`, `done`, and `error`. Define
ordering, interruption behavior, and error payloads before implementation.
Reasoning traces are outside the proposed UI scope.

Keep credentials on the server. Authorize generation against the search context
using a short-lived signed payload or server-side context identifier. Signing
does not encrypt a payload or prevent replay; choose replay/concurrency controls
to fit the deployment audience. Avoid retaining query or answer text by default.

## Initial acceptance criteria

- Slow or unavailable providers do not prevent reading ordinary results.
- Model text and source metadata cannot execute scripts in the results page.
- Citations link only to validated HTTP(S) URLs in the generation's source map.
- An empty evidence bundle produces an explicit insufficient-evidence state.
- Each supported adapter handles fragmented stream frames, upstream errors,
  timeouts, and premature disconnects.
- Each of the six requested backend categories has a documented configuration
  example and a compatibility check using a representative model. Record live
  checks requiring unavailable credentials or hardware as unverified.
- The same overview and follow-up flow works with local and hosted backends;
  provider limits and failures produce clear UI states.
- Local profiles send generation requests only to their configured endpoint;
  they never implicitly fall back to a hosted backend.
- Cancellation closes upstream work where supported; configured time and output
  limits bound remaining work.
- Secrets are absent from browser responses and ordinary logs.
- `why is the sky blue?` and `why is the sky blue?  ` trigger generation;
  `why is the sky blue` and `what? next` do not.
- Follow-ups preserve context, and new evidence cannot alter earlier citations.
- A deployment smoke test verifies result integration and streaming with the
  selected SearXNG version, theme, and reverse proxy.

## Reuse decision

Evaluate the reference's context assembly, endpoint authorization, and citation
UI individually. Do not commit to a fork until the desired behavior and packaging
are settled. Before copying code, establish its license and attribution terms.

## References

- [OpenCode Go documentation](https://opencode.ai/docs/go/)

- [AI Answers for SearXNG](https://github.com/cra88y/ai-answers-searxng)
- [Reference implementation](https://github.com/cra88y/ai-answers-searxng/blob/master/ai_answers.py)
- [SearXNG plugin development](https://docs.searxng.org/dev/plugins/development.html)

The reference describes streaming answers, inline citations, optional follow-ups,
and a post-search integration. Its deep/shallow context settings refer to result
snippets and headlines; they should not be interpreted as full-page retrieval.

# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Anthropic backend.** `backend: anthropic` (or `AI_OVERVIEW_BACKEND=anthropic`)
  calls the Claude API directly with the key in `ANTHROPIC_API_KEY`.
- **Request limits.** Optional `rate_limit` (or `AI_OVERVIEW_RATE_LIMIT_*`)
  limits overviews per reader over a window and for the whole instance per day.
  Cache hits are free. At a limit the panel shows a quiet notice with roughly
  when it resets; search results are unaffected. Readers are told apart by a
  signed browser cookie, else their address. Counts are shared through SearXNG's
  Valkey when it has one, and are per worker otherwise.

### Changed

- The 0.1.0 known limitation "no per-user rate or spending limits" now applies
  only while `rate_limit` is unset, which is still the default. A reader who
  clears cookies gets a new per-reader allowance; `instance_per_day` is the cap
  on the bill.

## [0.1.0] - 2026-11-17

First release. The plugin adds an AI overview to SearXNG: end a search with `?`
and a cited answer streams in above the results, written from the returned
search snippets by a local model or a hosted provider.

### Added

- **Overview for questions.** First-page searches in the General category that
  end in `?` stream a short answer above the results, in the Simple theme's
  light and dark modes and on mobile.
- **Cited sources.** Numbered citations open the search snippet each claim was
  written from. The model receives only the question and the snippets chosen as
  sources.
- **Follow-ups and chat mode.** Readers can ask follow-up questions; each one
  may run a fresh search and keeps its own sources. Answers can be stopped,
  retried, or regenerated. Optional chat mode (`chat_mode: true`) turns the
  results page into a full-width conversation with up to three suggested next
  questions, and a search ending in `??` opens straight into it.
- **Model picker and thinking control.** Optionally let readers choose between
  configured models (`model_picker: true`) and how much the model thinks
  (`thinking_control: true`), sent in each protocol's own terms.
- **Backends.** Ollama, any OpenAI-compatible local server, OpenAI, Gemini,
  OpenRouter, and OpenCode Go. Configure one model with environment variables,
  or several profiles with an `overview.yml`. API keys stay on the server.
- **Answer cache.** Completed first answers are kept in server memory, by
  default for 30 minutes per browser, so repeating a search does not pay for a
  new generation. Regenerate always asks the model again.
- **Markdown and syntax highlighting.** Answers render Markdown with copyable
  code blocks, highlighted for 39 languages. The highlighter and each grammar
  are bundled and loaded from the instance only when an answer contains code.
- **Busy handling.** When a worker is at its limit of simultaneous generations,
  the browser retries a few times before offering a manual Retry.

### Known limitations

- Early-stage software for personal instances. Only the Simple theme is
  supported; other themes are unverified.
- Answers are written from search snippets, not full pages. A citation shows
  which source the model was given; it does not prove the claim is correct.
- Providers are tested against recorded responses, not live against every
  backend and model.
- There are no per-user rate or spending limits, only a per-worker cap on
  simultaneous generations, so a public instance can run up provider costs.
- A hosted provider receives the question and the chosen snippets even when
  SearXNG is self-hosted.

[Unreleased]: https://github.com/jacobabahn/ai-overview-searxng/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jacobabahn/ai-overview-searxng/releases/tag/v0.1.0

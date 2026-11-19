"""Send one short real request to each hosted backend and check the answer streams back.

Each check builds a profile through the same configuration path as overview.yml,
streams one short answer through the plugin's provider adapter, and passes when
text arrives and the stream ends with a completion status. Where a check names a
thinking level, a second request sends that level the way the reader's Thinking
choice would. A backend whose API key variable is unset or empty is skipped.

    uv run python scripts/live_check.py              # every check with a key set
    uv run python scripts/live_check.py gemini       # only the named checks

Exits 1 when a check fails, 2 for an unknown check name, and 0 otherwise, even
when every check was skipped.
"""

import logging
import os
import secrets
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Optional

from ai_overview.config import Config, Profile
from ai_overview.errors import OverviewError
from ai_overview.models import Message
from ai_overview.providers.adapter import Provider
from ai_overview.providers.transport import HTTPXTransport, Transport
from ai_overview.routing import DEFAULTS
from ai_overview.thinking import levels, with_thinking

# A ceiling, not a target: reasoning models spend part of it before answering.
# The prompt asks for one word, so a passing check uses a few dozen tokens.
MAX_OUTPUT_TOKENS = 1024
MESSAGES = [
    Message("system", "Answer with one word and nothing else."),
    Message("user", "Reply with the word: ready"),
]


@dataclass(frozen=True)
class Check:
    name: str
    backend: str
    # The cheapest small model that answers on this backend's protocol.
    model: str
    protocol: Optional[str] = None
    # A level from thinking.LEVELS to send in a second request; None skips it.
    thinking: Optional[str] = None


# Models and prices checked 2026-11-18. On OpenRouter the chat protocol's thinking
# fields follow DeepSeek's API rather than an OpenRouter parameter, so it has no
# thinking request; Go's chat check covers those fields on DeepSeek itself.
CHECKS = (
    Check("openai", "openai", "gpt-5-nano", thinking="low"),
    Check("anthropic", "anthropic", "claude-haiku-5-5", thinking="off"),
    Check("gemini", "gemini", "gemini-2.5-flash-lite", thinking="off"),
    Check("openrouter", "openrouter", "meta-llama/llama-3.1-8b-instruct"),
    Check("opencode_go-chat", "opencode_go", "deepseek-v4.1-flash", "chat", "off"),
    Check("opencode_go-responses", "opencode_go", "gpt-6-luna", "responses", "low"),
    Check("opencode_go-anthropic", "opencode_go", "claude-haiku-5-5", "anthropic", "off"),
)


def key_variable(check: Check) -> str:
    variable = DEFAULTS[check.backend][2]
    assert variable is not None, f"{check.backend} is not a hosted backend"
    return variable


def build_profile(check: Check) -> Profile:
    """The check's profile, validated like an overview.yml profile."""
    raw: dict[str, object] = {
        "backend": check.backend,
        "model": check.model,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "timeout_seconds": 60,
        "read_timeout_seconds": 30,
        "thinking_control": check.thinking is not None,
    }
    if check.protocol is not None:
        raw["protocol"] = check.protocol
    config = Config.from_dict({"default_profile": "live", "profiles": {"live": raw}})
    return config.profiles["live"]


def ask(profile: Profile, transport: Transport) -> str:
    """Stream one answer; the adapter raises unless the stream completes cleanly."""
    session = "live-check-" + secrets.token_hex(8)
    deadline = time.monotonic() + profile.timeout_seconds
    provider = Provider(profile, transport)
    text = "".join(provider.stream(MESSAGES, session, deadline=deadline))
    if not text.strip():
        raise OverviewError("empty", "The stream completed without any answer text.")
    return text


class ProviderReasons(logging.Handler):
    """Keeps what the transport logs about a rejected request, to report with the failure."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    def take(self) -> str:
        messages, self.messages = self.messages, []
        return " ".join(messages)


class Report:
    def __init__(self) -> None:
        self.failed = False
        self.rows: list[str] = []
        self.github = os.environ.get("GITHUB_ACTIONS") == "true"

    def skip(self, check: Check, reason: str) -> None:
        print(f"skip  {check.name}: {reason}")
        if self.github:
            print(f"::notice title=Skipped {check.name}::{reason}")
        self.rows.append(f"| {check.name} | | skipped | {reason} |")

    def result(self, check: Check, label: str, outcome: str, detail: str) -> None:
        print(f"{outcome:<5} {check.name} {label}: {detail}")
        if outcome == "FAIL":
            self.failed = True
            if self.github:
                print(f"::error title=Live check {check.name} failed::{label}: {detail}")
        self.rows.append(f"| {check.name} | {label} | {outcome.lower()} | {detail} |")

    def summary(self) -> None:
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if not path:
            return
        with open(path, "a", encoding="utf-8") as file:
            file.write("| Check | Request | Result | Detail |\n| --- | --- | --- | --- |\n")
            file.write("\n".join(row.replace("\n", " ") for row in self.rows) + "\n")


def run(check: Check, transport: Transport, report: Report, reasons: ProviderReasons) -> None:
    variable = key_variable(check)
    if not os.environ.get(variable):
        report.skip(check, f"{variable} is not set")
        return
    try:
        profile = build_profile(check)
    except ValueError as error:
        report.result(check, check.model, "FAIL", f"configuration rejected: {error}")
        return
    requests = [(check.model, profile)]
    if check.thinking is not None:
        if check.thinking not in levels(profile):
            raise SystemExit(f"{check.name}: {profile.protocol} has no {check.thinking} level")
        requests.append(
            (f"{check.model}, thinking {check.thinking}", with_thinking(profile, check.thinking))
        )
    for label, request_profile in requests:
        started = time.monotonic()
        reasons.take()
        try:
            text = ask(request_profile, transport)
        except OverviewError as error:
            detail = f"{error.code}: {error.message}"
            if said := reasons.take():
                detail += f" ({said})"
            report.result(check, label, "FAIL", detail)
            continue
        seconds = time.monotonic() - started
        shown = " ".join(text.split())[:60]
        report.result(check, label, "pass", f"{shown!r} in {seconds:.1f} s")


def main(argv: Sequence[str], transport: Optional[Transport] = None) -> int:
    known = {check.name for check in CHECKS}
    unknown = [name for name in argv if name not in known]
    if unknown:
        print(f"Unknown check: {', '.join(unknown)}. Choose from: {', '.join(sorted(known))}")
        return 2
    # The transport logs the provider's own reason for a rejected request.
    reasons = ProviderReasons()
    logger = logging.getLogger("ai_overview")
    logger.addHandler(reasons)
    report = Report()
    try:
        for check in CHECKS:
            if not argv or check.name in argv:
                run(check, transport or HTTPXTransport(), report, reasons)
    finally:
        logger.removeHandler(reasons)
    report.summary()
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Offline tests for scripts/live_check.py; no request leaves the process."""

import importlib.util
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

import pytest

from ai_overview.config import Profile
from ai_overview.thinking import levels

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")
KEYS += ("OPENROUTER_API_KEY", "OPENCODE_GO_API_KEY")


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("live_check", ROOT / "scripts/live_check.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


live = load_script()


class GeminiStream:
    """Answers every request with a recorded Gemini stream, complete or cut off."""

    def __init__(self, finish: Optional[str] = "STOP") -> None:
        self.finish = finish
        self.bodies: list[dict[str, Any]] = []

    @contextmanager
    def stream(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        profile: Profile,
        *,
        deadline: Optional[float] = None,
    ) -> Iterator[list[bytes]]:
        self.bodies.append(body)
        candidate: dict[str, Any] = {"content": {"parts": [{"text": "Ready"}]}}
        if self.finish:
            candidate["finishReason"] = self.finish
        yield [b"data: " + json.dumps({"candidates": [candidate]}).encode() + b"\n\n"]


@pytest.fixture(autouse=True)
def no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in KEYS + ("GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("check", live.CHECKS, ids=lambda check: check.name)
def test_each_check_is_a_valid_profile(check: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(live.key_variable(check), "key")
    profile = live.build_profile(check)
    assert profile.api_key == "key"
    assert profile.max_output_tokens == live.MAX_OUTPUT_TOKENS
    if check.thinking is not None:
        assert check.thinking in levels(profile)


def test_every_hosted_backend_is_checked() -> None:
    assert {check.backend for check in live.CHECKS} == {
        "openai",
        "anthropic",
        "gemini",
        "openrouter",
        "opencode_go",
    }
    go = {check.protocol for check in live.CHECKS if check.backend == "opencode_go"}
    assert go == {"chat", "responses", "anthropic"}


def test_without_keys_every_check_is_skipped(capsys: pytest.CaptureFixture[str]) -> None:
    transport = GeminiStream()
    assert live.main([], transport) == 0
    assert transport.bodies == []
    out = capsys.readouterr().out
    assert out.count("skip  ") == len(live.CHECKS)
    assert "OPENCODE_GO_API_KEY is not set" in out


def test_a_completed_stream_passes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    transport = GeminiStream()
    assert live.main(["gemini"], transport) == 0
    (config,) = [body["generationConfig"] for body in transport.bodies]
    assert "thinkingConfig" not in config
    assert config["maxOutputTokens"] == live.MAX_OUTPUT_TOKENS
    assert "pass  gemini gemini-3.5-flash-lite: 'Ready'" in capsys.readouterr().out


def test_a_thinking_level_adds_a_second_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setattr(live, "CHECKS", (live.Check("gemini", "gemini", "m", thinking="low"),))
    transport = GeminiStream()
    assert live.main([], transport) == 0
    configs = [body["generationConfig"] for body in transport.bodies]
    assert "thinkingConfig" not in configs[0]
    assert configs[1]["thinkingConfig"] == {"thinkingBudget": 1024}
    assert configs[1]["maxOutputTokens"] == live.MAX_OUTPUT_TOKENS + 1024
    assert "pass  gemini m, thinking low:" in capsys.readouterr().out


def test_summary_cells_keep_provider_text_in_one_cell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    report = live.Report()
    report.result(live.CHECKS[0], "m", "FAIL", "error (a | b\nc)")
    report.summary()
    row = summary.read_text().splitlines()[-1]
    assert row == "| openai | m | fail | error (a \\| b c) |"


def test_an_unfinished_stream_fails_and_is_reported_to_github(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert live.main([], GeminiStream(finish=None)) == 1
    out = capsys.readouterr().out
    assert "FAIL  gemini gemini-3.5-flash-lite: interrupted" in out
    assert "::error title=Live check gemini failed::" in out
    assert "::notice title=Skipped openai::OPENAI_API_KEY is not set" in out
    assert "| gemini | gemini-3.5-flash-lite | fail |" in summary.read_text()


def test_unknown_check_names_are_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert live.main(["gemini", "claude"], GeminiStream()) == 2
    assert "Unknown check: claude" in capsys.readouterr().out

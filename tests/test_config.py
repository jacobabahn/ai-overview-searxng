import os
from pathlib import Path

import pytest

from ai_overview.config import Config


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in os.environ:
        if name.startswith("AI_OVERVIEW_"):
            monkeypatch.delenv(name)
    monkeypatch.setattr("ai_overview.config.DEFAULT_CONFIG_PATH", tmp_path / "overview.yml")


def write_config(path: Path) -> None:
    path.write_text(
        "default_profile: file\nprofiles:\n  file:\n    backend: local\n    model: file-model\n"
    )


def test_environment_only_local_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_OVERVIEW_BACKEND", "ollama")
    monkeypatch.setenv("AI_OVERVIEW_MODEL", "installed-model")
    monkeypatch.setenv("AI_OVERVIEW_ENDPOINT", "http://host.docker.internal:11434/api/chat")
    monkeypatch.setenv("AI_OVERVIEW_OPTIONS", '{"think": false, "num_ctx": 8192}')
    monkeypatch.setenv("AI_OVERVIEW_MAX_OUTPUT_TOKENS", "1600")
    monkeypatch.setenv("AI_OVERVIEW_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("AI_OVERVIEW_READ_TIMEOUT_SECONDS", "30")
    config = Config.load()
    profile = config.profiles[config.default_profile]
    assert profile.model == "installed-model"
    assert profile.endpoint == "http://host.docker.internal:11434/api/chat"
    assert profile.options == {"think": False, "num_ctx": 8192}
    assert profile.max_output_tokens == 1600
    assert profile.timeout_seconds == 120
    assert profile.read_timeout_seconds == 30
    assert not profile.api_key
    assert not config.model_picker


def test_environment_credentials_and_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_OVERVIEW_BACKEND", "opencode_go")
    monkeypatch.setenv("AI_OVERVIEW_MODEL", "test-model")
    monkeypatch.setenv("AI_OVERVIEW_PROTOCOL", "anthropic")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "provider-secret")
    profile = Config.load().profiles["default"]
    assert profile.endpoint.endswith("/messages")
    assert profile.api_key == "provider-secret"
    monkeypatch.setenv("AI_OVERVIEW_API_KEY", "override-secret")
    config = Config.load()
    assert config.profiles["default"].api_key == "override-secret"
    assert "override-secret" not in repr(config)
    monkeypatch.setenv("AI_OVERVIEW_API_KEY", "")
    assert Config.load().profiles["default"].api_key == ""


def test_file_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    default = tmp_path / "overview.yml"
    write_config(default)
    assert Config.load().default_profile == "file"
    monkeypatch.setenv("AI_OVERVIEW_BACKEND", "ollama")
    monkeypatch.setenv("AI_OVERVIEW_MODEL", "env-model")
    assert Config.load().profiles["default"].model == "env-model"
    monkeypatch.setenv("AI_OVERVIEW_CONFIG", str(default))
    assert Config.load().default_profile == "file"
    monkeypatch.setenv("AI_OVERVIEW_CONFIG", str(tmp_path / "missing.yml"))
    with pytest.raises(FileNotFoundError):
        Config.load()
    assert Config.load(default).default_profile == "file"
    default.write_text("profiles: [invalid yaml")
    with pytest.raises(ValueError, match="Invalid overview YAML"):
        Config.load(default)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AI_OVERVIEW_BACKEND", "unknown"),
        ("AI_OVERVIEW_MODEL", ""),
        ("AI_OVERVIEW_ENDPOINT", "https://user:secret@example.com"),
        ("AI_OVERVIEW_PROTOCOL", "unknown"),
        ("AI_OVERVIEW_MAX_OUTPUT_TOKENS", "0"),
        ("AI_OVERVIEW_TIMEOUT_SECONDS", "-1"),
        ("AI_OVERVIEW_READ_TIMEOUT_SECONDS", "not-a-number"),
        ("AI_OVERVIEW_OPTIONS", "not-json"),
        ("AI_OVERVIEW_OPTIONS", "[]"),
        ("AI_OVERVIEW_OPTIONS", '{"messages": []}'),
        ("AI_OVERVIEW_OPTIONS", '{"think": "false"}'),
    ],
)
def test_invalid_environment_does_not_fall_back_to_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str, value: str
) -> None:
    write_config(tmp_path / "overview.yml")
    monkeypatch.setenv("AI_OVERVIEW_BACKEND", "ollama")
    monkeypatch.setenv("AI_OVERVIEW_MODEL", "test-model")
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        Config.load()


def test_environment_requires_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_OVERVIEW_BACKEND", "ollama")
    with pytest.raises(ValueError, match="explicit model"):
        Config.load()

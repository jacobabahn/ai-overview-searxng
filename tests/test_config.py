import os
from pathlib import Path

import pytest

from ai_overview.config import Config
from ai_overview.limits import RateLimit


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


def test_environment_only_anthropic_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_OVERVIEW_BACKEND", "anthropic")
    monkeypatch.setenv("AI_OVERVIEW_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "provider-secret")
    config = Config.load()
    profile = config.profiles["default"]
    assert profile.backend == "anthropic"
    assert profile.model == "claude-haiku-5-5"
    assert profile.protocol == "anthropic"
    assert profile.endpoint == "https://api.anthropic.com/v1/messages"
    assert profile.api_key == "provider-secret"
    assert profile.api_key_env == "ANTHROPIC_API_KEY"
    assert config.warnings() == []
    assert "provider-secret" not in repr(config)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert Config.load().warnings() == [
        "Profile default has no API key: ANTHROPIC_API_KEY is unset or empty"
    ]


def test_yaml_anthropic_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "provider-secret")
    path = tmp_path / "overview.yml"
    path.write_text(
        "default_profile: claude\n"
        "model_picker: true\n"
        "profiles:\n"
        "  claude:\n"
        "    backend: anthropic\n"
        "    model: claude-sonnet-5-5\n"
        "    thinking_control: true\n"
        "    options:\n"
        "      temperature: 1\n"
    )
    profile = Config.load(path).profiles["claude"]
    assert profile.endpoint == "https://api.anthropic.com/v1/messages"
    assert profile.protocol == "anthropic"
    assert profile.api_key == "provider-secret"
    assert profile.options == {"temperature": 1}
    assert profile.thinking_control


@pytest.mark.parametrize(
    "patch",
    [
        {"protocol": "chat"},
        {"options": {"reasoning": {"effort": "low"}}},
        {"discover_models": True},
    ],
)
def test_anthropic_backend_rejects_other_protocols_and_options(patch: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        Config.from_dict(profile_config(backend="anthropic", **patch))


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
        ("AI_OVERVIEW_ANSWER_CACHE_ENTRIES", "-1"),
        ("AI_OVERVIEW_ANSWER_CACHE_ENTRIES", "many"),
        ("AI_OVERVIEW_ANSWER_CACHE_TTL_SECONDS", "0"),
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


def test_answer_cache_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    base = {"default_profile": "p", "profiles": {"p": {"backend": "local", "model": "m"}}}
    config = Config.from_dict(base)
    assert (config.answer_cache_entries, config.answer_cache_ttl_seconds) == (256, 1800)
    assert Config.from_dict({**base, "answer_cache_entries": 0}).answer_cache_entries == 0
    for invalid in ({"answer_cache_entries": True}, {"answer_cache_ttl_seconds": 0}):
        with pytest.raises(ValueError):
            Config.from_dict({**base, **invalid})
    monkeypatch.setenv("AI_OVERVIEW_BACKEND", "ollama")
    monkeypatch.setenv("AI_OVERVIEW_MODEL", "test-model")
    monkeypatch.setenv("AI_OVERVIEW_ANSWER_CACHE_ENTRIES", "0")
    monkeypatch.setenv("AI_OVERVIEW_ANSWER_CACHE_TTL_SECONDS", "600")
    config = Config.load()
    assert (config.answer_cache_entries, config.answer_cache_ttl_seconds) == (0, 600)


def test_rate_limit_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    base = {"default_profile": "p", "profiles": {"p": {"backend": "local", "model": "m"}}}
    assert Config.from_dict(base).rate_limit == RateLimit()
    assert not Config.from_dict({**base, "rate_limit": None}).rate_limit.enabled
    assert not Config.from_dict({**base, "rate_limit": {}}).rate_limit.enabled
    config = Config.from_dict({**base, "rate_limit": {"instance_per_day": 500}})
    assert config.rate_limit == RateLimit(None, 3600, 500)
    full = {"per_reader": 20, "window_seconds": 600, "instance_per_day": 500}
    assert Config.from_dict({**base, "rate_limit": full}).rate_limit == RateLimit(20, 600, 500)
    for invalid, message in (
        ([20], "rate_limit must be a mapping"),
        ({"per_user": 20}, "Unknown rate_limit field"),
        ({"per_reader": 0}, "rate_limit.per_reader must be a positive integer"),
        ({"window_seconds": "1h"}, "rate_limit.window_seconds must be a positive integer"),
        ({"instance_per_day": True}, "rate_limit.instance_per_day must be a positive integer"),
    ):
        with pytest.raises(ValueError, match=message):
            Config.from_dict({**base, "rate_limit": invalid})
    monkeypatch.setenv("AI_OVERVIEW_BACKEND", "ollama")
    monkeypatch.setenv("AI_OVERVIEW_MODEL", "test-model")
    assert not Config.load().rate_limit.enabled
    monkeypatch.setenv("AI_OVERVIEW_RATE_LIMIT_PER_READER", "20")
    monkeypatch.setenv("AI_OVERVIEW_RATE_LIMIT_WINDOW_SECONDS", "600")
    monkeypatch.setenv("AI_OVERVIEW_RATE_LIMIT_INSTANCE_PER_DAY", "500")
    assert Config.load().rate_limit == RateLimit(20, 600, 500)
    monkeypatch.setenv("AI_OVERVIEW_RATE_LIMIT_PER_READER", "twenty")
    with pytest.raises(ValueError, match="AI_OVERVIEW_RATE_LIMIT_PER_READER must be an integer"):
        Config.load()
    monkeypatch.setenv("AI_OVERVIEW_RATE_LIMIT_PER_READER", "-1")
    with pytest.raises(ValueError, match="rate_limit.per_reader must be a positive integer"):
        Config.load()


def profile_config(**profile: object) -> dict[str, object]:
    return {
        "default_profile": "main",
        "profiles": {"main": {"backend": "local", "model": "test-model", **profile}},
    }


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        "profiles",
        {"default_profile": "main", "profiles": []},
        {"default_profile": "main", "profiles": {"main": "local"}},
        {"default_profile": ["main"], "profiles": profile_config()["profiles"]},
        {**profile_config(), "max_sources": "8"},
        {**profile_config(), 1: 2},
        profile_config(backend=["local"]),
        profile_config(backend={"name": "local"}),
        profile_config(protocol=["chat"]),
        profile_config(backend="opencode_go", protocol=["chat"]),
        profile_config(backend="opencode_go", model_protocols={"some-model": ["chat"]}),
        profile_config(endpoint=8080),
        profile_config(endpoint=["http://localhost:1234"]),
        profile_config(endpoint="http://[::1"),
        profile_config(network=5),
        profile_config(headers=["X-Test"]),
        profile_config(options=["think"]),
        profile_config(model=["test-model"]),
        profile_config(api_key_env=["LOCAL_KEY"]),
        profile_config(api_key="secret"),
        profile_config(unknown=True),
        profile_config(**{"1": 2}),
        {"default_profile": "main", "profiles": {"main": {1: 2, "backend": "local"}}},
    ],
)
def test_malformed_configuration_raises_value_error(data: object) -> None:
    with pytest.raises(ValueError):
        Config.from_dict(data)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "- profiles\n",
        "just text\n",
        "profiles: [unclosed\n",
        "default_profile: main\nprofiles:\n  main:\n    backend: [local]\n    model: m\n",
        "default_profile: main\nprofiles:\n  main:\n    backend: local\n    model: m\n"
        "    endpoint: 8080\n",
        "default_profile: main\nprofiles:\n  main:\n    backend: local\n    model: m\n"
        "    surprise: true\n",
    ],
)
def test_malformed_file_raises_value_error(tmp_path: Path, text: str) -> None:
    path = tmp_path / "overview.yml"
    path.write_text(text)
    with pytest.raises(ValueError):
        Config.load(path)


def test_non_utf8_file_raises_value_error(tmp_path: Path) -> None:
    path = tmp_path / "overview.yml"
    path.write_bytes(b"default_profile: \xff\xfe\n")
    with pytest.raises(ValueError, match="UTF-8"):
        Config.load(path)


def test_missing_file_raises_os_error(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="missing.yml"):
        Config.load(tmp_path / "missing.yml")


def test_endpoint_error_does_not_quote_credentials() -> None:
    with pytest.raises(ValueError) as raised:
        Config.from_dict(profile_config(endpoint="https://user:hunter2secret@[bad/v1"))
    assert "hunter2secret" not in str(raised.value)


def test_warns_about_unset_key_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "present")
    monkeypatch.delenv("MY_LOCAL_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = Config.from_dict(
        {
            "default_profile": "ready",
            "profiles": {
                "ready": {"backend": "openrouter", "model": "m"},
                "defaulted": {"backend": "openai", "model": "m"},
                "empty": {"backend": "gemini", "model": "m"},
                "named": {"backend": "local", "model": "m", "api_key_env": "MY_LOCAL_KEY"},
                "opted_out": {"backend": "openai", "model": "m", "api_key_env": None},
                "claude": {"backend": "anthropic", "model": "m"},
                "ollama": {"backend": "ollama", "model": "m"},
                "local": {"backend": "local", "model": "m"},
            },
        }
    )
    # A missing key does not stop the other profiles from loading.
    assert config.profiles["ready"].api_key == "present"
    assert config.warnings() == [
        "Profile defaulted has no API key: OPENAI_API_KEY is unset or empty",
        "Profile empty has no API key: GEMINI_API_KEY is unset or empty",
        "Profile named has no API key: MY_LOCAL_KEY is unset or empty",
        "Profile opted_out has no API key: api_key_env names no variable",
        "Profile claude has no API key: ANTHROPIC_API_KEY is unset or empty",
    ]


def test_no_key_warning_when_keys_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "present")
    monkeypatch.setenv("AI_OVERVIEW_BACKEND", "openai")
    monkeypatch.setenv("AI_OVERVIEW_MODEL", "m")
    assert Config.load().warnings() == []
    monkeypatch.delenv("OPENAI_API_KEY")
    assert Config.load().warnings() == [
        "Profile default has no API key: OPENAI_API_KEY is unset or empty"
    ]


def test_key_warning_does_not_quote_a_secret_used_as_variable_name() -> None:
    config = Config.from_dict(profile_config(backend="openai", api_key_env="sk-proj-hunter2secret"))
    assert config.warnings() == [
        "Profile main has no API key: its api_key_env variable is unset or empty"
    ]

"""SXNGPlugin.init against stand-ins for the SearXNG modules it imports."""

import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from flask import Flask

SECRET = "a-signing-secret-of-sufficient-length"


@pytest.fixture
def plugin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    class Plugin:
        def __init__(self, plg_cfg: Any) -> None:
            self.log = logging.getLogger("searx.plugins.ai_overview")

    searx: Any = ModuleType("searx")
    searx.settings = {"server": {"secret_key": SECRET}}
    plugins: Any = ModuleType("searx.plugins")
    plugins.Plugin = Plugin
    plugins.PluginInfo = lambda **kwargs: kwargs
    result_types: Any = ModuleType("searx.result_types")
    result_types.Answer = dict
    monkeypatch.setitem(sys.modules, "searx", searx)
    monkeypatch.setitem(sys.modules, "searx.plugins", plugins)
    monkeypatch.setitem(sys.modules, "searx.result_types", result_types)
    monkeypatch.delitem(sys.modules, "ai_overview.plugin", raising=False)
    for name in ("AI_OVERVIEW_BACKEND", "AI_OVERVIEW_SECRET", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AI_OVERVIEW_CONFIG", str(tmp_path / "overview.yml"))

    from ai_overview.plugin import SXNGPlugin

    yield SXNGPlugin(None)
    sys.modules.pop("ai_overview.plugin", None)


def profiles(tmp_path: Path, text: str) -> None:
    (tmp_path / "overview.yml").write_text("default_profile: main\nprofiles:\n" + text)


def test_init_logs_the_configuration_error(
    plugin: Any, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    profiles(tmp_path, "  main:\n    backend: local\n    model: m\n    surprise: true\n")
    assert plugin.init(Flask(__name__)) is False
    assert plugin.service is None
    [record] = caplog.records
    assert record.levelno == logging.ERROR
    assert "Unknown field in profile main" in record.getMessage()


def test_init_survives_wrong_typed_values(
    plugin: Any, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    profiles(tmp_path, "  main:\n    backend: [local]\n    model: m\n")
    assert plugin.init(Flask(__name__)) is False
    assert "Unknown backend in profile main" in caplog.text


def test_init_logs_a_missing_file(plugin: Any, caplog: pytest.LogCaptureFixture) -> None:
    assert plugin.init(Flask(__name__)) is False
    assert "overview.yml" in caplog.text
    assert "No such file" in caplog.text


def test_init_logs_a_weak_secret(
    plugin: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    profiles(tmp_path, "  main:\n    backend: local\n    model: m\n")
    monkeypatch.setenv("AI_OVERVIEW_SECRET", "short")
    assert plugin.init(Flask(__name__)) is False
    assert "signing secret" in caplog.text
    assert "short" not in caplog.text


def test_init_warns_about_a_missing_key_and_still_loads(
    plugin: Any, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    profiles(
        tmp_path,
        "  main:\n    backend: local\n    model: m\n  hosted:\n    backend: openai\n    model: m\n",
    )
    assert plugin.init(Flask(__name__)) is True
    assert plugin.service is not None
    [record] = caplog.records
    assert record.levelno == logging.WARNING
    assert record.getMessage() == (
        "AI overview: Profile hosted has no API key: OPENAI_API_KEY is unset or empty"
    )


def test_init_is_quiet_for_keyless_backends(
    plugin: Any, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    profiles(
        tmp_path,
        "  main:\n    backend: local\n    model: m\n  other:\n    backend: ollama\n    model: m\n",
    )
    assert plugin.init(Flask(__name__)) is True
    assert caplog.records == []

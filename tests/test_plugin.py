"""SXNGPlugin against stand-ins for the SearXNG modules it imports."""

import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
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
    results: Any = ModuleType("searx.results")
    results.calculate_score = calculate_score
    monkeypatch.setitem(sys.modules, "searx", searx)
    monkeypatch.setitem(sys.modules, "searx.plugins", plugins)
    monkeypatch.setitem(sys.modules, "searx.result_types", result_types)
    monkeypatch.setitem(sys.modules, "searx.results", results)
    monkeypatch.delitem(sys.modules, "ai_overview.plugin", raising=False)
    for name in ("AI_OVERVIEW_BACKEND", "AI_OVERVIEW_SECRET", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AI_OVERVIEW_CONFIG", str(tmp_path / "overview.yml"))

    from ai_overview.plugin import SXNGPlugin

    yield SXNGPlugin(None)
    sys.modules.pop("ai_overview.plugin", None)


def calculate_score(result: Any, priority: str) -> float:
    """SearXNG's score for engines of weight 1: the sum of 1/position per engine hit."""
    weight = len(result.positions)
    if priority == "low":
        return 0
    return sum(weight if priority == "high" else weight / p for p in result.positions)


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


class Result:
    """A merged main result as SearXNG keeps it in main_results_map."""

    def __init__(self, name: str, positions: list[int], priority: str = "", **extra: Any) -> None:
        self.url = f"https://example.org/{name}"
        self.title = name
        self.content = f"Snippet about {name}."
        self.positions = positions
        self.priority = priority
        self.__dict__.update(extra)


class Container:
    """The parts of ResultContainer the plugin may touch; closing it is an error."""

    def __init__(self, results: list[Result]) -> None:
        self.main_results_map = {hash(r.url): r for r in results}

    def close(self) -> None:
        raise AssertionError("post_search closed the result container")

    def get_ordered_results(self) -> list[Result]:
        raise AssertionError("post_search closed the result container")


def search_for(query: str, results: list[Result]) -> Any:
    search_query = SimpleNamespace(
        query=query,
        pageno=1,
        categories=["general"],
        lang="en",
        safesearch=0,
        time_range=None,
        engineref_list=[SimpleNamespace(name="fixture", category="general")],
    )
    return SimpleNamespace(search_query=search_query, result_container=Container(results))


@pytest.fixture
def ready(plugin: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    profiles(tmp_path, "  main:\n    backend: local\n    model: m\n")
    assert plugin.init(Flask(__name__)) is True
    states: list[Any] = []
    module = sys.modules["ai_overview.plugin"]
    monkeypatch.setattr(
        module, "render_panel", lambda service, state: states.append(state) or "panel"
    )
    return states


def test_post_search_returns_the_panel_and_leaves_the_container_open(
    plugin: Any, ready: list[Any]
) -> None:
    search = search_for("why is the sky blue?", [Result("sky", [1])])
    request = SimpleNamespace(values={})
    assert plugin.post_search(request, search) == [{"answer": "panel"}]
    [state] = ready
    assert [s.url for s in state.sources] == ["https://example.org/sky"]


def test_post_search_orders_sources_by_score(plugin: Any, ready: list[Any]) -> None:
    results = [
        Result("third", [3]),
        # Two engines found it: 1/2 + 1/4, doubled for the two hits.
        Result("merged", [2, 4]),
        # SearXNG's page pulls a lower result next to an earlier one with the same
        # template and thumbnail presence; sources keep the plain score order.
        Result("thumb-first", [1], thumbnail="https://example.org/t.png"),
        Result("thumb-late", [9], thumbnail="https://example.org/t.png"),
        Result("pinned-low", [1], priority="low"),
        Result("pinned-high", [5], priority="high"),
    ]
    plugin.post_search(SimpleNamespace(values={}), search_for("why?", results))
    [state] = ready
    assert [s.title for s in state.sources] == [
        "merged",
        "thumb-first",
        "pinned-high",
        "third",
        "thumb-late",
        "pinned-low",
    ]


def test_post_search_ignores_ineligible_queries(plugin: Any, ready: list[Any]) -> None:
    search = search_for("sky colour", [Result("sky", [1])])
    assert plugin.post_search(SimpleNamespace(values={}), search) == []
    assert ready == []

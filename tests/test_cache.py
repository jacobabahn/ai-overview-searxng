import pytest

from ai_overview.cache import AnswerCache


def test_entries_expire(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    monkeypatch.setattr("ai_overview.cache.time.monotonic", lambda: clock[0])
    cache = AnswerCache(entries=2, ttl_seconds=60)
    cache.put("a", "answer")
    clock[0] += 59
    assert cache.get("a") == "answer"
    clock[0] += 1
    assert cache.get("a") is None


def test_least_recently_used_entry_is_evicted() -> None:
    cache = AnswerCache(entries=2, ttl_seconds=60)
    cache.put("a", "A")
    cache.put("b", "B")
    assert cache.get("a") == "A"
    cache.put("c", "C")
    assert cache.get("b") is None
    assert cache.get("a") == "A"
    assert cache.get("c") == "C"

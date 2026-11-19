from datetime import UTC, datetime
from typing import Any

import pytest

from ai_overview.errors import OverviewError
from ai_overview.limits import KEY_PREFIX, Limiter, MemoryCounter, RateLimit, ValkeyCounter

SECRET = "s" * 32
# 2026-11-18 21:00 UTC: three hours before the instance's day resets.
EVENING = datetime(2026, 11, 18, 21, 0, tzinfo=UTC).timestamp()


class Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def limiter(clock: Clock, wall: float = EVENING, **limits: Any) -> Limiter:
    return Limiter(RateLimit(**limits), SECRET, MemoryCounter(clock), now=lambda: wall)


def refused(limiter: Limiter, reader: str) -> str:
    with pytest.raises(OverviewError) as caught:
        limiter.admit(reader)
    assert caught.value.code == "rate_limited"
    return caught.value.message


def test_limits_are_off_by_default() -> None:
    assert not RateLimit().enabled
    assert RateLimit(per_reader=1).enabled
    assert RateLimit(instance_per_day=1).enabled


def test_each_reader_gets_its_own_window() -> None:
    clock = Clock()
    limits = limiter(clock, per_reader=2, window_seconds=3600)
    limits.admit("alice")
    limits.admit("alice")
    clock.now += 1200
    assert refused(limits, "alice") == (
        "You’ve reached the AI Summary limit for now. Try again in about 40 minutes."
    )
    # A refused turn does not push the reset back, and another reader is unaffected.
    assert "in about 40 minutes" in refused(limits, "alice")
    limits.admit("bob")
    clock.now += 2400
    limits.admit("alice")


def test_the_instance_cap_stops_everyone_until_utc_midnight() -> None:
    clock = Clock()
    limits = limiter(clock, instance_per_day=2)
    limits.admit("alice")
    limits.admit("bob")
    assert refused(limits, "carol") == (
        "AI Summary has reached today’s limit on this instance. Try again in about 3 hours."
    )
    limits = Limiter(
        RateLimit(instance_per_day=2), SECRET, limits.counter, now=lambda: EVENING + 3 * 3600
    )
    limits.admit("carol")


def test_a_turn_the_instance_refuses_does_not_count_for_the_reader() -> None:
    clock = Clock()
    counter = MemoryCounter(clock)
    full = Limiter(
        RateLimit(per_reader=2, instance_per_day=1), SECRET, counter, now=lambda: EVENING
    )
    full.admit("alice")
    for _ in range(3):
        assert "this instance" in refused(full, "bob")
    # The next day bob still has both of his turns.
    tomorrow = Limiter(
        RateLimit(per_reader=2, instance_per_day=5), SECRET, counter, now=lambda: EVENING + 86400
    )
    tomorrow.admit("bob")
    tomorrow.admit("bob")
    assert "You’ve reached" in refused(tomorrow, "bob")


def test_a_reader_over_its_limit_does_not_spend_the_instance_cap() -> None:
    limits = limiter(Clock(), per_reader=1, instance_per_day=2)
    limits.admit("alice")
    for _ in range(5):
        assert "You’ve reached" in refused(limits, "alice")
    limits.admit("bob")


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (5, "in about a minute"),
        (60, "in about a minute"),
        (61, "in about 2 minutes"),
        (3540, "in about 59 minutes"),
        (3600, "in about an hour"),
        (5400, "in about 2 hours"),
        (20 * 3600, "in about 20 hours"),
    ],
)
def test_reset_times_are_rounded_for_reading(seconds: int, text: str) -> None:
    clock = Clock()
    limits = limiter(clock, per_reader=1, window_seconds=seconds)
    limits.admit("alice")
    assert refused(limits, "alice").endswith(f"Try again {text}.")


def test_the_browser_cookie_is_signed_and_the_address_is_the_fallback() -> None:
    limits = limiter(Clock(), per_reader=1)
    cookie = limits.new_reader_cookie()
    reader, known = limits.reader(cookie, "192.0.2.1")
    assert known and reader.startswith("browser:")
    assert limits.reader(cookie, "198.51.100.7") == (reader, True)
    assert limits.new_reader_cookie() != cookie
    other = Limiter(RateLimit(per_reader=1), "o" * 32)
    for forged in (None, "", "browser-chosen", cookie[:-2] + "xx", other.new_reader_cookie()):
        assert limits.reader(forged, "192.0.2.1") == ("address:192.0.2.1", False)
    assert limits.reader(None, None) == ("address:unknown", False)


def test_an_ipv6_reader_is_its_64_network() -> None:
    limits = limiter(Clock(), per_reader=1)
    first, _ = limits.reader(None, "2001:db8:1:2::1")
    assert first == limits.reader(None, "2001:db8:1:2:ffff::9")[0] == "address:2001:db8:1:2::/64"
    limits.admit(first)
    assert "You’ve reached" in refused(limits, limits.reader(None, "2001:db8:1:2::abcd")[0])
    limits.admit(limits.reader(None, "2001:db8:1:3::1")[0])


def test_memory_counters_forget_expired_readers() -> None:
    clock = Clock()
    counter = MemoryCounter(clock)
    for name in ("a", "b", "c"):
        counter.hit(name, 30)
    clock.now += 61
    counter.hit("d", 30)
    assert set(counter._items) == {"d"}


class FakeValkey:
    """Enough of a Valkey client for the commands ValkeyCounter sends."""

    def __init__(self) -> None:
        self.data: dict[str, list[int]] = {}
        self.now = 0
        self.commands: list[tuple[Any, ...]] = []

    def pipeline(self, transaction: bool) -> "FakeValkey":
        assert transaction
        self.queued: list[Any] = []
        return self

    def set(self, key: str, value: int, ex: int, nx: bool) -> None:
        self.commands.append(("set", key, value, ex, nx))
        self.queued.append(lambda: self.data.setdefault(key, [value, self.now + ex * 1000]))

    def incr(self, key: str) -> None:
        def incr() -> int:
            self.data[key][0] += 1
            return self.data[key][0]

        self.queued.append(incr)

    def pttl(self, key: str) -> None:
        self.queued.append(lambda: self.data[key][1] - self.now)

    def execute(self) -> list[Any]:
        return [step() for step in self.queued]

    def eval(self, script: str, keys: int, key: str) -> None:
        assert "EXISTS" in script and keys == 1
        if key in self.data:
            self.data[key][0] -= 1


def test_valkey_counters_expire_with_their_window() -> None:
    client = FakeValkey()
    counter = ValkeyCounter(client)
    assert counter.hit("reader:x", 3600) == (1, 3600.0)
    client.now += 1000
    assert counter.hit("reader:x", 3600) == (2, 3599.0)
    assert client.commands[0] == ("set", KEY_PREFIX + "reader:x", 0, 3600, True)
    counter.undo("reader:x")
    assert client.data[KEY_PREFIX + "reader:x"][0] == 1
    counter.undo("reader:gone")
    assert KEY_PREFIX + "reader:gone" not in client.data


def test_valkey_holds_a_limit_across_workers() -> None:
    client = FakeValkey()
    workers = [
        Limiter(RateLimit(per_reader=2), SECRET, ValkeyCounter(client), now=lambda: EVENING)
        for _ in range(2)
    ]
    workers[0].admit("alice")
    workers[1].admit("alice")
    assert "You’ve reached" in refused(workers[0], "alice")
    # Keys hold a keyed hash, never the cookie or the address itself.
    assert not any("alice" in key for key in client.data)


def test_a_failing_store_falls_back_to_memory(caplog: pytest.LogCaptureFixture) -> None:
    class Down:
        def hit(self, key: str, ttl_seconds: int) -> tuple[int, float]:
            raise ConnectionError("refused")

        def undo(self, key: str) -> None:
            raise ConnectionError("refused")

    limits = Limiter(RateLimit(per_reader=1), SECRET, Down(), now=lambda: EVENING)
    limits.admit("alice")
    assert "You’ve reached" in refused(limits, "alice")
    assert "Request limit store failed (ConnectionError); counting in memory" in caplog.text

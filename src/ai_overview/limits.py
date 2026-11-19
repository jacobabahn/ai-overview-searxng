"""Request limits: generations per reader over a window, and an instance-wide daily cap.

Only generations that call the provider are counted; cache hits and the requests
that ride on a turn (follow-up planning, suggestions) are not. Counters live in
SearXNG's Valkey when it has one, so every worker shares them; otherwise each
worker counts in its own memory.
"""

import hashlib
import hmac
import ipaddress
import logging
import math
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any, Optional, Protocol

from itsdangerous import BadData, URLSafeSerializer

from .errors import OverviewError

log = logging.getLogger(__name__)

READER_COOKIE = "ai_overview_reader"
# Browsers cap cookie lifetimes at about 400 days.
READER_COOKIE_SECONDS = 365 * 24 * 3600
_READER_ID = re.compile(r"[0-9a-f]{32}")
# SearXNG's own Valkey keys share this prefix, so its purge drops these too.
KEY_PREFIX = "SearXNG_ai_overview_limit_"
_UNDO = "if redis.call('EXISTS', KEYS[1]) == 1 then return redis.call('DECR', KEYS[1]) end return 0"


@dataclass(frozen=True, slots=True)
class RateLimit:
    """Off unless `per_reader` or `instance_per_day` is set."""

    per_reader: Optional[int] = None
    window_seconds: int = 3600
    instance_per_day: Optional[int] = None

    @property
    def enabled(self) -> bool:
        return bool(self.per_reader or self.instance_per_day)


class Counter(Protocol):
    def hit(self, key: str, ttl_seconds: int) -> tuple[int, float]:
        """Add one to `key`, starting it with `ttl_seconds` to live if new.

        Returns the new count and the seconds until the key resets.
        """
        ...

    def undo(self, key: str) -> None:
        """Take back one hit on `key`."""
        ...


class MemoryCounter:
    """Counters in this worker's memory; each worker keeps its own."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._items: dict[str, list[float]] = {}
        self._lock = Lock()
        self._next_sweep = 0.0

    def hit(self, key: str, ttl_seconds: int) -> tuple[int, float]:
        now = self._clock()
        with self._lock:
            if now >= self._next_sweep:
                # Expired readers are dropped once a minute, so memory follows the window.
                self._items = {k: v for k, v in self._items.items() if v[1] > now}
                self._next_sweep = now + 60
            item = self._items.get(key)
            if item is None or item[1] <= now:
                item = self._items[key] = [0, now + ttl_seconds]
            item[0] += 1
            return int(item[0]), item[1] - now

    def undo(self, key: str) -> None:
        with self._lock:
            item = self._items.get(key)
            if item and item[0] > 0:
                item[0] -= 1


class ValkeyCounter:
    """Counters in SearXNG's Valkey, shared by every worker."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def hit(self, key: str, ttl_seconds: int) -> tuple[int, float]:
        pipe = self.client.pipeline(transaction=True)
        # Creating the key with its expiry in one command means a crash between
        # commands can never leave a counter that lives forever.
        pipe.set(KEY_PREFIX + key, 0, ex=ttl_seconds, nx=True)
        pipe.incr(KEY_PREFIX + key)
        pipe.pttl(KEY_PREFIX + key)
        _, count, pttl = pipe.execute()
        return int(count), max(0, int(pttl)) / 1000

    def undo(self, key: str) -> None:
        # DECR on a key that just expired would recreate it without an expiry.
        self.client.eval(_UNDO, 1, KEY_PREFIX + key)


class Limiter:
    def __init__(
        self,
        limits: RateLimit,
        secret: str,
        counter: Optional[Counter] = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.limits = limits
        self.counter = counter or MemoryCounter()
        self._fallback = MemoryCounter()
        self._now = now
        self._key = hashlib.sha256(f"ai-overview-limit:{secret}".encode()).digest()
        self._cookies = URLSafeSerializer(secret, salt="searxng-ai-overview-reader-v1")

    @property
    def per_reader(self) -> bool:
        return bool(self.limits.per_reader)

    def new_reader_cookie(self) -> str:
        """A signed, random browser identity the browser cannot choose for itself."""
        value = self._cookies.dumps(secrets.token_hex(16))
        return value if isinstance(value, str) else value.decode()

    def reader(self, cookie: Optional[str], address: Optional[str]) -> tuple[str, bool]:
        """The reader to count, and whether it is a browser rather than an address.

        A valid signed cookie names the browser; without one (cookies blocked,
        cleared, or forged) the client address SearXNG resolved stands in.
        """
        if cookie:
            try:
                value = self._cookies.loads(cookie)
            except BadData:
                value = None
            if isinstance(value, str) and _READER_ID.fullmatch(value):
                return f"browser:{value}", True
        return f"address:{_network(address)}", False

    def admit(self, reader: str) -> None:
        """Count one generation for `reader`, or raise `rate_limited` at a limit."""
        counted: Optional[tuple[Counter, str]] = None
        if self.limits.per_reader:
            key = "reader:" + self._digest(reader)
            counter, count, reset = self._hit(key, self.limits.window_seconds)
            counted = (counter, key)
            if count > self.limits.per_reader:
                raise OverviewError(
                    "rate_limited",
                    f"You’ve reached the AI Summary limit for now. Try again {_when(reset)}.",
                )
        if self.limits.instance_per_day:
            today = datetime.fromtimestamp(self._now(), UTC)
            midnight = datetime.combine(today.date() + timedelta(days=1), datetime.min.time(), UTC)
            ttl = max(1, math.ceil((midnight - today).total_seconds()))
            _, count, reset = self._hit(f"instance:{today.date().isoformat()}", ttl)
            if count > self.limits.instance_per_day:
                # A turn the instance refused is not the reader's to pay for.
                if counted:
                    _undo(*counted)
                raise OverviewError(
                    "rate_limited",
                    f"AI Summary has reached today’s limit on this instance. Try again {_when(reset)}.",
                )

    def _digest(self, reader: str) -> str:
        # Addresses and cookie IDs are stored only as keyed hashes.
        return hmac.new(self._key, reader.encode(), hashlib.sha256).hexdigest()[:32]

    def _hit(self, key: str, ttl: int) -> tuple[Counter, int, float]:
        try:
            return self.counter, *self.counter.hit(key, ttl)
        except Exception as error:
            # A shared store that fails falls back to this worker's memory, so the
            # limits still hold, per worker, instead of switching off.
            log.warning("Request limit store failed (%s); counting in memory", type(error).__name__)
            return self._fallback, *self._fallback.hit(key, ttl)


def _undo(counter: Counter, key: str) -> None:
    try:
        counter.undo(key)
    except Exception as error:
        log.warning("Request limit store failed (%s)", type(error).__name__)


def _network(address: Optional[str]) -> str:
    """An IPv4 address, or the /64 an IPv6 address is in: one household or host."""
    try:
        ip = ipaddress.ip_address(address or "")
    except ValueError:
        return "unknown"
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def _when(seconds: float) -> str:
    minutes = max(1, math.ceil(seconds / 60))
    if minutes == 1:
        return "in about a minute"
    if minutes < 60:
        return f"in about {minutes} minutes"
    hours = round(minutes / 60)
    return "in about an hour" if hours == 1 else f"in about {hours} hours"

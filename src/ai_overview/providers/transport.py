import json
import time
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import replace
from typing import Any, Optional, Protocol

from ..config import Profile
from ..errors import OverviewError


def check_status(status: int) -> None:
    if 200 <= status < 300:
        return
    if status in {401, 403}:
        raise OverviewError(
            "provider_auth", "The provider rejected access. Check its configuration."
        )
    if status == 429:
        raise OverviewError(
            "provider_limit", "The provider is busy or its usage limit was reached."
        )
    raise OverviewError("provider_error", "The provider could not complete this request.")


def bounded(chunks: Iterable[bytes], deadline: float) -> Iterator[bytes]:
    for chunk in chunks:
        if time.monotonic() > deadline:
            raise OverviewError("timeout", "Generation took too long. Try again.")
        if isinstance(chunk, Exception):
            raise OverviewError("connection", "The provider connection was interrupted.")
        if chunk:
            yield chunk


class HTTPXTransport:
    def stream(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        profile: Profile,
    ) -> AbstractContextManager[Iterable[bytes]]:
        return self._request("POST", url, headers, body, profile)

    def get_json(self, url: str, profile: Profile) -> dict[str, Any]:
        # The Go catalog is public. Never send credentials to discovery requests.
        with self._request(
            "GET",
            url,
            {"User-Agent": "searxng-ai-overview/0.1.0"},
            None,
            replace(profile, timeout_seconds=10, read_timeout_seconds=10),
        ) as chunks:
            return read_catalog(chunks)

    @contextmanager
    def _request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: Optional[dict[str, Any]],
        profile: Profile,
    ) -> Iterator[Iterable[bytes]]:
        import httpx

        deadline = time.monotonic() + profile.timeout_seconds
        timeout = httpx.Timeout(profile.read_timeout_seconds, connect=10)
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                with client.stream(
                    method, url, headers=headers, **({"json": body} if body is not None else {})
                ) as response:
                    check_status(response.status_code)
                    yield bounded(response.iter_bytes(), deadline)
        except httpx.TimeoutException:
            raise OverviewError(
                "timeout", "The provider did not respond in time. Try again."
            ) from None
        except httpx.HTTPError:
            raise OverviewError("connection", "Could not connect to the provider.") from None


class SearXNGTransport:
    def stream(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        profile: Profile,
    ) -> AbstractContextManager[Iterable[bytes]]:
        return self._request("POST", url, headers, body, profile)

    def get_json(self, url: str, profile: Profile) -> dict[str, Any]:
        # The Go catalog is public. Never send credentials to discovery requests.
        with self._request(
            "GET",
            url,
            {"User-Agent": "searxng-ai-overview/0.1.0"},
            None,
            replace(profile, timeout_seconds=10, read_timeout_seconds=10),
        ) as chunks:
            return read_catalog(chunks)

    @contextmanager
    def _request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: Optional[dict[str, Any]],
        profile: Profile,
    ) -> Iterator[Iterable[bytes]]:
        from searx import network  # ty: ignore[unresolved-import]

        response = None
        previous_network = network.get_context_network()
        deadline = time.monotonic() + profile.timeout_seconds
        try:
            network.set_context_network_name(profile.network)
            response, chunks = network.stream(
                method,
                url,
                headers=headers,
                **({"json": body} if body is not None else {}),
                timeout=profile.read_timeout_seconds,
                allow_redirects=False,
                # SearXNG's stream helper defaults to raw compressed image bytes.
                # Ask for identity so JSON/SSE arrive as readable application data.
                accept_encoding="identity",
            )
            check_status(response.status_code)
            yield bounded(chunks, deadline)
        except OverviewError:
            raise
        except Exception:
            # Network libraries can put request URLs or credentials in exceptions.
            raise OverviewError(
                "connection", "The provider connection failed or timed out."
            ) from None
        finally:
            try:
                if response is not None:
                    response.close()
            finally:
                network.THREADLOCAL.network = previous_network


class Transport(Protocol):
    def stream(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        profile: Profile,
    ) -> AbstractContextManager[Iterable[bytes]]: ...


def read_catalog(chunks: Iterable[bytes]) -> dict[str, Any]:
    data = bytearray()
    for chunk in chunks:
        data.extend(chunk)
        if len(data) > 1_000_000:
            raise OverviewError("catalog", "The provider model list exceeded its size limit.")
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError):
        raise OverviewError("catalog", "The provider returned an invalid model list.") from None
    if not isinstance(value, dict):
        raise OverviewError("catalog", "The provider returned an invalid model list.")
    return value

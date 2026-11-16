"""Public model choices and server-validated selection; never expose credentials."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from threading import Lock
from typing import Any, Optional

from .config import Config, Profile
from .errors import OverviewError
from .models import Conversation
from .routing import go_root, model_protocol
from .state import new_session
from .thinking import levels

log = logging.getLogger(__name__)

FetchCatalog = Callable[[str, Profile], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ModelChoice:
    profile: str
    model: str
    protocol: str
    # Thinking levels a reader may choose with this model, quickest first.
    thinking_levels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CatalogResult:
    choices: tuple[ModelChoice, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CachedModels:
    expires_at: float
    choices: tuple[ModelChoice, ...]
    warning: Optional[str] = None


class ModelCatalog:
    def __init__(
        self,
        config: Config,
        fetch: Optional[FetchCatalog] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.fetch = fetch
        self.clock = clock
        self._cache: dict[str, CachedModels] = {}
        # One lock per profile, held by whichever request is refreshing that profile.
        self._refreshing: dict[str, Lock] = {}
        # Guards the two dictionaries above only; never held across a fetch.
        self._lock = Lock()

    def list(self) -> CatalogResult:
        choices: list[ModelChoice] = []
        warnings: list[str] = []
        for name, profile in self.config.profiles.items():
            if not profile.discover_models:
                choices.append(self._default(name, profile))
                continue
            entry = self._models(name, profile)
            choices.extend(entry.choices)
            if entry.warning:
                warnings.append(entry.warning)
        return CatalogResult(tuple(choices), tuple(warnings))

    @staticmethod
    def _default(name: str, profile: Profile) -> ModelChoice:
        return ModelChoice(name, profile.model, profile.protocol, levels(profile))

    def _models(self, name: str, profile: Profile) -> CachedModels:
        with self._lock:
            cached = self._cache.get(name)
            refreshing = self._refreshing.setdefault(name, Lock())
        if cached and cached.expires_at > self.clock():
            return cached
        # One request refreshes an expired entry; the others keep serving it meanwhile.
        # With nothing saved yet there is nothing to serve, so they wait for that fetch.
        if cached is None:
            refreshing.acquire()
        elif not refreshing.acquire(blocking=False):
            return cached
        try:
            with self._lock:
                cached = self._cache.get(name)
            # Another request may have refreshed the entry before this one got its turn.
            if cached and cached.expires_at > self.clock():
                return cached
            entry = self._refresh(name, profile, cached)
            with self._lock:
                self._cache[name] = entry
            return entry
        finally:
            refreshing.release()

    def _refresh(self, name: str, profile: Profile, cached: Optional[CachedModels]) -> CachedModels:
        default = self._default(name, profile)
        try:
            models = self._discover(name, profile)
        except OverviewError:
            models = cached.choices if cached else (default,)
            warning = f"Could not refresh models for {name}; showing saved choices."
            return CachedModels(self.clock() + 15, models, warning)
        warning = None
        # Retain the operator's configured model when the catalog omits it,
        # but say so: a retired default otherwise fails as a generic error.
        if not any(m.model == profile.model for m in models):
            models = (default, *models)
            warning = (
                f"{profile.model} is no longer in the {name} model list; "
                "update the configured model."
            )
            log.warning("Configured model %s for %s is not in the catalog", profile.model, name)
        return CachedModels(self.clock() + 300, models, warning)

    def _discover(self, name: str, profile: Profile) -> tuple[ModelChoice, ...]:
        if self.fetch is None:
            raise OverviewError("configuration", "Model discovery is unavailable.")
        body = self.fetch(go_root(profile.endpoint) + "models", profile)
        items = body.get("data")
        if not isinstance(items, list) or not items:
            raise OverviewError("catalog", "The provider returned an invalid model list.")
        models: dict[str, ModelChoice] = {}
        for item in items[:500]:
            if not isinstance(item, dict):
                continue
            model = item.get("id")
            if not isinstance(model, str) or not model or len(model) > 200:
                continue
            protocol = model_protocol(profile, model)
            models[model] = ModelChoice(name, model, protocol, levels(profile, protocol))
        if not models:
            raise OverviewError("catalog", "The provider returned an empty model list.")
        return tuple(models[k] for k in sorted(models))

    def select(
        self, state: Conversation, name: object, model: object, thinking: object = None
    ) -> Conversation:
        if not self.config.model_picker:
            raise OverviewError("invalid_request", "The model picker is disabled.")
        if state.turns:
            raise OverviewError(
                "invalid_request",
                "Switch models from the original search to start a new conversation.",
            )
        if not isinstance(name, str) or not isinstance(model, str):
            raise OverviewError("invalid_request", "Choose an available model.")
        choice = next(
            (c for c in self.list().choices if c.profile == name and c.model == model),
            None,
        )
        if choice is None:
            raise OverviewError("invalid_request", "Choose an available model.")
        if thinking is not None and thinking not in choice.thinking_levels:
            raise OverviewError("invalid_request", "Choose a thinking level this model offers.")
        return replace(
            state,
            session=new_session(),
            profile=name,
            model=model,
            protocol=choice.protocol,
            thinking=thinking,
        )

"""Public model choices and server-validated selection; never expose credentials."""

import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from threading import Lock
from typing import Any, Optional

from .config import Config, Profile
from .errors import OverviewError
from .models import Conversation
from .routing import go_root, model_protocol

FetchCatalog = Callable[[str, Profile], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ModelChoice:
    profile: str
    model: str
    protocol: Optional[str]
    available: bool


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
    def __init__(self, config: Config, fetch: Optional[FetchCatalog] = None) -> None:
        self.config = config
        self.fetch = fetch
        self._cache: dict[str, CachedModels] = {}
        self._lock = Lock()

    def list(self) -> CatalogResult:
        choices: list[ModelChoice] = []
        warnings: list[str] = []
        with self._lock:
            for name, profile in self.config.profiles.items():
                default = ModelChoice(name, profile.model, profile.protocol, True)
                if not profile.discover_models:
                    choices.append(default)
                    continue
                cached = self._cache.get(name)
                if cached and cached.expires_at > time.monotonic():
                    choices.extend(cached.choices)
                    if cached.warning:
                        warnings.append(cached.warning)
                    continue
                try:
                    models = self._discover(name, profile)
                    # Retain the operator's configured model when the catalog omits it.
                    if not any(m.model == profile.model for m in models):
                        models = (default, *models)
                    self._cache[name] = CachedModels(time.monotonic() + 300, models)
                    choices.extend(models)
                except OverviewError:
                    models = cached.choices if cached else (default,)
                    choices.extend(models)
                    warning = f"Could not refresh models for {name}; showing saved choices."
                    warnings.append(warning)
                    self._cache[name] = CachedModels(time.monotonic() + 15, models, warning)
        return CatalogResult(tuple(choices), tuple(warnings))

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
            models[model] = ModelChoice(name, model, protocol, protocol is not None)
        if not models:
            raise OverviewError("catalog", "The provider returned an empty model list.")
        return tuple(models[k] for k in sorted(models))

    def select(self, state: Conversation, name: object, model: object) -> Conversation:
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
            (
                c
                for c in self.list().choices
                if c.profile == name and c.model == model and c.available
            ),
            None,
        )
        if choice is None:
            raise OverviewError("invalid_request", "Choose an available model.")
        import secrets

        return replace(
            state,
            session=secrets.token_hex(16),
            profile=name,
            model=model,
            protocol=choice.protocol,
        )

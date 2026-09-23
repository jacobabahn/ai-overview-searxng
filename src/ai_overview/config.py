import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Self
from urllib.parse import urlsplit

import yaml

from .routing import DEFAULTS, EXTRA_OPTIONS, SUFFIXES, go_endpoint

DEFAULT_CONFIG_PATH = Path("/etc/searxng/overview.yml")


@dataclass(frozen=True, slots=True)
class Profile:
    backend: str
    model: str
    endpoint: str
    protocol: str
    api_key: str = field(default="", repr=False)
    headers: dict[str, str] = field(default_factory=dict, repr=False)
    options: dict[str, Any] = field(default_factory=dict)
    max_output_tokens: int = 1200
    planning_max_output_tokens: int = 1200
    max_input_bytes: int = 48000
    max_output_bytes: int = 16000
    timeout_seconds: int = 90
    read_timeout_seconds: int = 15
    network: str = "ai_overview"
    discover_models: bool = False
    model_protocols: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Config:
    default_profile: str
    profiles: dict[str, Profile]
    max_sources: int = 8
    evidence_bytes: int = 12000
    max_turns: int = 6
    token_ttl_seconds: int = 1800
    max_concurrent: int = 2
    model_picker: bool = False

    @classmethod
    def load(cls, path: Optional[str | Path] = None) -> Self:
        if path is None:
            path = os.getenv("AI_OVERVIEW_CONFIG")
            if path is None and "AI_OVERVIEW_BACKEND" in os.environ:
                return cls.from_environment()
            if path is None:
                path = DEFAULT_CONFIG_PATH
        with open(path, encoding="utf-8") as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError:
                raise ValueError("Invalid overview YAML") from None
        return cls.from_dict(data)

    @classmethod
    def from_environment(cls) -> Self:
        """Build one profile through the same validation used for YAML."""
        profile: dict[str, Any] = {
            "backend": os.getenv("AI_OVERVIEW_BACKEND", ""),
            "model": os.getenv("AI_OVERVIEW_MODEL", ""),
        }
        for field_name in ("endpoint", "protocol"):
            name = "AI_OVERVIEW_" + field_name.upper()
            if name in os.environ:
                profile[field_name] = os.environ[name]
        if "AI_OVERVIEW_API_KEY" in os.environ:
            profile["api_key_env"] = "AI_OVERVIEW_API_KEY"
        for field_name in ("max_output_tokens", "timeout_seconds", "read_timeout_seconds"):
            name = "AI_OVERVIEW_" + field_name.upper()
            if name in os.environ:
                try:
                    profile[field_name] = int(os.environ[name])
                except ValueError:
                    raise ValueError(f"{name} must be a positive integer") from None
        if "AI_OVERVIEW_OPTIONS" in os.environ:
            try:
                profile["options"] = json.loads(os.environ["AI_OVERVIEW_OPTIONS"])
            except ValueError:
                raise ValueError("AI_OVERVIEW_OPTIONS must be a JSON object") from None
        return cls.from_dict({"default_profile": "default", "profiles": {"default": profile}})

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        if not isinstance(data, dict):
            raise ValueError("Overview configuration must be a mapping")
        allowed = set(cls.__dataclass_fields__)
        if set(data) - allowed:
            raise ValueError("Unknown overview configuration field")
        raw_profiles = data.get("profiles")
        if not isinstance(raw_profiles, dict) or not raw_profiles:
            raise ValueError("Configure at least one profile")
        profiles = {}
        for name, raw in raw_profiles.items():
            if not isinstance(name, str) or not name or not isinstance(raw, dict):
                raise ValueError("Invalid provider profile")
            fields = set(Profile.__dataclass_fields__) - {"api_key"}
            if set(raw) - (fields | {"api_key_env"}):
                raise ValueError(f"Unknown field in profile {name}")
            backend = raw.get("backend")
            if backend not in DEFAULTS:
                raise ValueError(f"Unknown backend in profile {name}")
            protocol, endpoint, key_env = DEFAULTS[backend]
            values = dict(raw)
            key_env = values.pop("api_key_env", key_env)
            if key_env is not None and not isinstance(key_env, str):
                raise ValueError("api_key_env must be an environment variable name")
            values.setdefault("protocol", protocol)
            values.setdefault("endpoint", endpoint)
            if type(values.get("discover_models", False)) is not bool:
                raise ValueError("discover_models must be a boolean")
            if values.get("discover_models") and backend != "opencode_go":
                raise ValueError("Model discovery currently supports OpenCode Go")
            routes = values.get("model_protocols", {})
            if not isinstance(routes, dict) or not all(
                isinstance(k, str) and v in SUFFIXES for k, v in routes.items()
            ):
                raise ValueError("model_protocols must map model IDs to supported Go protocols")
            # Initial configuration and later selections use the same endpoint rules.
            if backend == "opencode_go":
                if values["protocol"] not in SUFFIXES:
                    raise ValueError("Unsupported Go protocol")
                if "endpoint" not in raw:
                    values["endpoint"] = go_endpoint(endpoint, values["protocol"])
            if not isinstance(values.get("model"), str) or not values["model"].strip():
                raise ValueError(f"Set an explicit model in profile {name}")
            if values["protocol"] not in EXTRA_OPTIONS:
                raise ValueError(f"Unknown protocol in profile {name}")
            if backend == "gemini" and values["protocol"] != "gemini":
                raise ValueError("The Gemini backend requires the gemini protocol")
            if backend == "ollama" and values["protocol"] != "ollama":
                raise ValueError("The Ollama backend requires the ollama protocol")
            url = urlsplit(values["endpoint"])
            if url.scheme not in {"http", "https"} or not url.hostname or url.username:
                raise ValueError("Provider endpoint must be an HTTP(S) URL without credentials")
            if url.query or url.fragment:
                raise ValueError("Provider endpoints must not contain queries or fragments")
            for field_name in (
                "max_output_tokens",
                "planning_max_output_tokens",
                "max_input_bytes",
                "max_output_bytes",
                "timeout_seconds",
                "read_timeout_seconds",
            ):
                if field_name in values:
                    _positive(values[field_name], field_name)
            headers = values.get("headers", {})
            options = values.get("options", {})
            if not isinstance(headers, dict) or not all(
                isinstance(k, str)
                and isinstance(v, str)
                and "\n" not in k + v
                and "\r" not in k + v
                for k, v in headers.items()
            ):
                raise ValueError("Profile headers must contain plain strings")
            if any(k.lower() in {"host", "content-length", "transfer-encoding"} for k in headers):
                raise ValueError("Transport headers cannot be overridden")
            if not isinstance(options, dict) or set(options) - EXTRA_OPTIONS[values["protocol"]]:
                raise ValueError(f"Unsupported provider option in profile {name}")
            if values["protocol"] == "ollama" and "think" in options:
                if type(options["think"]) is not bool:
                    raise ValueError("Ollama think must be a boolean")
            if values["protocol"] == "chat" and "thinking" in options:
                thinking = options["thinking"]
                if (
                    not isinstance(thinking, dict)
                    or set(thinking) != {"type"}
                    or thinking["type"] not in ("enabled", "disabled")
                ):
                    raise ValueError("Chat thinking must contain type: enabled or disabled")
            values["api_key"] = os.getenv(key_env, "") if key_env else ""
            profiles[name] = Profile(**values)
        default = data.get("default_profile")
        if default not in profiles:
            raise ValueError("default_profile must name a configured profile")
        other = {k: v for k, v in data.items() if k not in {"default_profile", "profiles"}}
        for k, v in other.items():
            if k == "model_picker":
                if type(v) is not bool:
                    raise ValueError("model_picker must be a boolean")
            else:
                _positive(v, k)
        if other.get("max_sources", 8) > 30 or other.get("max_turns", 6) > 12:
            raise ValueError("At most 30 sources and 12 turns are supported")
        if other.get("evidence_bytes", 12000) > 24000:
            raise ValueError("Evidence budget cannot exceed 24000 bytes")
        return cls(default, profiles, **other)


def _positive(value: Any, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")

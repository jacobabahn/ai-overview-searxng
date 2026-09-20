"""Prepare a private live test; prompt without echo or reuse a container's Go key."""

import argparse
import getpass
import json
import os
import secrets
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def private_write(path: Path, content: str) -> None:
    # Create with restricted permissions before writing secrets.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        os.fchmod(file.fileno(), 0o600)
        file.write(content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-container", help="Reuse its Go key and search settings without printing secrets"
    )
    args = parser.parse_args()
    directory = ROOT / ".local"
    settings: dict[str, Any] = {"use_default_settings": True}
    if (directory / "settings.yml").exists() and not args.from_container:
        settings = yaml.safe_load((directory / "settings.yml").read_text())
    if args.from_container:
        result = subprocess.run(
            ["docker", "inspect", args.from_container],
            check=True,
            capture_output=True,
            text=True,
        )
        env = dict(item.split("=", 1) for item in json.loads(result.stdout)[0]["Config"]["Env"])
        key = env.get("OPENCODE_GO_API_KEY", "")
        if not key:
            raise SystemExit(
                "That container has no OPENCODE_GO_API_KEY; run without --from-container to enter one."
            )
        config = subprocess.run(
            ["docker", "exec", args.from_container, "cat", "/etc/searxng/settings.yml"],
            check=True,
            capture_output=True,
            text=True,
        )
        original = yaml.safe_load(config.stdout)
        for name in ("use_default_settings", "search", "engines", "outgoing"):
            if name in original:
                settings[name] = original[name]
    else:
        key = getpass.getpass("OpenCode Go API key (hidden): ").strip()
    if not key or any(c.isspace() for c in key) or "'" in key:
        raise SystemExit("Enter a nonempty API key without whitespace or quotes.")
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    settings["general"] = {"instance_name": "AI overview live test"}
    settings["server"] = {
        "secret_key": secrets.token_hex(32),
        "limiter": False,
        "image_proxy": False,
    }
    settings["ui"] = {"default_theme": "simple"}
    settings["plugins"] = {"ai_overview.plugin.SXNGPlugin": {"active": True}}
    settings.setdefault("outgoing", {}).setdefault("networks", {})["ai_overview"] = {
        "enable_http": False,
        "retries": 0,
    }
    overview = {
        "default_profile": "opencode",
        "model_picker": True,
        "profiles": {
            "opencode": {
                "backend": "opencode_go",
                "model": "deepseek-v4-flash",
                "discover_models": True,
                "api_key_env": "OPENCODE_GO_API_KEY",
                "max_output_tokens": 4096,
                "planning_max_output_tokens": 4096,
                "read_timeout_seconds": 60,
                "timeout_seconds": 150,
            }
        },
    }
    private_write(directory / "provider.env", f"OPENCODE_GO_API_KEY='{key}'\n")
    private_write(directory / "settings.yml", yaml.safe_dump(settings, sort_keys=False))
    if not (directory / "overview.yml").exists():
        private_write(directory / "overview.yml", yaml.safe_dump(overview, sort_keys=False))
    print("Saved private configuration under .local/. No key was printed.")
    print("Start or apply changes: docker compose -f compose.live.yml up -d --force-recreate")
    print("Open http://127.0.0.1:8898 and search with a trailing question mark.")


if __name__ == "__main__":
    main()

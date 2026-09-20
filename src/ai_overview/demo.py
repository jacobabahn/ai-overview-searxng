"""Local fixture demo: no search engine or model account needed."""

import json
import secrets
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any, Optional

from flask import Flask

from .config import Config, Profile
from .evidence import build_sources
from .models import SearchOptions, Source
from .service import GenerationService
from .state import StateSigner, initial_state
from .web import register, render_panel

FIXTURES = [
    {
        "title": "Why is the sky blue? — NASA Space Place",
        "url": "https://spaceplace.nasa.gov/blue-sky/en/",
        "content": "Air molecules scatter shorter blue wavelengths of sunlight more strongly than longer red wavelengths.",
    },
    {
        "title": "Rayleigh scattering",
        "url": "https://en.wikipedia.org/wiki/Rayleigh_scattering",
        "content": "Rayleigh scattering is stronger at shorter wavelengths. At sunset sunlight travels through more atmosphere.",
    },
]


class FixtureTransport:
    @contextmanager
    def stream(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        profile: Profile,
        *,
        deadline: Optional[float] = None,
    ) -> Iterator[Iterable[bytes]]:
        def chunks() -> Iterator[bytes]:
            messages = body.get("messages", body.get("input", []))
            planning = messages and "Plan retrieval" in messages[0]["content"]
            text = (
                '{"query":null}'
                if planning
                else (
                    "The sky looks blue because air molecules scatter blue light more strongly "
                    "than red light. That scattered blue light reaches your eyes from across the sky. [1]\n\n"
                    "At sunset, sunlight travels through more air. Much of its blue light has scattered "
                    "away, leaving warmer red and orange colors. [2]"
                )
            )
            for start in range(0, len(text), 12):
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "choices": [
                                {
                                    "delta": {"content": text[start : start + 12]},
                                    "finish_reason": None,
                                }
                            ]
                        }
                    )
                    + "\n\n"
                ).encode()
                time.sleep(0.025)
            yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'

        yield chunks()


def create_app() -> Flask:
    app = Flask(__name__)
    config = Config.from_dict(
        {"default_profile": "demo", "profiles": {"demo": {"backend": "local", "model": "fixture"}}}
    )
    sources = build_sources(FIXTURES)

    def retrieve(query: str, options: SearchOptions, timeout: float) -> tuple[Source, ...]:
        return sources

    service = GenerationService(
        config, StateSigner(secrets.token_hex(32)), FixtureTransport(), retrieve
    )
    register(app, service)

    @app.get("/")
    def index() -> str:
        panel = render_panel(service, initial_state("Why is the sky blue?", sources, "demo"))
        return f"""<!doctype html><html lang="en"><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>AI overview fixture demo</title>
        <body style="font-family:system-ui;margin:2rem auto;padding:0 1rem;max-width:760px">
        <h1>Why is the sky blue?</h1><p>Fixture demo — answers are prerecorded.</p>
        {panel}<hr><h2>Search results</h2><p>Ordinary results remain available below the overview.</p>
        </body></html>"""

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=8765, threaded=True)

"""The only integration module tied to SearXNG's Python interfaces."""

import os
from typing import Any, Optional

from flask import Flask
from searx import settings  # ty: ignore[unresolved-import]
from searx.plugins import Plugin, PluginInfo  # ty: ignore[unresolved-import]
from searx.result_types import Answer  # ty: ignore[unresolved-import]
from searx.results import calculate_score  # ty: ignore[unresolved-import]

from .catalog import ModelCatalog
from .config import Config
from .evidence import build_sources, eligible
from .models import Engine, SearchOptions, Source
from .providers.transport import SearXNGTransport
from .service import GenerationService
from .state import StateSigner, initial_state
from .web import register, render_panel


class SXNGPlugin(Plugin):
    id = "ai_overview"

    def __init__(self, plg_cfg: Any) -> None:
        super().__init__(plg_cfg)
        self.info = PluginInfo(
            id=self.id,
            name="AI overview",
            description="Stream a cited overview for searches ending in a question mark.",
        )
        self.service: Optional[GenerationService] = None

    def init(self, app: Flask) -> bool:
        try:
            config = Config.load()
            secret = os.getenv("AI_OVERVIEW_SECRET") or settings["server"]["secret_key"]
            signer = StateSigner(secret, config.token_ttl_seconds)
            transport = SearXNGTransport()
            self.service = GenerationService(config, signer, transport, self.retrieve)
            register(app, self.service, ModelCatalog(config, transport.get_json))
        except (OSError, ValueError) as error:
            # Config and signer messages name files, profiles and fields, never secrets.
            self.log.error("AI overview configuration failed: %s", error)
            return False
        for warning in config.warnings():
            self.log.warning("AI overview: %s", warning)
        return True

    def post_search(self, request: Any, search: Any) -> list[Any]:
        service = self.service
        if service is None:
            return []
        query = search.search_query
        output_format = request.values.get("format", "html")
        if not eligible(query.query, query.pageno, query.categories, output_format):
            return []
        try:
            sources = build_sources(
                ranked_results(search.result_container),
                service.config.max_sources,
                service.config.evidence_bytes,
            )
            options = SearchOptions(
                lang=query.lang,
                safesearch=query.safesearch,
                time_range=query.time_range,
                engines=tuple(Engine(e.name, e.category) for e in query.engineref_list),
            )
            state = initial_state(query.query, sources, service.config.default_profile, options)
            return [Answer(answer=render_panel(service, state))]
        except Exception as error:
            self.log.warning("Could not prepare AI overview (%s)", type(error).__name__)
            return []

    def retrieve(self, query: str, options: SearchOptions, timeout: float) -> tuple[Source, ...]:
        from searx.search import Search  # ty: ignore[unresolved-import]
        from searx.search.models import EngineRef, SearchQuery  # ty: ignore[unresolved-import]

        # Reuse the original engine selection and filters. Plain Search skips plugin
        # execution, so this cannot recursively create another overview.
        sq = SearchQuery(
            query=query,
            engineref_list=[EngineRef(e.name, e.category) for e in options.engines],
            lang=options.lang,
            safesearch=options.safesearch,
            time_range=options.time_range,
            pageno=1,
            timeout_limit=min(10, timeout),
        )
        container = Search(sq).search()
        # A plain Search leaves its container open and nothing else reads it;
        # closing it records the engines' score counters once, as for any search.
        container.close()
        assert self.service is not None
        return build_sources(
            ranked_results(container),
            self.service.config.max_sources,
            self.service.config.evidence_bytes,
        )


def ranked_results(container: Any) -> list[Any]:
    """Main results by SearXNG's score, best first, leaving the container open.

    SearchWithPlugins closes the container after every plugin's post_search, and
    closing is not idempotent: get_ordered_results() would close it early, so
    later plugins' results would be dropped and engine score counters added
    twice. This skips get_ordered_results()'s display pass, which pulls results
    of the same category, template and thumbnail presence next to each other.
    """
    # Engine threads that timed out may still add results; list() takes one snapshot.
    results = list(container.main_results_map.values())
    # Stable on ties, like SearXNG's own sort of the same map.
    return sorted(results, key=lambda r: calculate_score(r, r.priority), reverse=True)

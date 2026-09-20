"""The only integration module tied to SearXNG's Python interfaces."""

import os
from typing import Any, Optional

from flask import Flask
from searx import settings  # ty: ignore[unresolved-import]
from searx.plugins import Plugin, PluginInfo  # ty: ignore[unresolved-import]
from searx.result_types import Answer  # ty: ignore[unresolved-import]

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
            config = Config.load(os.getenv("AI_OVERVIEW_CONFIG", "/etc/searxng/overview.yml"))
            secret = os.getenv("AI_OVERVIEW_SECRET") or settings["server"]["secret_key"]
            signer = StateSigner(secret, config.token_ttl_seconds)
            self.service = GenerationService(config, signer, SearXNGTransport(), self.retrieve)
            register(app, self.service, ModelCatalog(config, SearXNGTransport().get_json))
        except (OSError, ValueError) as error:
            self.log.error("AI overview configuration failed (%s)", type(error).__name__)
            return False
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
                search.result_container.get_ordered_results(),
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
            # get_ordered_results() closes the result container in the target
            # SearXNG version; a returned result would then be silently ignored.
            search.result_container.answers.add(Answer(answer=render_panel(service, state)))
            return []
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
        results = Search(sq).search().get_ordered_results()
        assert self.service is not None
        return build_sources(
            results, self.service.config.max_sources, self.service.config.evidence_bytes
        )

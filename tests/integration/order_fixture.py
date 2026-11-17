"""A second plugin whose post_search answer must survive the overview plugin.

SearXNG keeps plugins in a set, so the order in which their post_search hooks
run is arbitrary. This fixture fixes the worst case for the overview plugin:
every other plugin runs first and this one runs last, after ai_overview.
"""

from typing import Any

import searx.plugins  # ty: ignore[unresolved-import]
from searx.plugins import Plugin, PluginInfo  # ty: ignore[unresolved-import]
from searx.result_types import Answer  # ty: ignore[unresolved-import]

ANSWER = "Answer from the plugin that runs after the overview."


class _RunLast(set[Any]):
    """The storage's plugin set, iterated with this fixture last."""

    def __iter__(self) -> Any:
        items: list[Any] = list(super().__iter__())
        return iter(sorted(items, key=lambda plugin: getattr(plugin, "id", "") == OrderFixture.id))


class OrderFixture(Plugin):
    id = "order_fixture"

    def __init__(self, plg_cfg: Any) -> None:
        super().__init__(plg_cfg)
        self.info = PluginInfo(
            id=self.id, name="Order fixture", description="Integration test only."
        )

    def init(self, app: Any) -> bool:
        storage = searx.plugins.STORAGE
        storage.plugin_list = _RunLast(storage.plugin_list)
        return True

    def post_search(self, request: Any, search: Any) -> list[Any]:
        if "plugin-order" not in search.search_query.query:
            return []
        return [Answer(answer=ANSWER)]

import json
import secrets
from dataclasses import asdict
from typing import Optional

from itsdangerous import BadData, URLSafeTimedSerializer

from .errors import OverviewError
from .models import Conversation, SearchOptions, Source

MAX_STATE_BYTES = 220000


class StateSigner:
    def __init__(self, secret: str, ttl: int = 1800) -> None:
        if not secret or secret == "ultrasecretkey" or len(secret) < 24:
            raise ValueError("Configure a signing secret of at least 24 characters")
        self.serializer = URLSafeTimedSerializer(secret, salt="searxng-ai-overview-v1")
        self.ttl = ttl

    def dumps(self, state: Conversation) -> str:
        data = asdict(state)
        if len(json.dumps(data, ensure_ascii=False).encode()) > MAX_STATE_BYTES:
            raise OverviewError("context_limit", "This conversation is full. Start a new search.")
        return self.serializer.dumps(data)

    def loads(self, token: object) -> Conversation:
        if not isinstance(token, str) or not token or len(token) > MAX_STATE_BYTES:
            raise OverviewError("invalid_state", "This overview has expired. Run the search again.")
        try:
            state = self.serializer.loads(token, max_age=self.ttl)
        except BadData:
            raise OverviewError(
                "invalid_state", "This overview has expired. Run the search again."
            ) from None
        if not isinstance(state, dict) or state.get("v") != 1:
            raise OverviewError("invalid_state", "Run the search again to start an overview.")
        try:
            return Conversation.from_dict(state)
        except (KeyError, TypeError, ValueError):
            raise OverviewError(
                "invalid_state", "Run the search again to start an overview."
            ) from None


def initial_state(
    query: str,
    sources: tuple[Source, ...],
    profile: str,
    search_options: Optional[SearchOptions] = None,
) -> Conversation:
    return Conversation(
        session=secrets.token_hex(16),
        profile=profile,
        query=query.strip(),
        sources=sources,
        search=search_options or SearchOptions(),
    )

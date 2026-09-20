from dataclasses import dataclass, field
from typing import Any, Literal, Optional


@dataclass(frozen=True, slots=True)
class Source:
    id: int
    url: str
    title: str
    snippet: str


@dataclass(frozen=True, slots=True)
class Engine:
    name: str
    category: str


@dataclass(frozen=True, slots=True)
class SearchOptions:
    lang: str = "all"
    safesearch: Literal[0, 1, 2] = 0
    time_range: Optional[Literal["day", "week", "month", "year"]] = None
    engines: tuple[Engine, ...] = ()


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class Turn:
    question: str
    answer: str
    sources: tuple[Source, ...]


@dataclass(frozen=True, slots=True)
class Conversation:
    session: str
    profile: str
    query: str
    sources: tuple[Source, ...]
    search: SearchOptions = field(default_factory=SearchOptions)
    turns: tuple[Turn, ...] = ()
    v: int = 1
    model: Optional[str] = None
    protocol: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Conversation":
        """Decode only after verifying the server signature."""
        options = dict(data["search"])
        options["engines"] = tuple(Engine(**e) for e in options["engines"])
        return cls(
            session=data["session"],
            profile=data["profile"],
            query=data["query"],
            sources=tuple(Source(**s) for s in data["sources"]),
            search=SearchOptions(**options),
            turns=tuple(
                Turn(
                    question=t["question"],
                    answer=t["answer"],
                    sources=tuple(Source(**s) for s in t["sources"]),
                )
                for t in data["turns"]
            ),
            v=data["v"],
            model=data.get("model"),
            protocol=data.get("protocol"),
        )


@dataclass(frozen=True, slots=True)
class Event:
    name: Literal["status", "sources", "text_delta", "done", "error"]
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Plan:
    query: Optional[str]

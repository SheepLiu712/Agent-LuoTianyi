"""Validated output of the fast call-memory routing decision."""

from dataclasses import dataclass
from enum import Enum


class RecallMode(str, Enum):
    DIRECT = "direct"
    RECALL = "recall"


class AckStyle(str, Enum):
    NONE = "none"
    THINKING = "thinking"
    EMPATHY = "empathy"
    CONFIRMING = "confirming"


@dataclass(frozen=True, slots=True)
class CallRecallDecision:
    mode: RecallMode
    memory_queries: tuple[str, ...]
    ack_style: AckStyle

    def __post_init__(self) -> None:
        queries = tuple(query.strip() for query in self.memory_queries if query.strip())
        if len(queries) != len(set(queries)):
            raise ValueError("memory_queries must be unique")
        object.__setattr__(self, "memory_queries", queries)

        if self.mode is RecallMode.DIRECT:
            if queries or self.ack_style is not AckStyle.NONE:
                raise ValueError("DIRECT requires no memory queries and no acknowledgement")
            return
        if not queries:
            raise ValueError("RECALL requires at least one memory query")
        if self.ack_style is AckStyle.NONE:
            raise ValueError("RECALL requires a provisional acknowledgement style")

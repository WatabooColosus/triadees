from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .salience import SalienceVector


@dataclass(slots=True)
class WorkingMemoryItem:
    text: str
    source: str
    salience: SalienceVector
    timestamp: float = field(default_factory=time.time)
    access_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text[:120],
            "source": self.source,
            "salience": self.salience.to_dict(),
            "timestamp": self.timestamp,
            "age_seconds": int(time.time() - self.timestamp),
            "access_count": self.access_count,
        }


@dataclass(slots=True)
class WorkingMemory:
    max_size: int = 10
    _items: list[WorkingMemoryItem] = field(default_factory=list, init=False)

    def push(self, text: str, source: str, salience: SalienceVector) -> None:
        item = WorkingMemoryItem(text=text, source=source, salience=salience)
        self._items.append(item)
        self._prune()

    def get_relevant(self, min_relevance: float = 0.0, limit: int = 5) -> list[WorkingMemoryItem]:
        sorted_items = sorted(
            [it for it in self._items if it.salience.relevance >= min_relevance],
            key=lambda x: (x.salience.relevance, x.timestamp),
            reverse=True,
        )
        for item in sorted_items[:limit]:
            item.access_count += 1
        return sorted_items[:limit]

    def peek(self) -> list[WorkingMemoryItem]:
        return list(self._items)

    def touch(self, index: int) -> None:
        if 0 <= index < len(self._items):
            self._items[index].access_count += 1

    def clear(self) -> None:
        self._items.clear()

    def get_context(self, max_chars: int = 2000) -> str:
        relevant = self.get_relevant(min_relevance=0.05, limit=self.max_size)
        parts = []
        for item in relevant:
            label = item.source.replace("_", " ").title()
            parts.append(f"[{label} (saliencia={item.salience.relevance:.2f})]: {item.text[:200]}")
        text = "\n".join(parts)
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
        return text

    def _prune(self) -> None:
        if len(self._items) <= self.max_size:
            return
        self._items.sort(key=lambda x: (x.salience.relevance, x.timestamp), reverse=True)
        self._items = self._items[:self.max_size]

    def doctor(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "size": len(self._items),
            "max_size": self.max_size,
            "items": [it.to_dict() for it in self._items[-5:]],
            "context_preview": self.get_context(max_chars=500),
        }

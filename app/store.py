"""In-memory context, conversation, and suppression store for Vera."""

from __future__ import annotations

import time
from typing import Any, Optional

SCOPES = ("category", "merchant", "customer", "trigger")

_DEFAULT_META: dict[str, Any] = {
    "auto_reply_count": 0,
    "is_closed": False,
    "opted_out": False,
    "last_sent_body": None,
}


class ContextStore:
    """Stateful in-memory store for judge-pushed context and live conversations."""

    def __init__(self) -> None:
        self.started_at: float = time.time()
        # Aliased attribute to prevent AttributeError regardless of naming convention in main.py
        self.start_time: float = self.started_at
        self.contexts: dict[tuple[str, str], dict] = {}
        self.conversations: dict[str, list[dict]] = {}
        self.conversation_meta: dict[str, dict] = {}
        self.suppressed_keys: set[str] = set()

    def uptime_seconds(self) -> int:
        return int(time.time() - self.started_at)

    def upsert_context(
        self,
        scope: str,
        context_id: str,
        version: int,
        payload: dict,
    ) -> tuple[bool, Optional[int]]:
        key = (scope, context_id)
        existing = self.contexts.get(key)
        if existing is not None and existing["version"] >= version:
            return False, existing["version"]
        self.contexts[key] = {"version": version, "payload": payload}
        return True, None

    def get_context(self, scope: str, context_id: str) -> Optional[dict]:
        entry = self.contexts.get((scope, context_id))
        if entry is None:
            return None
        return entry["payload"]

    def get_counts(self) -> dict[str, int]:
        counts = {scope: 0 for scope in SCOPES}
        for scope, _context_id in self.contexts:
            if scope in counts:
                counts[scope] += 1
        return counts

    def add_turn(self, conversation_id: str, role: str, message: str, turn: int) -> None:
        # Includes both "message" and "msg" keys so callers looking for either work seamlessly
        self.conversations.setdefault(conversation_id, []).append(
            {"role": role, "message": message, "msg": message, "turn": turn}
        )

    def get_history(self, conversation_id: str) -> list[dict]:
        return list(self.conversations.get(conversation_id, []))

    def mark_suppressed(self, key: str) -> None:
        self.suppressed_keys.add(key)

    def is_suppressed(self, key: str) -> bool:
        return key in self.suppressed_keys

    def get_meta(self, conversation_id: str) -> dict:
        if conversation_id not in self.conversation_meta:
            self.conversation_meta[conversation_id] = dict(_DEFAULT_META)
        return self.conversation_meta[conversation_id]

    def update_meta(self, conversation_id: str, **kwargs: Any) -> None:
        meta = self.get_meta(conversation_id)
        meta.update(kwargs)


store = ContextStore()
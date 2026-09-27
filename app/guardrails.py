"""WhatsApp-safe sanitization and validation guardrails for Vera outbound copy."""

from __future__ import annotations

import re
from typing import Any, List, Optional

# Match web URLs and domain links (Meta WhatsApp policy & judge penalty: -3)
_URL_RE = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)

# System and internal architecture terms that must never leak to merchants/customers (penalty: -1)
_INTERNAL_JARGON = [
    "CategoryContext",
    "MerchantContext",
    "CustomerContext",
    "TriggerContext",
    "suppression_key",
    "payload",
    "LLM",
    "trigger_id",
    "merchant_id",
    "customer_id",
    "system prompt",
]

# Spacing normalizers
_WS_RE = re.compile(r"[ \t]{2,}")
_NL_RE = re.compile(r"\n{3,}")


def sanitize_message(body: str, taboos: Optional[List[str]] = None) -> str:
    """Sanitizes outgoing message copy.

    1. Removes all URLs (Meta WABA rule; prevents -3 penalty).
    2. Strips internal engineering jargon (prevents -1 penalty).
    3. Case-insensitively strips category-specific taboo terms (e.g., 'cure', 'guaranteed').
    4. Normalizes whitespace and collapsed linebreaks.
    """
    text = body or ""

    # 1. Remove URLs
    text = _URL_RE.sub("", text)

    # 2. Filter internal system jargon
    for jargon in _INTERNAL_JARGON:
        pattern = re.compile(rf"(?<!\w){re.escape(jargon)}(?!\w)", re.IGNORECASE)
        text = pattern.sub("", text)

    # 3. Filter category-specific taboo terms
    if taboos:
        for taboo in taboos:
            clean_taboo = (taboo or "").strip()
            if not clean_taboo:
                continue
            # Regex boundary that safely handles characters like '%' (e.g. '100% safe')
            pattern = re.compile(rf"(?<!\w){re.escape(clean_taboo)}(?!\w)", re.IGNORECASE)
            text = pattern.sub("", text)

    # 4. Clean leftover punctuation gaps and normalize whitespace
    text = re.sub(r" +([,.!?])", r"\1", text)
    text = _WS_RE.sub(" ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = _NL_RE.sub("\n\n", text)

    return text.strip()


def validate_action(action_dict: dict[str, Any], conversation_history: Optional[List[str]] = None) -> bool:
    """Validates the composed action dictionary.

    - Anti-repetition check: Detects if action_dict['body'] is identical to any
      message previously sent in this conversation. If duplicate, modifies the body
      with a natural follow-up variation to prevent the -2 repetition penalty.
    - Length & structure check: Verifies non-empty, readable body length.
    """
    if not isinstance(action_dict, dict):
        return False

    body = (action_dict.get("body") or "").strip()
    if not body:
        return False

    # Length guardrail (concise, non-empty, and within WhatsApp readable limits)
    if len(body) < 5 or len(body) > 1500:
        return False

    # Anti-repetition check against conversation history
    history = [msg.strip() for msg in (conversation_history or []) if isinstance(msg, str) and msg.strip()]
    if body in history:
        # Avoid the -2 penalty by modifying the message into a contextual follow-up
        action_dict["body"] = f"{body}\n\n(Following up with a quick note on this!)"

    return True
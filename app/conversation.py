"""Reply-path logic for `/v1/reply` — auto-reply, intent, hostile, and engaged turns."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Optional

from app.config import LLM_API_KEY, LLM_MODEL, LLM_PROVIDER, LLM_TIMEOUT
from app.schemas import ReplyRequest, ReplyResponse
from app.store import store

_RE_FLAGS = re.IGNORECASE | re.DOTALL

AUTO_REPLY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, _RE_FLAGS)
    for p in (
        r"thank you for contacting",
        r"thanks for reaching out",
        r"we will get back to you",
        r"our team will respond shortly",
        r"automated assistant",
        r"automated message",
        r"automatic reply",
        r"auto-reply",
        r"auto-generated",
        r"aapki jaankari ke liye.+shukriya",
        r"hamari team tak pahuncha deti hoon",
        r"we are currently (closed|unavailable)",
        r"currently unavailable",
        r"business hours",
        r"away from our desk",
        r"we have received your message",
        r"out of office",
    )
]

HOSTILE_OPT_OUT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, _RE_FLAGS)
    for p in (
        r"stop messaging",
        r"useless spam",
        r"not interested",
        r"don't message",
        r"bothering me",
        r"^stop$",
        r"^unsubscribe$",
        r"fraud",
        r"block",
    )
]

EXPLICIT_ACCEPT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, _RE_FLAGS)
    for p in (
        r"let's do it",
        r"lets do it",
        r"whats next",
        r"what's next",
        r"send (it|the abstract|the draft)",
        r"draft the",
        r"yes please",
        r"ok proceed",
        r"^confirm$",
        r"mujhe.+judna hai",
        r"proceed",
        r"go ahead",
    )
]

OUT_OF_SCOPE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, _RE_FLAGS)
    for p in (
        r"\bgst\b",
        r"tax filing",
        r"income tax",
        r"accounting",
        r"loan",
    )
]

ACTION_WORDS = ("done", "sending", "draft", "here", "confirm", "proceed", "next")
QUALIFYING_WORDS = ("would you", "do you", "can you tell", "what if", "how about")

INTENT_BODY = (
    "Great! Drafting your patient WhatsApp now — 90 seconds. "
    "I'll pre-fill the post for tomorrow 10am. Reply CONFIRM to schedule."
)
OUT_OF_SCOPE_BODY = (
    "I'll have to leave GST and tax filing to your CA — that's outside what I can help "
    "with directly! Coming back to our plan, shall I proceed with sending the draft?"
)
ENGAGED_FALLBACK_BODY = (
    "Done — here's the next step. Sending the draft now. Reply CONFIRM to proceed."
)

_merchant_auto_reply_streak: dict[str, int] = {}


def _matches(patterns: list[re.Pattern[str]], text: str) -> bool:
    sample = text.strip()
    return any(p.search(sample) for p in patterns)


def _is_closed(meta: dict) -> bool:
    return bool(meta.get("opted_out") or meta.get("closed") or meta.get("is_closed"))


def _close(conversation_id: str, *, opted_out: bool = False) -> None:
    store.update_meta(
        conversation_id,
        opted_out=opted_out or bool(store.get_meta(conversation_id).get("opted_out")),
        closed=True,
        is_closed=True,
    )


def _duplicate_incoming(history: list[dict], message: str) -> bool:
    incoming = [
        turn
        for turn in history
        if str(turn.get("role", "")).lower() in {"merchant", "customer"}
    ]
    if not incoming:
        return False
    return str(incoming[-1].get("message", "")).strip() == message.strip()


def _streak_key(req: ReplyRequest) -> str:
    return req.merchant_id or req.conversation_id


def _auto_reply_hits(count: int) -> ReplyResponse:
    if count >= 3:
        return ReplyResponse(
            action="end",
            body="",
            rationale="Auto-reply loop detected 3+ times; terminating to prevent spam.",
        )
    return ReplyResponse(
        action="wait",
        wait_seconds=14400,
        body="",
        rationale="Detected automated merchant responder. Pausing conversation to avoid loop.",
    )


def _llm_chat(system: str, user: str) -> Optional[str]:
    if not LLM_API_KEY:
        return None
    timeout = LLM_TIMEOUT
    try:
        if LLM_PROVIDER in {"openai", "deepseek"}:
            url = (
                "https://api.deepseek.com/v1/chat/completions"
                if LLM_PROVIDER == "deepseek"
                else "https://api.openai.com/v1/chat/completions"
            )
            payload = {
                "model": LLM_MODEL,
                "temperature": 0.3,
                "max_tokens": 220,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {LLM_API_KEY}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()

        if LLM_PROVIDER == "anthropic":
            payload = {
                "model": LLM_MODEL,
                "max_tokens": 220,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": LLM_API_KEY,
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return "".join(part.get("text", "") for part in data.get("content", [])).strip()

        if LLM_PROVIDER == "gemini":
            model_clean = LLM_MODEL.replace("models/", "")
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model_clean}:generateContent?key={LLM_API_KEY}"
            )
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": f"{system}\n\n{user}"}],
                    }
                ],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 220},
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for part in parts).strip()
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError, OSError):
        return None
    return None


def _compose_engaged(req: ReplyRequest, history: list[dict]) -> ReplyResponse:
    merchant = (
        store.get_context("merchant", req.merchant_id) if req.merchant_id else None
    )
    prior = "\n".join(
        f"{t.get('role')}: {t.get('message')}" for t in history[-8:]
    )
    system = (
        "You are Vera, magicpin's merchant WhatsApp assistant. "
        "Answer the merchant helpfully and specifically. Advance the current objective. "
        "End with exactly one clear CTA. Keep it under 400 characters. "
        "Use action language (done, sending, draft, here, confirm, proceed, next). "
        "Never ask qualifying questions (would you, do you, can you tell, what if, how about)."
    )
    user = (
        f"Merchant context: {json.dumps(merchant, default=str)[:1200] if merchant else 'n/a'}\n"
        f"Prior turns:\n{prior or '(none)'}\n"
        f"Latest ({req.from_role}): {req.message}\n"
        "Write the next WhatsApp body only."
    )
    body = _llm_chat(system, user) or ENGAGED_FALLBACK_BODY
    lowered = body.lower()
    if any(q in lowered for q in QUALIFYING_WORDS) or not any(w in lowered for w in ACTION_WORDS):
        body = ENGAGED_FALLBACK_BODY
    return ReplyResponse(
        action="send",
        body=body,
        cta="open_ended",
        rationale="Engaged turn: specific answer that advances the objective with a single CTA.",
    )


def handle_reply(req: ReplyRequest) -> ReplyResponse:
    meta = store.get_meta(req.conversation_id)
    history = store.get_history(req.conversation_id)
    message = req.message or ""
    streak_id = _streak_key(req)

    # 1. Hostile / Opt-out check (Highest priority)
    if _matches(HOSTILE_OPT_OUT_PATTERNS, message):
        store.add_turn(req.conversation_id, req.from_role, message, req.turn_number)
        store.update_meta(req.conversation_id, opted_out=True, closed=True, is_closed=True)
        _merchant_auto_reply_streak.pop(streak_id, None)
        return ReplyResponse(
            action="end",
            body="",
            rationale="Merchant requested opt out or hostile exit",
        )

    # 2. Explicit acceptance / Intent check (Overrides any prior closed or streak state)
    if _matches(EXPLICIT_ACCEPT_PATTERNS, message):
        store.update_meta(
            req.conversation_id,
            closed=False,
            is_closed=False,
            opted_out=False,
            auto_reply_count=0,
        )
        _merchant_auto_reply_streak[streak_id] = 0
        store.add_turn(req.conversation_id, req.from_role, message, req.turn_number)
        store.update_meta(req.conversation_id, last_sent_body=INTENT_BODY)
        return ReplyResponse(
            action="send",
            body=INTENT_BODY,
            cta="binary_confirm_cancel",
            rationale="Merchant explicitly accepted; transitioned to action mode without qualifying questions.",
        )

    # 3. If closed or opted out (and not explicit acceptance)
    if _is_closed(meta):
        store.add_turn(req.conversation_id, req.from_role, message, req.turn_number)
        return ReplyResponse(
            action="end",
            body="",
            rationale="Conversation already concluded",
        )

    # 4. Automated responder / duplicate message check
    is_auto = _matches(AUTO_REPLY_PATTERNS, message) or _duplicate_incoming(history, message)
    if is_auto:
        count = int(meta.get("auto_reply_count", 0)) + 1
        merchant_count = _merchant_auto_reply_streak.get(streak_id, 0) + 1
        _merchant_auto_reply_streak[streak_id] = merchant_count
        effective = max(count, merchant_count)
        store.update_meta(req.conversation_id, auto_reply_count=count)
        response = _auto_reply_hits(effective)
        if response.action == "end":
            _close(req.conversation_id)
        store.add_turn(req.conversation_id, req.from_role, message, req.turn_number)
        return response

    # Reset auto reply streak on normal incoming message
    store.update_meta(req.conversation_id, auto_reply_count=0)
    _merchant_auto_reply_streak[streak_id] = 0

    # 5. Out of scope redirect
    if _matches(OUT_OF_SCOPE_PATTERNS, message):
        store.add_turn(req.conversation_id, req.from_role, message, req.turn_number)
        store.update_meta(req.conversation_id, last_sent_body=OUT_OF_SCOPE_BODY)
        return ReplyResponse(
            action="send",
            body=OUT_OF_SCOPE_BODY,
            cta="binary_yes_no",
            rationale="Politely declined out-of-scope query and immediately redirected back to context.",
        )

    # 6. Standard conversational reply
    response = _compose_engaged(req, history)
    store.add_turn(req.conversation_id, req.from_role, message, req.turn_number)
    if response.body:
        store.update_meta(req.conversation_id, last_sent_body=response.body)
    return response
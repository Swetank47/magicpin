"""Outbound message composer for `/v1/tick` — Vera, grounded in the 4 contexts."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Optional

from app.config import LLM_API_KEY, LLM_MODEL, LLM_PROVIDER
from app.guardrails import sanitize_message
from app.schemas import TickAction

COMPOSE_TIMEOUT = 3.5
COMPOSE_TEMPERATURE = 0.0

SYSTEM_PROMPT = """You are Vera, an elite WhatsApp engagement copilot for magicpin merchants.

Your job is NOT to write a generic marketing nudge. Identify the SINGLE trigger event that makes this message worth sending NOW, then build the message around that event.

SCORING PRIORITIES:
- SPECIFICITY: verifiable facts, numbers, dates, prices, sources
- CATEGORY FIT: correct voice for the business
- MERCHANT FIT: facts specific to this merchant
- TRIGGER RELEVANCE / DECISION QUALITY: unmistakable WHY NOW using trigger.payload
- ENGAGEMENT: useful, low-friction reason to reply

CORE FORMULA:
1. Address correctly.
2. State the trigger fact first or very early.
3. Explain the merchant-specific implication.
4. Offer ONE concrete next action Vera can actually perform.
5. End with ONE low-friction CTA.

TRIGGER-FIRST RULES:
- research_digest / research_digest_release / digest: lead with the research finding, exact source, and category/merchant relevance.
- perf_dip / performance_dip: lead with the exact decline and comparison period; connect it to actual merchant data; suggest one recovery action.
- perf_spike / performance_spike / milestone: lead with the exact improvement/milestone and suggest one next opportunity.
- review_pattern / review_theme_emerged: use the actual review theme/count available in the trigger and suggest one response.
- competitor / competitor_opened: state the competitor and location/timing from the trigger. Never invent impact.
- festival / seasonal: state the event/date from the trigger and connect it to the category or active offer.
- curious_ask: ask ONE merchant-specific question based on an observable fact.
- recall_due / customer_lapsed / appointment_tomorrow / unplanned_slot_open: use customer state, last visit/due date, preferences, consent, and actual slots when present.

ACTION RULE:
Only claim Vera has "drafted", "prepared", "scheduled", "booked", "pulled", or "sent" something if context explicitly supports it. Otherwise say "I can draft..." or "I can pull...".

IDENTITY:
- Merchant-facing: dentists -> "Dr. <FirstName>"; other categories -> first name.
- Customer-facing: "Hi <Customer Name>, <Merchant Name> here."
- Match category voice and useful language preference.

SPECIFICITY:
- Prefer exact trigger.payload facts over generic merchant statistics.
- Use exact source/date/price/metric when available.
- Never invent numbers, names, sources, dates, slots, outcomes, or competitor effects.
- Do not force a number into the message when none is useful.

DECISION QUALITY:
The first 1-2 sentences must make it obvious why Vera is messaging NOW.
A message that could have been sent last week without changing its meaning is too generic.
Do not merely report a metric; interpret its business implication and propose one concrete next step.
Avoid generic phrases like "improve your business", "boost engagement", or "grow your presence" unless directly tied to a trigger fact.

ENGAGEMENT:
Use curiosity, concrete utility, or a relevant opportunity.
Do not ask "What do you think?" or "Are you interested?"
Use ONE CTA only, such as "Reply YES and I'll draft it", "Reply YES and I'll pull the summary", or "Reply 1 or 2 to book".

COMPLIANCE:
- ZERO URLs.
- Keep the body under 380 characters.
- No internal jargon such as TriggerContext, suppression_key, payload, composer, or scoring.
- Return ONLY JSON:
{"body":"...","cta":"...","template_name":"...","template_params":["..."],"rationale":"..."}
"""


def _identity(m: dict) -> dict:
    return m.get("identity") or {}


def _owner_first(m: dict) -> str:
    return str(_identity(m).get("owner_first_name") or "").strip()


def _merchant_name(m: dict) -> str:
    return str(_identity(m).get("name") or "the business").strip()


def _salutation(m: dict, c: dict) -> str:
    slug = str(c.get("slug") or m.get("category_slug") or "")
    first = _owner_first(m)
    if slug == "dentists":
        if first:
            return f"Dr. {first}"
        name = _merchant_name(m)
        return name.split("'")[0].split("’")[0] if name.lower().startswith("dr") else f"Dr. {name}"
    return first or _merchant_name(m)


def _active_offers(m: dict, c: dict) -> list[dict]:
    offers = [o for o in (m.get("offers") or []) if o.get("status") == "active"]
    return offers if offers else (c.get("offer_catalog") or [])[:1]


def _offer_title(m: dict, c: dict) -> str:
    offers = _active_offers(m, c)
    return str(offers[0].get("title") or "") if offers else ""


def _digest_item(c: dict, t: dict) -> dict:
    payload = t.get("payload") or {}
    item_id = payload.get("top_item_id") or payload.get("digest_item_id") or payload.get("alert_id")
    digest = c.get("digest") or []
    if item_id:
        for item in digest:
            if item.get("id") == item_id:
                return item
    return digest[0] if digest else {}


def _customer_name(cust: Optional[dict]) -> str:
    return str((cust.get("identity") or {}).get("name") or "").split("(")[0].strip() if cust else ""


def _lapse_days(customer: Optional[dict], trigger: dict) -> Optional[int]:
    payload = trigger.get("payload") or {}
    if payload.get("days_since_last_visit") is not None:
        try:
            return int(float(payload.get("days_since_last_visit")))
        except (ValueError, TypeError):
            pass
    if not customer:
        return None
    rel = customer.get("relationship") or {}
    last = str(rel.get("last_visit") or "")[:10]
    due = str(payload.get("due_date") or payload.get("last_service_date") or "")[:10]
    if last and due:
        try:
            from datetime import date
            return abs((date.fromisoformat(due) - date.fromisoformat(last)).days)
        except ValueError:
            return None
    return None


def _slot_labels(trigger: dict) -> list[str]:
    payload = trigger.get("payload") or {}
    slots = payload.get("available_slots") or payload.get("next_session_options") or []
    labels = []
    for s in slots:
        if isinstance(s, dict) and s.get("label"):
            labels.append(str(s["label"]))
        elif isinstance(s, str):
            labels.append(s)
    return labels


def _assemble_context(
    trigger: dict,
    merchant: dict,
    category: dict,
    customer: Optional[dict],
) -> dict[str, Any]:
    ident = _identity(merchant)
    perf = merchant.get("performance") or {}
    peer = category.get("peer_stats") or {}
    digest = _digest_item(category, trigger)
    voice = category.get("voice") or {}

    return {
        "category": {
            "slug": category.get("slug") or merchant.get("category_slug"),
            "voice_tone": voice.get("tone"),
            "vocab_allowed": voice.get("vocab_allowed", []),
            "taboos": voice.get("taboos", voice.get("vocab_taboo", [])),
            "peer_stats": {
                "avg_views_30d": peer.get("avg_views_30d"),
                "avg_calls_30d": peer.get("avg_calls_30d"),
                "avg_ctr": peer.get("avg_ctr"),
                "avg_rating": peer.get("avg_rating"),
                "avg_reviews": peer.get("avg_reviews"),
            },
            "top_digest": {
                "id": digest.get("id"),
                "title": digest.get("title"),
                "source": digest.get("source"),
                "trial_n": digest.get("trial_n"),
                "patient_segment": digest.get("patient_segment"),
                "summary": digest.get("summary"),
            },
            "offer_catalog": category.get("offer_catalog") or [],
        },
        "merchant": {
            "salutation": _salutation(merchant, category),
            "business_name": _merchant_name(merchant),
            "locality": ident.get("locality"),
            "city": ident.get("city"),
            "languages": ident.get("languages"),
            "subscription": merchant.get("subscription") or {},
            "performance": {
                "views": perf.get("views"),
                "calls": perf.get("calls"),
                "directions": perf.get("directions"),
                "ctr": perf.get("ctr"),
                "delta_7d": perf.get("delta_7d"),
            },
            "active_offers": [
                {"id": o.get("id"), "title": o.get("title")}
                for o in (merchant.get("offers") or [])
                if o.get("status") == "active"
            ],
            "active_offer": _offer_title(merchant, category),
            "customer_aggregate": merchant.get("customer_aggregate") or {},
            "signals": merchant.get("signals") or [],
            "recent_conversation": (merchant.get("conversation_history") or [])[-3:],
        },
        "trigger": {
            "id": trigger.get("id") or trigger.get("trigger_id"),
            "kind": trigger.get("kind"),
            "source": trigger.get("source"),
            "scope": trigger.get("scope"),
            "payload": trigger.get("payload") or {},
            "urgency": trigger.get("urgency"),
            "expires_at": trigger.get("expires_at"),
            "available_slots": _slot_labels(trigger),
        },
        "customer": None if not customer else {
            "customer_id": customer.get("customer_id"),
            "name": _customer_name(customer),
            "lapse_days": _lapse_days(customer, trigger),
            "language": (customer.get("identity") or {}).get("language_pref"),
            "preferred_slots": (customer.get("preferences") or {}).get("preferred_slots"),
            "channel": (customer.get("preferences") or {}).get("channel"),
            "last_visit": (customer.get("relationship") or {}).get("last_visit"),
            "visits_total": (customer.get("relationship") or {}).get("visits_total"),
            "services_received": (customer.get("relationship") or {}).get("services_received"),
            "state": customer.get("state"),
            "consent": customer.get("consent") or {},
        },
    }

def _llm_complete(system: str, user: str) -> Optional[str]:
    if not LLM_API_KEY:
        return None
    try:
        if LLM_PROVIDER == "gemini":
            clean_model = LLM_MODEL.replace("models/", "")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent?key={LLM_API_KEY}"
            payload = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "temperature": COMPOSE_TEMPERATURE,
                    "maxOutputTokens": 450,
                    "responseMimeType": "application/json",
                },
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=COMPOSE_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(part.get("text", "") for part in parts).strip()
    except Exception:
        return None
    return None


def _parse_llm_json(raw: str) -> Optional[dict]:
    match = re.search(r"\{[\s\S]*\}", raw or "")
    if not match:
        return None
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    body = str(data.get("body") or "").strip()
    if not body or len(body) < 15 or "=" in body or "{" in body:
        return None
    return data


def _deterministic_fallback(
    trigger: dict,
    merchant: dict,
    category: dict,
    customer: Optional[dict] = None,
) -> dict:
    """Trigger-specific fallback with no invented business facts."""
    salut = _salutation(merchant, category)
    mname = _merchant_name(merchant)
    loc = _identity(merchant).get("locality") or "your area"
    perf = merchant.get("performance") or {}
    offer = _offer_title(merchant, category)
    views, calls = perf.get("views"), perf.get("calls")
    kind = str(trigger.get("kind") or "nudge").lower()
    payload = trigger.get("payload") or {}

    def val(*keys):
        for key in keys:
            value = payload.get(key)
            if value not in (None, "", [], {}):
                return value
        return None

    if customer:
        cname = _customer_name(customer) or "there"
        slots = _slot_labels(trigger)
        due = val("due_date", "appointment_date", "date")
        service = val("service", "service_name", "last_service")

        if "appointment" in kind and slots:
            body = f"Hi {cname}, {mname} here. Your options are {slots[0]}"
            if len(slots) > 1:
                body += f" or {slots[1]}"
            body += ". Reply 1 or 2 to confirm."
        elif "recall" in kind or "lapsed" in kind:
            body = f"Hi {cname}, {mname} here."
            if service:
                body += f" Your {service} follow-up is due"
            else:
                body += " Your follow-up is due"
            if due:
                body += f" around {due}"
            body += "."
            if slots:
                body += f" We have {slots[0]}"
                if len(slots) > 1:
                    body += f" or {slots[1]}"
            body += " Reply 1 or 2 to book."
        elif slots:
            body = f"Hi {cname}, {mname} here. We have {slots[0]}"
            if len(slots) > 1:
                body += f" or {slots[1]}"
            body += ". Reply 1 or 2 to book."
        else:
            body = f"Hi {cname}, {mname} here. I can help arrange your next visit. Reply YES and we'll help with a suitable time."

        return {
            "body": body[:379],
            "cta": "binary_yes_no",
            "template_name": f"merchant_{kind}_v2",
            "template_params": [cname, mname],
            "rationale": "Customer outreach anchored to the supplied trigger and customer context.",
        }

    if "research" in kind or "digest" in kind:
        item = _digest_item(category, trigger)
        title, source = item.get("title"), item.get("source")
        segment = item.get("patient_segment")
        body = f"{salut}, {title or 'a new category research update'}."
        if segment:
            body += f" It is relevant to your {str(segment).replace('_', ' ')} patients."
        if source:
            body += f" Source: {source}."
        body += " Reply YES and I'll pull the useful summary."

    elif "perf_dip" in kind or "performance_dip" in kind:
        delta = val("delta_pct", "change_pct", "calls_delta_pct", "views_delta_pct")
        metric = val("metric", "metric_name") or "performance"
        body = f"{salut}, {metric} is down {delta} over the trigger window." if delta is not None else f"{salut}, your recent {metric} performance has dipped."
        if views is not None and calls is not None:
            body += f" You have {views} views and {calls} calls."
        body += f" I can draft a recovery message{f' around {offer}' if offer else ''}. Reply YES to draft it."

    elif "perf_spike" in kind or "performance_spike" in kind or "milestone" in kind:
        delta = val("delta_pct", "change_pct", "growth_pct")
        metric = val("metric", "metric_name") or "performance"
        body = f"{salut}, your {metric} is up {delta}." if delta is not None else f"{salut}, your {metric} just improved."
        body += f" I can turn that momentum into a focused message{f' featuring {offer}' if offer else ''}. Reply YES to draft it."

    elif "competitor" in kind:
        comp = val("competitor_name", "name") or "A new competitor"
        area = val("locality", "location", "area") or loc
        body = f"{salut}, {comp} just appeared in {area}. "
        body += f"I can draft a retention message{f' around {offer}' if offer else ''}. Reply YES to draft it."

    elif "review" in kind:
        theme, count = val("theme", "review_theme", "topic"), val("count", "review_count", "mentions")
        body = f"{salut}, a review pattern is emerging"
        if theme:
            body += f" around {theme}"
        if count:
            body += f" ({count} mentions)"
        body += ". I can turn it into one concrete response action. Reply YES to draft it."

    elif "festival" in kind or "season" in kind:
        event, event_date = val("event", "festival", "name"), val("date", "event_date", "start_date")
        body = f"{salut}, {event or 'an upcoming seasonal moment'}"
        if event_date:
            body += f" is coming up on {event_date}"
        body += f". I can draft a timely message{f' around {offer}' if offer else ''}. Reply YES to draft it."

    elif "curious" in kind:
        body = f"{salut}, I noticed something specific in your latest account activity."
        if views is not None and calls is not None:
            body = f"{salut}, you have {views} views and {calls} calls in the current window."
        body += " Want me to dig into the gap and suggest one action?"

    else:
        body = f"{salut}, your listing currently has {views} views and {calls} calls." if views is not None and calls is not None else f"{salut}, I have a merchant-specific account insight to share."
        body += f" I can suggest one next step{f' around {offer}' if offer else ''}. Reply YES and I'll take care of it."

    return {
        "body": body[:379],
        "cta": "binary_yes_no",
        "template_name": f"vera_{kind}_v2",
        "template_params": [salut, mname, loc],
        "rationale": "Trigger-specific, context-grounded fallback with one concrete next step.",
    }

def compose_action(
    trigger: dict,
    merchant: dict,
    category: dict,
    customer: Optional[dict] = None,
) -> TickAction:
    packed = _assemble_context(trigger, merchant, category, customer)
    salut = _salutation(merchant, category)

    user_prompt = (
        f"Target recipient: {salut}\n"
        "Compose ONE message from ONLY these facts. The trigger is the reason to message NOW, "
        "so use at least one concrete trigger.payload fact whenever available. "
        "Prefer trigger facts over generic merchant metrics. "
        "Make the business implication explicit and propose exactly one next action. "
        "Do not invent numbers, names, dates, sources, slots, outcomes, or completed actions. "
        "If the trigger does not support a claim, omit it. "
        "The first two sentences must make the WHY NOW obvious.\n\n"
        f"{json.dumps(packed, default=str, ensure_ascii=False)}\n\n"
        f"send_as must be {'merchant_on_behalf' if customer else 'vera'}. JSON only."
    )

    raw = _llm_complete(SYSTEM_PROMPT, user_prompt)
    draft = _parse_llm_json(raw) if raw else None

    if draft is None:
        draft = _deterministic_fallback(trigger, merchant, category, customer)

    merchant_id = str(merchant.get("merchant_id") or trigger.get("merchant_id") or "unknown")
    trigger_id = str(trigger.get("id") or trigger.get("trigger_id") or "trg")
    customer_id = customer.get("customer_id") if customer else trigger.get("customer_id")

    return TickAction(
        conversation_id=f"conv_{merchant_id}_{trigger_id}",
        merchant_id=merchant_id,
        customer_id=customer_id,
        send_as="merchant_on_behalf" if customer else "vera",
        trigger_id=trigger_id,
        template_name=str(draft.get("template_name") or f"vera_{trigger.get('kind', 'generic')}_v1"),
        template_params=[str(p) for p in (draft.get("template_params") or [])],
        body=sanitize_message(str(draft.get("body") or "")),
        cta=str(draft.get("cta") or "binary_yes_no"),
        suppression_key=str(trigger.get("suppression_key") or ""),
        rationale=str(draft.get("rationale") or "Context-grounded composition."),
    )
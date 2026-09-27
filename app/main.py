"""FastAPI application entry point for Vera Merchant AI.

Exposes the 5 required endpoints under /v1/* adhering to the magicpin
challenge evaluation contract and judge harness specifications.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

from app import config
from app.composer import compose_action
from app.conversation import handle_reply
from app.guardrails import validate_action
from app.schemas import (
    ContextPushRequest,
    ContextPushResponse,
    HealthzResponse,
    MetadataResponse,
    ReplyRequest,
    ReplyResponse,
    TickAction,
    TickRequest,
    TickResponse,
)
from app.store import store

app = FastAPI(
    title="magicpin Vera Assistant",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)


@app.get("/v1/healthz", response_model=HealthzResponse, status_code=status.HTTP_200_OK)
async def healthz() -> HealthzResponse:
    """Liveness probe reporting uptime and context inventory across scopes."""
    return HealthzResponse(
        status="ok",
        uptime_seconds=int(time.time() - store.start_time),
        contexts_loaded=store.get_counts(),
    )


@app.get("/v1/metadata", response_model=MetadataResponse, status_code=status.HTTP_200_OK)
async def metadata() -> MetadataResponse:
    """Returns bot identification, model configurations, and team metadata."""
    return MetadataResponse(
        team_name="Vera-Mastery",
        team_members=["Participant"],
        model=config.LLM_MODEL or "gemini-3.1-flash-lite",
        approach="4-Context dynamic composer with deterministic multi-turn intent router",
        contact_email="team@example.com",
        version="1.0.0",
        submitted_at="2026-04-26T08:00:00Z",
    )


@app.post("/v1/context", response_model=ContextPushResponse)
async def push_context(req: ContextPushRequest) -> ContextPushResponse:
    accepted, current_version = store.upsert_context(
        scope=req.scope,
        context_id=req.context_id,
        version=req.version,
        payload=req.payload,
    )

    now_iso = datetime.now(timezone.utc).isoformat()

    if not accepted:
        return ContextPushResponse(
            accepted=False,
            reason=f"Version {req.version} is stale (current: {current_version})",
            current_version=current_version,
        )

    return ContextPushResponse(
        accepted=True,
        ack_id=str(uuid.uuid4()),
        stored_at=now_iso,
        current_version=req.version,
    )


def _process_single_trigger(trg_id: str) -> Optional[TickAction]:
    """Worker to compose, guard, and record one trigger action."""
    trigger = store.get_context("trigger", trg_id)
    if not trigger:
        return None

    suppression_key = trigger.get("suppression_key", "")
    if suppression_key and store.is_suppressed(suppression_key):
        return None

    merchant_id = trigger.get("merchant_id")
    if not merchant_id:
        return None

    merchant = store.get_context("merchant", merchant_id)
    if not merchant:
        return None

    cat_slug = merchant.get("category_slug")
    if not cat_slug:
        return None

    category = store.get_context("category", cat_slug)
    if not category:
        return None

    customer_id = trigger.get("customer_id")
    customer = store.get_context("customer", customer_id) if customer_id else None

    # Compose message using the 4-context engine
    action = compose_action(
        trigger=trigger,
        merchant=merchant,
        category=category,
        customer=customer,
    )

    # Validate against repetition and length constraints
    history_msgs = [turn.get("msg", "") for turn in store.get_history(action.conversation_id)]
    action_dict = action.model_dump()
    validate_action(action_dict, history_msgs)

    final_action = TickAction(**action_dict)

    # Record conversation state & suppress duplicate trigger execution
    store.add_turn(
        final_action.conversation_id,
        "bot",
        final_action.body,
        1,
    )
    store.update_meta(final_action.conversation_id, last_sent_body=final_action.body)

    if suppression_key:
        store.mark_suppressed(suppression_key)

    return final_action


@app.post("/v1/tick", response_model=TickResponse, status_code=status.HTTP_200_OK)
async def tick(req: TickRequest) -> TickResponse:
    """Evaluates active triggers in parallel, completing all 5 batch actions in sub-3s."""
    tasks = [
        asyncio.to_thread(_process_single_trigger, trg_id)
        for trg_id in req.available_triggers
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    actions: List[TickAction] = [
        res for res in results if isinstance(res, TickAction)
    ]
    return TickResponse(actions=actions)


@app.post("/v1/reply", response_model=ReplyResponse, status_code=status.HTTP_200_OK)
async def reply(req: ReplyRequest) -> ReplyResponse:
    """Handles incoming merchant/customer dialogue turns."""
    return handle_reply(req)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=getattr(config, "BOT_PORT", 8080),
        reload=True,
    )
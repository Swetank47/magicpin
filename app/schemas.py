"""Pydantic v2 request/response models for the magicpin judge harness."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Scope = Literal["category", "merchant", "customer", "trigger"]
SendAs = Literal["vera", "merchant_on_behalf"]
FromRole = Literal["merchant", "customer"]
ReplyAction = Literal["send", "wait", "end"]


class ContextPushRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scope: Scope
    context_id: str
    version: int
    delivered_at: str
    payload: dict[str, Any]


class ContextPushResponse(BaseModel):
    accepted: bool
    ack_id: Optional[str] = None
    stored_at: Optional[str] = None
    reason: Optional[str] = None
    current_version: Optional[int] = None


class TickRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    now: str
    available_triggers: list[str] = Field(default_factory=list)


class TickAction(BaseModel):
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    send_as: SendAs
    trigger_id: str
    template_name: str
    template_params: list[str]
    body: str
    cta: str
    suppression_key: str
    rationale: str


class TickResponse(BaseModel):
    actions: list[TickAction] = Field(default_factory=list)


class ReplyRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: FromRole
    message: str
    received_at: str
    turn_number: int


class ReplyResponse(BaseModel):
    action: ReplyAction
    body: Optional[str] = None
    cta: Optional[str] = None
    wait_seconds: Optional[int] = None
    rationale: str


class HealthzResponse(BaseModel):
    status: str
    uptime_seconds: int
    contexts_loaded: dict[str, int]


class MetadataResponse(BaseModel):
    team_name: str
    team_members: list[str]
    model: str
    approach: str
    contact_email: str
    version: str
    submitted_at: str
"""Runtime configuration for the Vera merchant assistant."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

LLM_PROVIDER_OPENAI = "openai"
LLM_PROVIDER_ANTHROPIC = "anthropic"
LLM_PROVIDER_GEMINI = "gemini"
LLM_PROVIDER_DEEPSEEK = "deepseek"

ALLOWED_LLM_PROVIDERS: frozenset[str] = frozenset(
    {
        LLM_PROVIDER_OPENAI,
        LLM_PROVIDER_ANTHROPIC,
        LLM_PROVIDER_GEMINI,
        LLM_PROVIDER_DEEPSEEK,
    }
)

DEFAULT_LLM_MODELS: dict[str, str] = {
    LLM_PROVIDER_OPENAI: "gpt-4o-mini",
    LLM_PROVIDER_ANTHROPIC: "claude-3-5-sonnet-20241022",
    LLM_PROVIDER_GEMINI: "gemini-1.5-flash",
    LLM_PROVIDER_DEEPSEEK: "deepseek-chat",
}

DEFAULT_BOT_PORT = 8080
DEFAULT_LLM_TIMEOUT = 15.0


def _require_provider(raw: str) -> str:
    provider = raw.strip().lower()
    if provider not in ALLOWED_LLM_PROVIDERS:
        allowed = ", ".join(sorted(ALLOWED_LLM_PROVIDERS))
        raise ValueError(f"LLM_PROVIDER must be one of: {allowed}. Got {raw!r}.")
    return provider


LLM_PROVIDER: str = _require_provider(os.getenv("LLM_PROVIDER", LLM_PROVIDER_OPENAI))
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
LLM_MODEL: str = os.getenv("LLM_MODEL") or DEFAULT_LLM_MODELS[LLM_PROVIDER]
BOT_PORT: int = int(os.getenv("BOT_PORT", str(DEFAULT_BOT_PORT)))
LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", str(DEFAULT_LLM_TIMEOUT)))

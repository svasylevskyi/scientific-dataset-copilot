import os
from dataclasses import dataclass, field
from decimal import Decimal

# A reviewed model and tariff, not a user-selectable model or destination.
MODEL = "gpt-5.4-mini-2026-03-17"
INPUT_RATE = Decimal("0.75")
CACHED_RATE = Decimal("0.075")
OUTPUT_RATE = Decimal("4.50")
PRICING_VERSION = "openai-standard-2026-10-14"
PROMPT_VERSION = "sst-intent-v1"
MAX_OUTPUT = 600
MAX_TURNS = 3


@dataclass(frozen=True)
class CopilotConfig:
    enabled: bool
    key: str = field(repr=False)
    daily_requests: int = 20
    daily_budget_usd: Decimal = Decimal("2.00")


def config() -> CopilotConfig:
    key = os.getenv("SDC_OPENAI_API_KEY", "").strip()
    requests = int(os.getenv("SDC_COPILOT_DAILY_REQUESTS", "20"))
    budget = Decimal(os.getenv("SDC_COPILOT_DAILY_BUDGET_USD", "2.00"))
    if not 1 <= requests <= 100 or not budget.is_finite() or not 0 <= budget <= 100:
        raise ValueError("Copilot limits require 1–100 requests and a finite USD budget from 0–100")
    return CopilotConfig(
        enabled=os.getenv("SDC_COPILOT_ENABLED", "false").lower() == "true" and bool(key),
        key=key,
        daily_requests=requests,
        daily_budget_usd=budget,
    )

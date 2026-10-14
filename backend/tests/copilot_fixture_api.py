"""Browser-test entry point. Never used by the app or either Compose deployment."""

import os

from app.copilot import provider
from app.copilot.schemas import Intent
from app.main import app  # noqa: F401

os.environ["SDC_COPILOT_ENABLED"] = "true"
os.environ["SDC_OPENAI_API_KEY"] = "browser-fixture-never-sent"


async def fixture_extract(body, key):
    prompt = body["input"][-1]["content"].lower()
    if "outage" in prompt:
        return provider.ProviderResult(error="unavailable")
    intent = {
        "operation": "unsupported" if "rainfall" in prompt else "monthly_sst",
        "region_id": "madeira",
        "start": "2020-01-01" if "2020" in prompt else None,
        "end": "2020-01-31" if "2020" in prompt else None,
        "clarification": "none" if "2020" in prompt else "dates",
    }
    return provider.ProviderResult(
        intent=Intent.model_validate(intent), input_tokens=1000, cached_tokens=0, output_tokens=100
    )


provider.extract = fixture_extract

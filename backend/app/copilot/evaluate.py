"""Explicit, bounded live model evaluation; deterministic CI never needs an API key."""

import argparse
import asyncio
import json
from datetime import date
from decimal import Decimal
from importlib.resources import files

from app.copilot import provider
from app.copilot.config import MODEL, config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Make paid provider calls (at most $0.50 reserved)"
    )
    args = parser.parse_args()
    cases = json.loads(files("app.copilot").joinpath("evaluation_cases.json").read_text())
    bodies = [
        provider.payload(
            case.get("history", []) + [{"role": "user", "content": case["prompt"]}],
            date(2026, 10, 14),
        )
        for case in cases
    ]
    reserved = sum(provider.reservation(body) for body in bodies)
    print(f"{len(cases)} cases; model {MODEL}; conservative total reservation ${reserved}")
    if reserved > Decimal("0.50"):
        raise SystemExit("Evaluation exceeds its fixed $0.50 ceiling; reduce the corpus first.")
    if not args.live:
        print("No provider calls made. Pass --live with SDC_OPENAI_API_KEY configured to evaluate.")
        return
    cfg = config()
    if not cfg.key:
        raise SystemExit(
            "Configure SDC_OPENAI_API_KEY in the server environment, never in a command argument."
        )
    failures = 0
    estimated = Decimal(0)
    for case, body in zip(cases, bodies, strict=True):
        result = asyncio.run(provider.extract(body, cfg.key))
        estimated += result.cost if result.cost is not None else provider.reservation(body)
        actual = result.intent.model_dump(mode="json") if result.intent else {}
        passed = result.intent is not None and all(
            actual.get(k) == v for k, v in case["expect"].items()
        )
        print(f"{case['id']}: {'PASS' if passed else 'FAIL'}")
        failures += not passed
    print(
        f"{len(cases) - failures}/{len(cases)} passed; "
        f"estimated cost including unknown-usage holds ${estimated}"
    )
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()

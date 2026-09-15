from __future__ import annotations

import argparse
import json
from pathlib import Path

from planner import VerificationRequest, load_registry, plan_verification, Plan
from probe import probe_unpaid_challenge

ROOT = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description="Minimal Verification Planner PoC")
    ap.add_argument("--target", default="https://10x402.com/lint/envelope/one")
    ap.add_argument("--max-cost", type=float, default=0.01)
    ap.add_argument("--claims", default="protocol_conformance,settlement_history")
    ap.add_argument("--min-operators", type=int, default=2)
    ap.add_argument("--min-source-classes", type=int, default=2)
    ap.add_argument("--probe", action="store_true", help="Perform safe unpaid 402 probes; never pays")
    args = ap.parse_args()

    registry = load_registry(ROOT / "registry.json")
    req = VerificationRequest(
        target=args.target,
        required_claims=frozenset(c.strip() for c in args.claims.split(",") if c.strip()),
        max_cost_usd=args.max_cost,
        min_operators=args.min_operators,
        min_source_classes=args.min_source_classes,
    )
    result = plan_verification(req, registry)

    output = {
        "request": {
            "target": req.target,
            "required_claims": sorted(req.required_claims),
            "max_cost_usd": req.max_cost_usd,
            "min_operators": req.min_operators,
            "min_source_classes": req.min_source_classes,
        },
        "planner_status": result.status,
    }

    if not isinstance(result, Plan):
        output["reason"] = result.reason
        print(json.dumps(output, indent=2))
        return 2

    output["plan"] = {
        "verifiers": [v.id for v in result.verifiers],
        "total_cost_usd": result.total_cost_usd,
        "covered_claims": sorted(result.covered_claims),
        "operators": sorted(result.operators),
        "source_classes": sorted(result.source_classes),
    }

    if args.probe:
        output["unpaid_probe_results"] = [probe_unpaid_challenge(v, req.target).to_dict() for v in result.verifiers]
        output["note"] = "Probe mode only inspects the 402 payment challenge. It cannot sign or spend funds."

    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

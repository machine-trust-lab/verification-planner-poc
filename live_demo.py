from __future__ import annotations

import argparse
import json
import os
from decimal import Decimal
from pathlib import Path

from payment import LIVE_ACK, SafeX402Payer, SpendPolicy
from planner import VerificationRequest, load_registry, plan_verification, Plan

ROOT = Path(__file__).resolve().parent
DEFAULT_TARGET = "https://x402.fuchss.app/v1/x402-trust"


def main():
    ap = argparse.ArgumentParser(description="Safe payment-adapter demo")
    ap.add_argument("--target", default=DEFAULT_TARGET)
    ap.add_argument("--live", action="store_true", help="Actually allow an x402 payment (requires explicit env ack + key)")
    ap.add_argument("--simulate", action="store_true", help="Use a captured/synthetic x402check $0.002 challenge; never touches network")
    ap.add_argument("--max-per-call", type=Decimal, default=Decimal("0.01"))
    ap.add_argument("--max-total", type=Decimal, default=Decimal("0.05"))
    args = ap.parse_args()

    registry = load_registry(ROOT / "registry.json")
    # The first live milestone intentionally purchases only protocol conformance:
    # one x402check call, currently quoted at $0.002.
    request = VerificationRequest(
        target=args.target,
        required_claims=frozenset({"protocol_conformance"}),
        max_cost_usd=float(args.max_per_call),
    )
    plan = plan_verification(request, registry)
    if not isinstance(plan, Plan):
        print(json.dumps({"status": plan.status, "reason": plan.reason}, indent=2))
        raise SystemExit(2)

    payer = SafeX402Payer(
        SpendPolicy(max_per_call_usd=args.max_per_call, max_total_usd=args.max_total)
    )
    verifier = plan.verifiers[0]
    if args.live and args.simulate:
        raise SystemExit("choose either --live or --simulate, not both")
    if args.simulate:
        from probe import ProbeResult
        from payment import BASE_MAINNET, USDC_BASE
        captured = ProbeResult(
            verifier_id=verifier.id, status="PAYMENT_REQUIRED", http_status=402, latency_ms=0,
            advertised_amount_atomic="2000", advertised_network=BASE_MAINNET,
            advertised_pay_to="0xceEc1c3F6CD66dC7c91fae0e232Eac0d346564e9",
            advertised_asset=USDC_BASE, advertised_scheme="exact",
        )
        result = payer.dry_run(verifier, args.target, synthetic_probe=captured)
    else:
        result = payer.live(verifier, args.target) if args.live else payer.dry_run(verifier, args.target)

    print(json.dumps({
        "planner": {
            "selected": [v.id for v in plan.verifiers],
            "registry_cost_usd": plan.total_cost_usd,
            "target": args.target,
        },
        "payment": result.to_dict(),
        "spent_local_ledger_usd": str(payer.ledger.committed_usd),
        "live_guard": {
            "ack_env": "X402_LIVE_PAYMENT_ACK",
            "required_value": LIVE_ACK,
            "private_key_env": "PAYER_PRIVATE_KEY",
        },
    }, indent=2))

    if args.live and result.status == "PAYMENT_OR_CALL_ERROR":
        print("\nDo NOT blindly retry: settlement can be pending after a transport/RPC error.")


if __name__ == "__main__":
    main()

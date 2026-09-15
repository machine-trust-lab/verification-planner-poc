import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from planner import VerificationRequest, load_registry, plan_verification, Plan


def reg():
    return load_registry(ROOT / "registry.json")


def test_expected_medium_risk_plan():
    req = VerificationRequest(
        target="https://example.com/paid",
        required_claims=frozenset({"protocol_conformance", "settlement_history"}),
        max_cost_usd=0.01,
        min_operators=2,
        min_source_classes=2,
    )
    out = plan_verification(req, reg())
    assert isinstance(out, Plan)
    assert [v.id for v in out.verifiers] == ["x402check", "x402_trust_prober"]
    assert abs(out.total_cost_usd - 0.007) < 1e-9


def test_budget_can_block_plan():
    req = VerificationRequest(
        target="https://example.com/paid",
        required_claims=frozenset({"protocol_conformance", "settlement_history"}),
        max_cost_usd=0.006,
        min_operators=2,
        min_source_classes=2,
    )
    out = plan_verification(req, reg())
    assert out.status == "NO_PLAN"


def test_single_claim_chooses_cheapest():
    req = VerificationRequest(
        target="https://example.com/paid",
        required_claims=frozenset({"protocol_conformance"}),
        max_cost_usd=0.01,
    )
    out = plan_verification(req, reg())
    assert isinstance(out, Plan)
    assert [v.id for v in out.verifiers] == ["x402check"]
    assert out.total_cost_usd == 0.002

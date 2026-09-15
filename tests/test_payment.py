from decimal import Decimal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from payment import (
    BASE_MAINNET,
    USDC_BASE,
    PaymentQuote,
    SafeX402Payer,
    SpendLedger,
    SpendPolicy,
    SpendPolicyError,
    quote_from_probe,
)
from probe import ProbeResult
from planner import load_registry


def challenge(verifier_id="x402check", amount="2000", network=BASE_MAINNET, asset=USDC_BASE, scheme="exact"):
    return ProbeResult(
        verifier_id=verifier_id,
        status="PAYMENT_REQUIRED",
        http_status=402,
        latency_ms=12,
        advertised_amount_atomic=amount,
        advertised_network=network,
        advertised_pay_to="0x1111111111111111111111111111111111111111",
        advertised_asset=asset,
        advertised_scheme=scheme,
    )


def test_quote_parses_base_usdc():
    q = quote_from_probe(challenge())
    assert q.amount_usd == Decimal("0.002")
    assert q.network == BASE_MAINNET


def test_wrong_network_blocked():
    reg = load_registry(ROOT / "registry.json")
    v = reg[0]
    q = PaymentQuote(v.id, 2000, Decimal("0.002"), "eip155:1", USDC_BASE, "exact", "0x1")
    try:
        SpendLedger().authorize(q, v, SpendPolicy())
    except SpendPolicyError as exc:
        assert "network not allowed" in str(exc)
    else:
        raise AssertionError("expected block")


def test_per_call_cap_blocked():
    reg = load_registry(ROOT / "registry.json")
    v = reg[0]
    payer = SafeX402Payer(SpendPolicy(max_per_call_usd=Decimal("0.001")))
    result = payer.dry_run(v, "https://example.com", synthetic_probe=challenge())
    assert result.status == "BLOCKED"
    assert "per-call cap exceeded" in result.error


def test_registry_price_ceiling_blocked():
    reg = load_registry(ROOT / "registry.json")
    v = reg[0]
    payer = SafeX402Payer()
    result = payer.dry_run(v, "https://example.com", synthetic_probe=challenge(amount="3000"))
    assert result.status == "BLOCKED"
    assert "exceeds registry quote" in result.error


def test_session_cap_blocks_second_payment():
    reg = load_registry(ROOT / "registry.json")
    v = reg[0]
    policy = SpendPolicy(max_per_call_usd=Decimal("0.01"), max_total_usd=Decimal("0.003"))
    ledger = SpendLedger()
    q = quote_from_probe(challenge())
    ledger.authorize(q, v, policy)
    ledger.commit(q)
    try:
        ledger.authorize(q, v, policy)
    except SpendPolicyError as exc:
        assert "session cap exceeded" in str(exc)
    else:
        raise AssertionError("expected block")



def _mock_402(monkeypatch, options):
    import io
    import json
    from urllib.error import HTTPError

    def unpaid_response(req, timeout):
        raise HTTPError(req.full_url, 402, "Payment Required", {},
                        io.BytesIO(json.dumps({"accepts": options}).encode()))

    monkeypatch.setattr("probe.request.urlopen", unpaid_response)


def test_policy_compatible_option_selected_when_not_first(monkeypatch):
    from probe import probe_unpaid_challenge

    good = {"network": BASE_MAINNET, "asset": USDC_BASE, "scheme": "exact",
            "amount": "2000", "payTo": "0x1111111111111111111111111111111111111111"}
    options = [dict(good, network="eip155:1"), dict(good, asset="wrong-asset"),
               dict(good, scheme="upto"), dict(good, payTo=""), good]
    verifier = load_registry(ROOT / "registry.json")[0]
    _mock_402(monkeypatch, options)
    result = probe_unpaid_challenge(verifier, "https://example.com")
    assert result.status == "PAYMENT_REQUIRED"
    assert result.advertised_network == BASE_MAINNET
    assert result.advertised_asset == USDC_BASE
    assert result.advertised_scheme == "exact"
    assert result.advertised_amount_atomic == "2000"
    assert SafeX402Payer().preflight(verifier, "https://example.com").amount_usd == Decimal("0.002")
    _mock_402(monkeypatch, list(reversed(options)))
    assert SafeX402Payer().dry_run(verifier, "https://example.com").status == "AUTHORIZED_NOT_PAID"


def test_no_policy_compatible_option_selected(monkeypatch):
    from probe import probe_unpaid_challenge

    good = {"network": BASE_MAINNET, "asset": USDC_BASE, "scheme": "exact",
            "amount": "2000", "payTo": "0x1111111111111111111111111111111111111111"}
    options = [dict(good, network="eip155:1"), dict(good, asset="wrong-asset"),
               dict(good, scheme="upto"), dict(good, payTo=""),
               dict(good, amount="invalid")]
    verifier = load_registry(ROOT / "registry.json")[0]
    _mock_402(monkeypatch, options)
    result = probe_unpaid_challenge(verifier, "https://example.com")
    assert result.status == "NO_COMPATIBLE_PAYMENT_OPTION"
    assert all(getattr(result, field) is None for field in (
        "advertised_network", "advertised_asset", "advertised_scheme",
        "advertised_amount_atomic", "advertised_pay_to"))
    assert SafeX402Payer().dry_run(verifier, "https://example.com").status == "BLOCKED"
    # Empty allowlists must be forwarded, not replaced by probe defaults.
    _mock_402(monkeypatch, [good])
    for field in ("allowed_networks", "allowed_assets", "allowed_schemes"):
        payer = SafeX402Payer(SpendPolicy(**{field: frozenset()}))
        result = payer.dry_run(verifier, "https://example.com")
        assert result.status == "BLOCKED"
        assert "NO_COMPATIBLE_PAYMENT_OPTION" in result.error
        try:
            payer.preflight(verifier, "https://example.com")
        except SpendPolicyError as exc:
            assert "NO_COMPATIBLE_PAYMENT_OPTION" in str(exc)
        else:
            raise AssertionError("expected preflight block")

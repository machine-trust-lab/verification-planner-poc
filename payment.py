from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, asdict
from decimal import Decimal
from typing import Iterable
from urllib.parse import urlsplit

from planner import Verifier
from probe import ProbeResult, probe_unpaid_challenge, request_parts_for

BASE_MAINNET = "eip155:8453"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
USDC_DECIMALS = 6
LIVE_ACK = "I_UNDERSTAND_THIS_SPENDS_USDC"


class SpendPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class SpendPolicy:
    max_per_call_usd: Decimal = Decimal("0.01")
    max_total_usd: Decimal = Decimal("0.05")
    allowed_networks: frozenset[str] = frozenset({BASE_MAINNET})
    allowed_assets: frozenset[str] = frozenset({USDC_BASE.lower()})
    allowed_schemes: frozenset[str] = frozenset({"exact"})
    # PoC rule: challenge may not exceed the hand-maintained registry quote.
    enforce_registry_price_ceiling: bool = True


@dataclass(frozen=True)
class PaymentQuote:
    verifier_id: str
    amount_atomic: int
    amount_usd: Decimal
    network: str
    asset: str
    scheme: str
    pay_to: str

    def to_dict(self):
        d = asdict(self)
        d["amount_usd"] = str(self.amount_usd)
        return d


@dataclass
class SpendLedger:
    """Local authorization control, not a cryptographic guarantee of on-chain spend.

    A server may change the challenge between preflight and paid retry. Transport
    or RPC errors may leave settlement uncertain and absent from this ledger.
    Never automatically retry an ambiguous payment; inspect settlement first.
    """
    committed_usd: Decimal = Decimal("0")

    def remaining(self, policy: SpendPolicy) -> Decimal:
        return policy.max_total_usd - self.committed_usd

    def authorize(self, quote: PaymentQuote, verifier: Verifier, policy: SpendPolicy) -> None:
        if quote.network not in policy.allowed_networks:
            raise SpendPolicyError(f"network not allowed: {quote.network}")
        if quote.asset.lower() not in policy.allowed_assets:
            raise SpendPolicyError(f"asset not allowed: {quote.asset}")
        if quote.scheme not in policy.allowed_schemes:
            raise SpendPolicyError(f"scheme not allowed: {quote.scheme}")
        if quote.amount_usd > policy.max_per_call_usd:
            raise SpendPolicyError(
                f"per-call cap exceeded: ${quote.amount_usd} > ${policy.max_per_call_usd}"
            )
        if policy.enforce_registry_price_ceiling and quote.amount_usd > Decimal(str(verifier.price_usd)):
            raise SpendPolicyError(
                f"live challenge price ${quote.amount_usd} exceeds registry quote ${verifier.price_usd}"
            )
        if self.committed_usd + quote.amount_usd > policy.max_total_usd:
            raise SpendPolicyError(
                f"session cap exceeded: ${self.committed_usd + quote.amount_usd} > ${policy.max_total_usd}"
            )

    def commit(self, quote: PaymentQuote) -> None:
        self.committed_usd += quote.amount_usd


def quote_from_probe(probe: ProbeResult) -> PaymentQuote:
    if probe.status != "PAYMENT_REQUIRED":
        raise SpendPolicyError(f"expected PAYMENT_REQUIRED, got {probe.status}")
    required = {
        "amount": probe.advertised_amount_atomic,
        "network": probe.advertised_network,
        "asset": probe.advertised_asset,
        "scheme": probe.advertised_scheme,
        "payTo": probe.advertised_pay_to,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise SpendPolicyError(f"incomplete x402 challenge, missing: {', '.join(missing)}")
    if str(probe.advertised_asset).lower() != USDC_BASE.lower():
        # The PoC only knows how to value Base USDC safely. Other assets need an
        # explicit decimals/price model rather than a guess.
        raise SpendPolicyError(f"unsupported asset for PoC valuation: {probe.advertised_asset}")
    atomic = int(str(probe.advertised_amount_atomic))
    usd = Decimal(atomic) / (Decimal(10) ** USDC_DECIMALS)
    return PaymentQuote(
        verifier_id=probe.verifier_id,
        amount_atomic=atomic,
        amount_usd=usd,
        network=str(probe.advertised_network),
        asset=str(probe.advertised_asset),
        scheme=str(probe.advertised_scheme),
        pay_to=str(probe.advertised_pay_to),
    )


@dataclass
class PaymentExecutionResult:
    verifier_id: str
    mode: str
    status: str
    quote: dict | None = None
    http_status: int | None = None
    response_excerpt: str | None = None
    error: str | None = None

    def to_dict(self):
        return asdict(self)


class SafeX402Payer:
    """PoC payer with local authorization controls.

    DRY RUN is dependency-free and cannot spend. LIVE mode is opt-in and uses
    the official x402 Python SDK if installed. Before invoking the SDK it probes
    the 402 challenge and enforces network/asset/scheme, per-call, session and
    registry-price limits.

    The PoC deliberately expects a dedicated low-balance wallet. A malicious
    server could change its challenge between preflight and the SDK retry, so a
    low wallet balance remains a final external blast-radius cap. Production
    should additionally use SDK-native spend controls/hooks where available.
    """

    def __init__(self, policy: SpendPolicy | None = None, ledger: SpendLedger | None = None):
        self.policy = policy or SpendPolicy()
        self.ledger = ledger or SpendLedger()

    def preflight(self, verifier: Verifier, target: str) -> PaymentQuote:
        probe = probe_unpaid_challenge(
            verifier, target,
            allowed_networks=self.policy.allowed_networks,
            allowed_assets=self.policy.allowed_assets,
            allowed_schemes=self.policy.allowed_schemes,
        )
        quote = quote_from_probe(probe)
        self.ledger.authorize(quote, verifier, self.policy)
        return quote

    def dry_run(self, verifier: Verifier, target: str, synthetic_probe: ProbeResult | None = None) -> PaymentExecutionResult:
        try:
            probe = synthetic_probe or probe_unpaid_challenge(
                verifier, target,
                allowed_networks=self.policy.allowed_networks,
                allowed_assets=self.policy.allowed_assets,
                allowed_schemes=self.policy.allowed_schemes,
            )
            quote = quote_from_probe(probe)
            self.ledger.authorize(quote, verifier, self.policy)
            return PaymentExecutionResult(
                verifier_id=verifier.id,
                mode="DRY_RUN",
                status="AUTHORIZED_NOT_PAID",
                quote=quote.to_dict(),
            )
        except Exception as exc:
            return PaymentExecutionResult(
                verifier_id=verifier.id,
                mode="DRY_RUN",
                status="BLOCKED",
                error=str(exc),
            )

    def live(self, verifier: Verifier, target: str, private_key: str | None = None) -> PaymentExecutionResult:
        if os.getenv("X402_LIVE_PAYMENT_ACK") != LIVE_ACK:
            return PaymentExecutionResult(
                verifier_id=verifier.id,
                mode="LIVE",
                status="BLOCKED",
                error=(
                    "live spending disabled; set X402_LIVE_PAYMENT_ACK=" + LIVE_ACK
                    + " only after funding a dedicated low-balance wallet"
                ),
            )
        private_key = private_key or os.getenv("PAYER_PRIVATE_KEY")
        if not private_key:
            return PaymentExecutionResult(
                verifier_id=verifier.id,
                mode="LIVE",
                status="BLOCKED",
                error="PAYER_PRIVATE_KEY is not set",
            )

        try:
            quote = self.preflight(verifier, target)
        except Exception as exc:
            return PaymentExecutionResult(verifier.id, "LIVE", "BLOCKED", error=str(exc))

        try:
            # Imports are intentionally inside LIVE mode so the entire PoC can be
            # tested without wallet/payment dependencies installed.
            import httpx  # type: ignore
            from eth_account import Account  # type: ignore
            from x402.client import x402Client  # type: ignore
            from x402.http.clients.httpx import wrapHttpxWithPayment  # type: ignore
            from x402.mechanisms.evm.exact import register_exact_evm_client  # type: ignore
        except Exception as exc:
            return PaymentExecutionResult(
                verifier.id,
                "LIVE",
                "BLOCKED",
                quote=quote.to_dict(),
                error=f"live dependencies unavailable: {exc}. Install: pip install x402 httpx eth-account",
            )

        async def _pay():
            account = Account.from_key(private_key)
            client = x402Client()
            register_exact_evm_client(client, account)

            parts = request_parts_for(verifier, target)
            split = urlsplit(parts["url"])
            base_url = f"{split.scheme}://{split.netloc}"
            path = split.path or "/"
            if split.query:
                path += "?" + split.query

            async with wrapHttpxWithPayment(client, base_url=base_url) as paid_http:
                kwargs = {}
                if parts.get("json") is not None:
                    kwargs["json"] = parts["json"]
                if parts.get("headers"):
                    kwargs["headers"] = parts["headers"]
                response = await paid_http.request(verifier.method, path, **kwargs)
                return response

        try:
            response = asyncio.run(_pay())
            if response.status_code >= 400:
                return PaymentExecutionResult(
                    verifier.id,
                    "LIVE",
                    "PAID_CALL_FAILED",
                    quote=quote.to_dict(),
                    http_status=response.status_code,
                    response_excerpt=response.text[:500],
                )
            self.ledger.commit(quote)
            return PaymentExecutionResult(
                verifier.id,
                "LIVE",
                "PAID_CALL_SUCCEEDED",
                quote=quote.to_dict(),
                http_status=response.status_code,
                response_excerpt=response.text[:1000],
            )
        except Exception as exc:
            # Deliberately do not commit spend to the local ledger on an exception;
            # x402 settlement can be pending in rare failure modes. Before retrying
            # a failed live call, inspect the payment/chain receipt manually.
            return PaymentExecutionResult(
                verifier.id,
                "LIVE",
                "PAYMENT_OR_CALL_ERROR",
                quote=quote.to_dict(),
                error=str(exc),
            )

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, asdict
from urllib import parse, request, error

from planner import Verifier


@dataclass
class ProbeResult:
    verifier_id: str
    status: str
    http_status: int | None
    latency_ms: int | None
    advertised_amount_atomic: str | None = None
    advertised_network: str | None = None
    advertised_pay_to: str | None = None
    advertised_asset: str | None = None
    advertised_scheme: str | None = None
    error: str | None = None

    def to_dict(self):
        return asdict(self)


def _decode_payment_required(headers, body_bytes: bytes):
    raw = headers.get("PAYMENT-REQUIRED") or headers.get("payment-required")
    if raw:
        try:
            pad = "=" * (-len(raw) % 4)
            return json.loads(base64.b64decode(raw + pad).decode())
        except Exception:
            pass
    try:
        obj = json.loads(body_bytes.decode())
        if isinstance(obj, dict):
            return obj
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            return obj[0]
    except Exception:
        pass
    return {}


def request_parts_for(verifier: Verifier, target: str) -> dict:
    endpoint = verifier.endpoint
    headers = {"User-Agent": "minimal-verification-planner-poc/0.2"}
    json_body = None

    if verifier.target_transport == "query:url":
        endpoint += ("&" if "?" in endpoint else "?") + parse.urlencode({"url": target})
    elif verifier.target_transport == "json:url":
        json_body = {"url": target, "check": "V2_B64_URLSAFE"}
        headers["Content-Type"] = "application/json"
    elif verifier.target_transport == "json:resource":
        json_body = {"resource": target}
        headers["Content-Type"] = "application/json"

    return {"url": endpoint, "headers": headers, "json": json_body}


def _request_for(verifier: Verifier, target: str):
    parts = request_parts_for(verifier, target)
    data = json.dumps(parts["json"]).encode() if parts["json"] is not None else None
    return request.Request(parts["url"], data=data, headers=parts["headers"], method=verifier.method)


def _select_payment_option(accepts, allowed_networks, allowed_assets, allowed_schemes):
    """Select a complete compatible option, independent of server list order.

    Sort by network, normalized asset, scheme, atomic amount, then recipient.
    Amounts are compared only within the same network/asset/scheme group.
    """
    assets = {asset.lower() for asset in allowed_assets}
    compatible = []
    for option in accepts if isinstance(accepts, list) else []:
        if not isinstance(option, dict):
            continue
        if any(not isinstance(option.get(key), str) or not option[key].strip()
               for key in ("network", "asset", "scheme", "payTo")):
            continue
        amount = option.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (str, int)):
            continue
        if not str(amount).isascii() or not str(amount).isdigit():
            continue
        if (option["network"] in allowed_networks
                and option["asset"].lower() in assets
                and option["scheme"] in allowed_schemes):
            compatible.append(option)
    return min(compatible, key=lambda option: (
        option["network"], option["asset"].lower(), option["scheme"],
        int(option["amount"]), option["payTo"], option["asset"], str(option["amount"]),
    ), default=None)


def probe_unpaid_challenge(
    verifier: Verifier, target: str, timeout: float = 10.0, *,
    allowed_networks: frozenset[str] = frozenset({"eip155:8453"}),
    allowed_assets: frozenset[str] = frozenset({"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"}),
    allowed_schemes: frozenset[str] = frozenset({"exact"}),
) -> ProbeResult:
    """Probe an x402 endpoint without signing or paying.

    A 402 with a complete policy-compatible option is PAYMENT_REQUIRED. This is safe by design: this
    function never creates a payment signature and cannot move funds.
    """
    req = _request_for(verifier, target)
    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            elapsed = round((time.perf_counter() - started) * 1000)
            return ProbeResult(verifier.id, "UNEXPECTED_FREE_RESPONSE", resp.status, elapsed)
    except error.HTTPError as exc:
        body = exc.read()
        elapsed = round((time.perf_counter() - started) * 1000)
        if exc.code != 402:
            return ProbeResult(verifier.id, "HTTP_ERROR", exc.code, elapsed, error=body[:300].decode(errors="replace"))
        payment = _decode_payment_required(exc.headers, body)
        accepts = payment.get("accepts") if isinstance(payment, dict) else []
        chosen = _select_payment_option(
            accepts, allowed_networks, allowed_assets, allowed_schemes,
        )
        if chosen is None:
            return ProbeResult(
                verifier.id, "NO_COMPATIBLE_PAYMENT_OPTION", 402, elapsed,
                error="No complete payment option matches the active network/asset/scheme policy",
            )
        return ProbeResult(
            verifier.id,
            "PAYMENT_REQUIRED",
            402,
            elapsed,
            advertised_amount_atomic=str(chosen.get("amount")) if chosen.get("amount") is not None else None,
            advertised_network=chosen.get("network"),
            advertised_pay_to=chosen.get("payTo"),
            advertised_asset=chosen.get("asset"),
            advertised_scheme=chosen.get("scheme"),
        )
    except Exception as exc:
        elapsed = round((time.perf_counter() - started) * 1000)
        return ProbeResult(verifier.id, "NETWORK_ERROR", None, elapsed, error=str(exc))

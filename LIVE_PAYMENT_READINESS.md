# Live payment readiness — PoC v0.2.1

## Status

**Experimental live code path; no real payment has been executed from this build environment.**

The first intended real transaction is intentionally tiny:

1. Planner asks only for `protocol_conformance`.
2. It selects `x402check` as the cheapest registry supplier.
3. The adapter probes without paying and deterministically selects a complete
   option matching the active network/asset/scheme policy. If none exists, it
   returns `NO_COMPATIBLE_PAYMENT_OPTION`.
4. It rejects the payment unless it is Base mainnet + Base USDC + exact scheme,
   <= $0.01, <= the registry quote, and within the $0.05 session cap.
5. Only with an explicit live acknowledgement and a wallet key does the official
   x402 SDK get invoked.

Current x402check public pricing snapshot: $0.002/call.

## Wallet rule

Use a fresh dedicated wallet with only a few cents of USDC. Never use a wallet
holding meaningful funds or other assets.

## Stop conditions

Abort rather than pay if any of these change unexpectedly:

- network is not `eip155:8453`;
- asset is not Base USDC;
- scheme is not `exact`;
- amount is above the registry quote or the local per-call cap;
- `payTo`/challenge fields are incomplete;
- the unpaid probe fails or returns something other than a valid 402 challenge.

## Retry rule

Do not blindly retry a failed live paid request. Current x402 SDKs explicitly
model settlement-pending cases where a transaction may already have been
broadcast despite an RPC/receipt timeout. Inspect the receipt/chain state first.


## Current limitations

- Registry metadata is hand-maintained and is not independently proven.
- Target compatibility is not yet considered during planning.
- Declared diversity does not prove real operational independence.
- Discovery in this PoC is still static.

Discovery and planning are complementary: a future registry could be populated
from x402 discovery/Bazaar, while this planner decides which combination of
services satisfies the assurance policy. Discovery integration is not implemented
in this PoC.

## Authorization boundary

The `$0.01` per-call and `$0.05` per-session limits are **local authorization
controls**, not cryptographic guarantees of total on-chain spend. A server can
change its challenge between unpaid preflight and the paid retry. Transport/RPC
errors may leave settlement uncertain, so the local ledger may not reflect all
on-chain spend. **No automatic retry on ambiguity**: inspect the receipt and
chain state before deciding whether to retry.

# PoC report — Minimal Verification Planner v0.2.1

## Hypothesis
A machine can express *what it wants verified* rather than naming a specific verifier, and a deterministic planner can purchase/select the cheapest supplier portfolio that satisfies the request.

## Minimal decision logic
A portfolio is valid only when all of the following hold:
1. Every required claim is covered.
2. Total quoted price is within budget.
3. Minimum number of distinct operators is met.
4. Minimum number of declared evidence/source classes is met.

Among valid portfolios, choose the cheapest. No probabilistic confidence is invented.

## Example
Request: protocol conformance + settlement history, 2 operators, 2 source classes, <= $0.01.

Candidates:
- x402check: conformance/reachability, $0.002.
- x402 Trust Prober: historical reliability/settlements, $0.005.
- 10x402: conformance, $0.004.

Winner: x402check + Trust Prober = $0.007.
Alternative: 10x402 + Trust Prober = $0.009.

## What this proves
It proves only that the *planning primitive* is simple and implementable.
It does not yet prove market demand, that the verifier claims are correct, or that a multi-verifier portfolio is economically superior in real deployments.

## Kill criterion for the next phase
If real developers do not see value in asking for a verification outcome/policy rather than selecting one vendor directly, stop or pivot before adding advanced trust machinery.

## v0.2.1 payment-adapter milestone

A payer layer with local authorization controls has been added without changing the planner's core.
The default live policy permits only Base mainnet USDC using the `exact` scheme,
with a $0.01 per-call cap and $0.05 session cap. A live challenge is also
rejected when its price exceeds the registry snapshot.

The first intended real transaction is intentionally a single $0.002 x402check
call. No live funds were moved in the build environment because it has no
outbound package/network access and no wallet credentials were supplied.

This phase demonstrates planning and local preflight authorization checks; it
does not prove safe live payment execution or successful on-chain settlement.


## Current limitations

- Registry metadata is hand-maintained and is not independently proven.
- Target compatibility is not yet considered during planning.
- Declared diversity does not prove real operational independence.
- Discovery in this PoC is still static.

Discovery and planning are complementary: a future registry could be populated
from x402 discovery/Bazaar, while this planner decides which combination of
services satisfies the assurance policy. Discovery integration is not implemented
in this PoC.

The `$0.01` per-call and `$0.05` per-session limits are **local authorization
controls**, not cryptographic guarantees of total on-chain spend. A server can
change its challenge between unpaid preflight and the paid retry. Transport/RPC
errors may leave settlement uncertain, so the local ledger may not reflect all
on-chain spend. **No automatic retry on ambiguity**: inspect the receipt and
chain state before deciding whether to retry.

The unpaid probe now deterministically selects a complete policy-compatible
option, or returns `NO_COMPATIBLE_PAYMENT_OPTION`. Existing caps are unchanged.

# Verification Planner PoC v0.2.1

A deliberately small proof-of-concept exploring one question:

> Can software automatically choose the cheapest sufficient portfolio of machine-verification services for a requested set of claims?

## Why this exists

Autonomous agents increasingly interact with external APIs, payment endpoints, and other machine services. Different verification providers can check different claims — for example protocol conformance, current reachability, or settlement history — but an agent still has to decide which checks are actually needed and how much verification is worth buying.

This project tests a minimal planning primitive: describe what needs to be verified, set hard constraints such as budget and provider diversity, and let a deterministic planner select the cheapest portfolio that satisfies those constraints.

Discovery and planning are complementary: a future registry could be populated
from x402 discovery/Bazaar, while this planner decides which combination of
services satisfies the assurance policy. Discovery integration is not implemented
in this PoC.

## What v0.2.1 does

- Reads a tiny registry of current x402 verification services.
- Accepts required claims, budget, minimum operator diversity, and minimum declared source-class diversity.
- Exhaustively finds the cheapest portfolio satisfying those hard constraints.
- Parses unpaid HTTP `402 Payment Required` challenges.
- Includes a guarded payment adapter with local authorization limits and dry-run support.
- Does **not** make a live payment unless explicit wallet credentials and a live-payment acknowledgement are supplied.

## Example

A request requires:

- `protocol_conformance`
- `settlement_history`
- at least 2 operators
- at least 2 declared source classes
- maximum cost: `$0.01`

The current registry snapshot contains:

- `x402check` — protocol conformance / live preflight — `$0.002`
- `x402 Trust Prober` — historical reliability / settlement history — `$0.005`
- `10x402` — competing conformance check — `$0.004`

The planner selects:

- `x402check`
- `x402 Trust Prober`
- total quoted cost: **$0.007**

The alternative combination `10x402 + Trust Prober` also satisfies the policy but costs `$0.009`, so it is rejected as non-optimal.

## What this project is NOT claiming

This PoC does not prove that:

- multiple verifiers automatically imply truth;
- declared evidence sources prove real independence;
- verification guarantees a real-world outcome;
- multi-provider verification is economically superior in production;
- historical telemetry will necessarily become a defensible data moat.

Those are later hypotheses, not assumptions built into the MVP.

## Current limitations

- Registry metadata is hand-maintained and is not independently proven.
- Target compatibility is not yet considered during planning.
- Declared diversity does not prove real operational independence.
- Discovery in this PoC is still static.

## Deliberately out of scope

No proprietary trust score, machine learning, hidden-dependency inference, cryptographic lineage, reputation network, token, new blockchain, new receipt format, or marketplace UI.

## Safety

Live spending is disabled by default. The payment adapter applies these checks during unpaid preflight:

- Base mainnet only (`eip155:8453`)
- Base USDC only
- `exact` scheme only
- maximum `$0.01` per call
- maximum `$0.05` per process/session
- live 402 price may not exceed the registry snapshot price

The `$0.01` per-call and `$0.05` per-session limits are **local authorization
controls**, not cryptographic guarantees of total on-chain spend. A server can
change its challenge between unpaid preflight and the paid retry. Transport/RPC
errors may leave settlement uncertain, so the local ledger may not reflect all
on-chain spend. **No automatic retry on ambiguity**: inspect the receipt and
chain state before deciding whether to retry.

**Never commit private keys, seed phrases, API keys, or wallet credentials to this repository.**

## Run locally

Python 3.10+.

```bash
python demo.py
```

Dry-run payment flow:

```bash
python live_demo.py
```

Tests:

```bash
pytest -q
```

## Current objective

The immediate goal is not fundraising or product launch. It is to falsify the core hypothesis:

> Is automated procurement of sufficient machine evidence a useful infrastructure primitive, or should verification remain hard-coded inside individual agent systems?

Critical technical feedback is welcome.

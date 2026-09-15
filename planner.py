from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Iterable
import json


@dataclass(frozen=True)
class Verifier:
    id: str
    operator: str
    claims: frozenset[str]
    source_classes: frozenset[str]
    price_usd: float
    method: str
    endpoint: str
    target_transport: str
    notes: str = ""


@dataclass(frozen=True)
class VerificationRequest:
    target: str
    required_claims: frozenset[str]
    max_cost_usd: float
    min_operators: int = 1
    min_source_classes: int = 1


@dataclass(frozen=True)
class Plan:
    verifiers: tuple[Verifier, ...]
    total_cost_usd: float
    covered_claims: frozenset[str]
    operators: frozenset[str]
    source_classes: frozenset[str]

    @property
    def status(self) -> str:
        return "PLAN_FOUND"


@dataclass(frozen=True)
class NoPlan:
    reason: str

    @property
    def status(self) -> str:
        return "NO_PLAN"


def load_registry(path: str | Path) -> list[Verifier]:
    raw = json.loads(Path(path).read_text())
    return [
        Verifier(
            id=item["id"],
            operator=item["operator"],
            claims=frozenset(item["claims"]),
            source_classes=frozenset(item["source_classes"]),
            price_usd=float(item["price_usd"]),
            method=item["method"].upper(),
            endpoint=item["endpoint"],
            target_transport=item["target_transport"],
            notes=item.get("notes", ""),
        )
        for item in raw
    ]


def _evaluate(combo: Iterable[Verifier]) -> Plan:
    combo = tuple(combo)
    return Plan(
        verifiers=combo,
        total_cost_usd=round(sum(v.price_usd for v in combo), 9),
        covered_claims=frozenset().union(*(v.claims for v in combo)),
        operators=frozenset(v.operator for v in combo),
        source_classes=frozenset().union(*(v.source_classes for v in combo)),
    )


def plan_verification(req: VerificationRequest, registry: list[Verifier]) -> Plan | NoPlan:
    """Return the cheapest portfolio satisfying hard constraints.

    This deliberately does *not* invent trust scores or probabilistic confidence.
    It only reasons over declared capabilities, operator diversity, source-class
    diversity and price.
    """
    candidates = [v for v in registry if v.claims & req.required_claims]
    valid: list[Plan] = []

    for size in range(1, len(candidates) + 1):
        for combo in combinations(candidates, size):
            p = _evaluate(combo)
            if not req.required_claims.issubset(p.covered_claims):
                continue
            if p.total_cost_usd > req.max_cost_usd + 1e-12:
                continue
            if len(p.operators) < req.min_operators:
                continue
            if len(p.source_classes) < req.min_source_classes:
                continue
            valid.append(p)

    if not valid:
        missing = req.required_claims - frozenset().union(*(v.claims for v in candidates)) if candidates else req.required_claims
        if missing:
            return NoPlan(f"No verifier in registry covers claims: {sorted(missing)}")
        return NoPlan("No portfolio satisfies budget/diversity constraints")

    # Cheapest first; then fewer suppliers; then more source diversity.
    valid.sort(key=lambda p: (p.total_cost_usd, len(p.verifiers), -len(p.source_classes)))
    return valid[0]

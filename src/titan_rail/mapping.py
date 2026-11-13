"""Shipping method mapping ladder.

Three rungs, tried in order: exact catalog id, alias table, guarded fuzzy.
When confidence is not there, the answer is UNMAPPED with ranked candidates
for a human, never a guess. Ambiguity between two close candidates also
refuses to map: a wrong carrier booked confidently is worse than a queue item.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Sequence

from .models import MappingDecision

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(value: str) -> str:
    """Lowercase, replace punctuation with spaces, collapse whitespace."""

    return " ".join(_NON_ALNUM.sub(" ", value.lower()).split())


@dataclass(frozen=True)
class ShippingMethod:
    """One entry of the carrier method catalog."""

    method_id: str
    name: str
    carrier: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Candidate:
    method: ShippingMethod
    score: float


@dataclass
class MappingOutcome:
    """Result of one trip down the ladder, evidence included."""

    decision: MappingDecision
    reason: str
    method: ShippingMethod | None
    normalized: str
    steps: list[tuple[str, bool, str]] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)


def load_catalog(path: Path) -> list[ShippingMethod]:
    """Load a method catalog from a JSON file (see fixtures/shipping_methods.json)."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    methods: list[ShippingMethod] = []
    for entry in raw["methods"]:
        methods.append(
            ShippingMethod(
                method_id=str(entry["id"]),
                name=str(entry["name"]),
                carrier=str(entry["carrier"]),
                aliases=tuple(str(a) for a in entry.get("aliases", ())),
            )
        )
    return methods


class MethodMapper:
    """Maps free-form shipping method values to catalog ids without guessing.

    Tunables:
      fuzzy_threshold: minimum similarity for the fuzzy rung to map at all.
      ambiguity_margin: minimum gap between the top two scores; closer than
        this is ambiguous and maps to UNMAPPED.
      candidate_floor: minimum score for a method to appear as a candidate.
      max_candidates: cap on the candidate list returned for human review.
    """

    def __init__(
        self,
        methods: Sequence[ShippingMethod],
        *,
        fuzzy_threshold: float = 0.85,
        ambiguity_margin: float = 0.05,
        candidate_floor: float = 0.5,
        max_candidates: int = 3,
    ) -> None:
        self._methods = list(methods)
        self._fuzzy_threshold = fuzzy_threshold
        self._ambiguity_margin = ambiguity_margin
        self._candidate_floor = candidate_floor
        self._max_candidates = max_candidates

        self._by_id: dict[str, ShippingMethod] = {
            m.method_id.lower(): m for m in self._methods
        }
        # The display name behaves as an implicit alias; explicit aliases win
        # on insertion order only when they collide, which the catalog avoids.
        self._by_alias: dict[str, ShippingMethod] = {}
        for m in self._methods:
            for alias in (m.name, *m.aliases):
                self._by_alias.setdefault(normalize(alias), m)

    def map_value(self, value: str) -> MappingOutcome:
        normalized = normalize(value)
        steps: list[tuple[str, bool, str]] = []

        if not normalized:
            steps.append(
                (
                    "exact_id",
                    False,
                    "input is empty after normalization; nothing to look up",
                )
            )
            return MappingOutcome(
                decision="UNMAPPED",
                reason=(
                    "empty shipping method value; refusing to guess, route this "
                    "order to review"
                ),
                method=None,
                normalized=normalized,
                steps=steps,
            )

        # Rung 1: exact catalog id. Ids keep their hyphens, so the lookup key
        # is the raw value stripped and lowercased, not the normalized form.
        id_key = value.strip().lower()
        exact = self._by_id.get(id_key)
        if exact is not None:
            steps.append(
                (
                    "exact_id",
                    True,
                    f"catalog id '{id_key}' matched {exact.method_id} ({exact.name})",
                )
            )
            return MappingOutcome(
                decision="MAPPED_EXACT",
                reason=f"exact catalog id match: {exact.method_id}",
                method=exact,
                normalized=normalized,
                steps=steps,
            )
        steps.append(("exact_id", False, f"no catalog method with id '{id_key}'"))

        # Rung 2: alias table on the normalized value.
        aliased = self._by_alias.get(normalized)
        if aliased is not None:
            steps.append(
                (
                    "alias",
                    True,
                    f"alias '{normalized}' resolved to {aliased.method_id} "
                    f"({aliased.name})",
                )
            )
            return MappingOutcome(
                decision="MAPPED_ALIAS",
                reason=f"alias table match: '{normalized}' is {aliased.method_id}",
                method=aliased,
                normalized=normalized,
                steps=steps,
            )
        steps.append(
            (
                "alias",
                False,
                f"no alias entry for '{normalized}' "
                f"({len(self._by_alias)} aliases checked)",
            )
        )

        # Rung 3: guarded fuzzy. Scores every method, maps only an
        # unambiguous winner above the threshold.
        scored = sorted(
            (Candidate(method=m, score=self._score(normalized, m)) for m in self._methods),
            key=lambda c: (-c.score, c.method.method_id),
        )
        candidates = [
            c for c in scored if c.score >= self._candidate_floor
        ][: self._max_candidates]

        if not scored or scored[0].score < self._fuzzy_threshold:
            best_note = (
                f"best candidate {scored[0].method.method_id} scored "
                f"{scored[0].score:.2f}, below threshold {self._fuzzy_threshold:.2f}"
                if scored
                else "catalog is empty, nothing to score"
            )
            steps.append(("fuzzy", False, best_note))
            return MappingOutcome(
                decision="UNMAPPED",
                reason=(
                    f"no reliable mapping for '{value.strip()}'; returning "
                    f"{len(candidates)} candidate(s) for human review instead "
                    "of guessing"
                ),
                method=None,
                normalized=normalized,
                steps=steps,
                candidates=candidates,
            )

        top = scored[0]
        runner_up = scored[1] if len(scored) > 1 else None
        if (
            runner_up is not None
            and top.score - runner_up.score < self._ambiguity_margin
        ):
            steps.append(
                (
                    "fuzzy",
                    False,
                    f"ambiguous: {top.method.method_id} ({top.score:.2f}) and "
                    f"{runner_up.method.method_id} ({runner_up.score:.2f}) are "
                    f"within {self._ambiguity_margin:.2f} of each other",
                )
            )
            return MappingOutcome(
                decision="UNMAPPED",
                reason=(
                    f"ambiguous fuzzy match for '{value.strip()}'; two catalog "
                    "methods score nearly the same, refusing to pick one"
                ),
                method=None,
                normalized=normalized,
                steps=steps,
                candidates=candidates,
            )

        steps.append(
            (
                "fuzzy",
                True,
                f"unambiguous fuzzy match {top.method.method_id} "
                f"({top.method.name}) with score {top.score:.2f}",
            )
        )
        return MappingOutcome(
            decision="MAPPED_FUZZY",
            reason=(
                f"fuzzy match above threshold: '{normalized}' resolves to "
                f"{top.method.method_id} with score {top.score:.2f}"
            ),
            method=top.method,
            normalized=normalized,
            steps=steps,
            candidates=candidates,
        )

    def _score(self, normalized_value: str, method: ShippingMethod) -> float:
        targets = [normalize(method.name), *(normalize(a) for a in method.aliases)]
        return max(
            SequenceMatcher(None, normalized_value, target).ratio()
            for target in targets
        )

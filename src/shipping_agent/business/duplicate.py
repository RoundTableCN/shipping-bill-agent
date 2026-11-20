"""Safe candidate de-duplication.

Only the same source_position_id is merged. Distinct source rows are kept even
when their values look identical, because two real charges can share a name and
amount.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from pydantic import Field

from ..models.base import StrictModel
from ..models.candidate import RawChargeLine
from .charge_mapper import normalize_charge


class DuplicateReport(StrictModel):
    kept: list[RawChargeLine] = Field(default_factory=list)
    merged: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def dedupe_candidates(candidates: list[RawChargeLine]) -> DuplicateReport:
    kept: list[RawChargeLine] = []
    merged: list[str] = []
    warnings: list[str] = []
    seen: dict[str, RawChargeLine] = {}

    for candidate in candidates:
        previous = seen.get(candidate.source_position_id)
        if previous is not None:
            merged.append(candidate.line_id)
            if not any(
                warning.startswith(f"E_DUPLICATE_LINE: {candidate.line_id}")
                for warning in warnings
            ):
                warnings.append(
                    f"E_DUPLICATE_LINE: {candidate.line_id} merged into "
                    f"{previous.line_id} (same source position)"
                )
            continue
        seen[candidate.source_position_id] = candidate
        kept.append(candidate)

    groups: dict[tuple[str, Decimal | None, str | None], list[RawChargeLine]] = defaultdict(list)
    for candidate in kept:
        key = (
            normalize_charge(candidate.charge_raw or ""),
            _amount(candidate.amount_raw),
            (candidate.currency_raw or "").upper() or None,
        )
        groups[key].append(candidate)

    for (name, amount, currency), group in groups.items():
        if len(group) > 1 and name:
            ids = ", ".join(item.line_id for item in group)
            warnings.append(
                f"W_POSSIBLE_DUPLICATE: {name} / {amount} / {currency} kept "
                f"as separate rows ({ids})"
            )

    return DuplicateReport(kept=kept, merged=merged, warnings=warnings)


def _amount(raw: str | None) -> Decimal | None:
    from ..io.text_normalize import parse_amount

    return parse_amount(raw)

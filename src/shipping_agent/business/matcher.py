"""Bill matching: strict four levels, then enhanced identity matching."""

from __future__ import annotations

import re

from pydantic import Field

from ..extract.models import DocumentClassification, ExtractedCharge
from ..models.base import StrictModel
from ..models.output import MatchAttempt, MatchCandidate
from .charge_mapper import normalize_charge
from .repository import BillRepository, ExistingBill, ExistingCharge

STRICT_LEVELS = ("STRICT_L1", "STRICT_L2", "STRICT_L3", "STRICT_L4")
ENHANCED_LEVELS = ("ENHANCED_E1", "ENHANCED_E2", "ENHANCED_E3", "ENHANCED_E4")


class MatchResult(StrictModel):
    candidate_id: str
    matched: bool = False
    bill: ExistingBill | None = None
    line: ExistingCharge | None = None
    rule: str | None = None
    ambiguous: bool = False
    amount_changed: bool = False
    candidates: list[MatchCandidate] = Field(default_factory=list)
    attempts: list[MatchAttempt] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _charge_key(name: str | None) -> str:
    return normalize_charge(name or "")


def _name_compatible(a: str | None, b: str | None) -> bool:
    ka, kb = _charge_key(a), _charge_key(b)
    if not ka or not kb:
        return False
    return ka == kb or ka in kb or kb in ka


def _same_currency(a: str | None, b: str | None) -> bool:
    return bool(a and b and a.upper() == b.upper())


def _same_date(a: str | None, b: str | None) -> bool:
    return bool(a and b and a == b)


def _same_party(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    na = re.sub(r"[^A-Z0-9]+", " ", a.upper()).strip()
    nb = re.sub(r"[^A-Z0-9]+", " ", b.upper()).strip()
    return bool(na and nb and (na == nb or na in nb or nb in na))


def _parties_match(classification: DocumentClassification, bill: ExistingBill) -> bool:
    left = [
        value
        for value in (
            classification.payer,
            classification.payee,
            *classification.issuer_candidates,
            *classification.recipient_candidates,
        )
        if value
    ]
    right = [
        value
        for value in (
            bill.payer,
            bill.payee,
            bill.parties.get("issuer"),
            bill.parties.get("recipient"),
        )
        if value
    ]
    if not left or not right:
        return True
    return any(_same_party(a, b) for a in left for b in right)


def _pair_key(bill: ExistingBill, line: ExistingCharge) -> str:
    return f"{bill.bill_id}::{line.line_id}"


class Matcher:
    def __init__(self, repository: BillRepository, mode: str = "strict"):
        if mode not in {"strict", "enhanced"}:
            raise ValueError("mode must be 'strict' or 'enhanced'")
        self.repository = repository
        self.mode = mode

    # -- bill selection -------------------------------------------------
    def _bills_for_level(
        self, level: str, classification: DocumentClassification
    ) -> list[ExistingBill]:
        if level.endswith("1"):
            return self.repository.by_reference_no(classification.reference_no)
        if level.endswith("2"):
            return self.repository.by_bl_no(classification.bl_no)
        if level.endswith("3"):
            return self.repository.by_booking_no(classification.booking_no)
        if level.endswith("4"):
            bills: dict[str, ExistingBill] = {}
            for container in classification.container_nos:
                for bill in self.repository.by_container(container):
                    bills[bill.bill_id] = bill
            return list(bills.values())
        return []

    # -- strict ---------------------------------------------------------
    def _strict_pairs(
        self,
        level: str,
        classification: DocumentClassification,
        charge: ExtractedCharge,
        used: set[str],
    ) -> list[tuple[ExistingBill, ExistingCharge]]:
        bills = self._bills_for_level(level, classification)
        charge_key = _charge_key(charge.charge_item or charge.charge_raw)
        pairs: list[tuple[ExistingBill, ExistingCharge]] = []

        for bill in bills:
            for line in bill.charges:
                if _pair_key(bill, line) in used:
                    continue
                line_key = _charge_key(line.charge_item)
                if not charge_key or not line_key:
                    continue

                if level == "STRICT_L1":
                    if line_key != charge_key:
                        continue
                elif level in {"STRICT_L2", "STRICT_L3"}:
                    if line_key != charge_key:
                        continue
                    if not _same_currency(line.currency, charge.currency):
                        continue
                else:  # STRICT_L4
                    if line_key != charge_key:
                        continue
                    if charge.amount is None or line.amount != charge.amount:
                        continue
                    if charge.currency and line.currency != charge.currency:
                        continue
                    if not _same_date(classification.document_date, bill.document_date):
                        continue
                    if not _parties_match(classification, bill):
                        continue

                pairs.append((bill, line))
        return pairs

    # -- enhanced -------------------------------------------------------
    def _enhanced_pairs(
        self,
        level: str,
        classification: DocumentClassification,
        charge: ExtractedCharge,
        used: set[str],
    ) -> list[tuple[ExistingBill, ExistingCharge]]:
        bills = self._bills_for_level(level, classification)
        pairs: list[tuple[ExistingBill, ExistingCharge]] = []
        for bill in bills:
            if level == "ENHANCED_E4":
                if not _same_date(classification.document_date, bill.document_date):
                    continue
                if not _parties_match(classification, bill):
                    continue
            for line in bill.charges:
                if _pair_key(bill, line) in used:
                    continue
                pairs.append((bill, line))
        return pairs

    # -- selection ------------------------------------------------------
    @staticmethod
    def _pick(
        pairs: list[tuple[ExistingBill, ExistingCharge]],
        charge: ExtractedCharge,
    ) -> tuple[tuple[ExistingBill, ExistingCharge] | None, bool]:
        if not pairs:
            return None, False
        if len(pairs) == 1:
            return pairs[0], False

        exact = [
            pair
            for pair in pairs
            if charge.amount is not None
            and pair[1].amount == charge.amount
            and (not charge.currency or pair[1].currency == charge.currency)
            and _name_compatible(
                pair[1].charge_item, charge.charge_item or charge.charge_raw
            )
        ]
        if len(exact) == 1:
            return exact[0], False
        return None, True

    @staticmethod
    def _candidate_list(
        pairs: list[tuple[ExistingBill, ExistingCharge]],
        charge: ExtractedCharge,
    ) -> list[MatchCandidate]:
        result: list[MatchCandidate] = []
        for bill, line in pairs:
            score = 0.5
            if charge.amount is not None and line.amount == charge.amount:
                score = 0.9
            if _charge_key(line.charge_item) == _charge_key(charge.charge_item or charge.charge_raw):
                score = min(1.0, score + 0.05)
            result.append(
                MatchCandidate(
                    bill_id=bill.bill_id,
                    line_id=line.line_id,
                    score=round(score, 2),
                    reason="candidate",
                )
            )
        return result

    # -- public ---------------------------------------------------------
    def match(
        self,
        classification: DocumentClassification,
        charges: list[ExtractedCharge],
    ) -> list[MatchResult]:
        used: set[str] = set()
        results: list[MatchResult] = []

        for charge in charges:
            attempts: list[MatchAttempt] = []
            result: MatchResult | None = None

            for level in STRICT_LEVELS:
                pairs = self._strict_pairs(level, classification, charge, used)
                attempts.append(
                    MatchAttempt(
                        rule=level,
                        matched=bool(pairs),
                        candidate_count=len(pairs),
                    )
                )
                if not pairs:
                    continue
                picked, ambiguous = self._pick(pairs, charge)
                if picked is not None:
                    bill, line = picked
                    result = MatchResult(
                        candidate_id=charge.candidate_id,
                        matched=True,
                        bill=bill,
                        line=line,
                        rule=level,
                        amount_changed=(
                            charge.amount is not None and line.amount != charge.amount
                        ),
                        attempts=attempts,
                        notes=[f"matched {level}"],
                    )
                else:
                    result = MatchResult(
                        candidate_id=charge.candidate_id,
                        matched=False,
                        ambiguous=True,
                        candidates=self._candidate_list(pairs, charge),
                        attempts=attempts,
                        notes=[f"{level} returned multiple candidates"],
                    )
                break

            if result is None and self.mode == "enhanced":
                for level in ENHANCED_LEVELS:
                    pairs = self._enhanced_pairs(
                        level, classification, charge, used
                    )
                    filtered = [
                        pair
                        for pair in pairs
                        if _name_compatible(
                            pair[1].charge_item,
                            charge.charge_item or charge.charge_raw,
                        )
                        and (
                            not charge.currency
                            or pair[1].currency == charge.currency
                        )
                    ]
                    attempts.append(
                        MatchAttempt(
                            rule=level,
                            matched=bool(filtered),
                            candidate_count=len(filtered),
                            note="identity match, amount not used",
                        )
                    )
                    if not filtered:
                        continue
                    picked, ambiguous = self._pick(filtered, charge)
                    if picked is not None:
                        bill, line = picked
                        result = MatchResult(
                            candidate_id=charge.candidate_id,
                            matched=True,
                            bill=bill,
                            line=line,
                            rule=level,
                            amount_changed=(
                                charge.amount is not None
                                and line.amount != charge.amount
                            ),
                            attempts=attempts,
                            notes=[f"matched {level}", "amount compared in stage B"],
                        )
                    else:
                        result = MatchResult(
                            candidate_id=charge.candidate_id,
                            matched=False,
                            ambiguous=True,
                            candidates=self._candidate_list(filtered, charge),
                            attempts=attempts,
                            notes=[f"{level} returned multiple candidates"],
                        )
                    break

            if result is None:
                result = MatchResult(
                    candidate_id=charge.candidate_id,
                    matched=False,
                    attempts=attempts,
                    notes=["no matching bill"],
                )

            if result.matched and result.bill is not None and result.line is not None:
                used.add(_pair_key(result.bill, result.line))
            results.append(result)

        return results

"""Four-layer AR/AP determination.

Layer 1: accounting entity
Layer 2: document roles (issuer / recipient)
Layer 3: money flow (payer / payee / beneficiary)
Layer 4: charge direction (to_us / by_us)

PP/CC is a payment term, not an AR/AP decision.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import Field

from ..extract.models import DocumentClassification, ExtractedCharge
from ..models.base import StrictModel
from ..models.output import AccountingStatus, ChargeDirection, PostingType
from .repository import ExistingBill

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENTITIES = ROOT / "config" / "accounting_entities.yaml"


def _norm_name(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"[^A-Z0-9一-鿿]+", " ", value.upper())
    return re.sub(r"\s+", " ", value).strip()


class EntityResolver:
    def __init__(self, config_path: str | Path | None = None):
        path = Path(config_path) if config_path else DEFAULT_ENTITIES
        if not path.exists():
            path = Path.cwd() / "config" / "accounting_entities.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self.default = data.get("default")
        self.alias_to_canonical: dict[str, str] = {}
        for entity in data.get("entities", []):
            name = entity.get("name")
            if not name:
                continue
            canonical = _norm_name(name)
            for alias in [name, *entity.get("aliases", [])]:
                self.alias_to_canonical[_norm_name(alias)] = canonical

    def canonical(self, value: str | None) -> str:
        normalized = _norm_name(value)
        return self.alias_to_canonical.get(normalized, normalized)

    def matches(self, a: str | None, b: str | None) -> bool:
        if not a or not b:
            return False
        ca, cb = self.canonical(a), self.canonical(b)
        if not ca or not cb:
            return False
        return ca == cb or ca in cb or cb in ca


class ArapResult(StrictModel):
    accounting_entity: str | None = None
    # posting_type is the CONFIRMED direction only.  Weak evidence goes to
    # candidate_posting_type and never to financial_attributes.posting_type.
    posting_type: PostingType | None = None
    candidate_posting_type: PostingType | None = None
    accounting_direction: ChargeDirection | None = None
    candidate_direction: ChargeDirection | None = None
    accounting_status: AccountingStatus | None = None
    collection_right: bool | None = None
    payment_obligation: bool | None = None
    charge_direction: ChargeDirection | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    inherited_from_bill: bool = False
    reasoning: list[str] = []


class ArapEngine:
    def __init__(
        self,
        resolver: EntityResolver | None = None,
        accounting_entity: str | None = None,
    ):
        self.resolver = resolver or EntityResolver()
        self.accounting_entity = accounting_entity or self.resolver.default

    def evaluate(
        self,
        classification: DocumentClassification,
        charge: ExtractedCharge,
        existing_bill: ExistingBill | None = None,
    ) -> ArapResult:
        accounting = self.accounting_entity
        reasoning: list[str] = []

        if classification.document_class != "billing" or classification.billing_status != "confirmed":
            return ArapResult(
                accounting_entity=accounting,
                accounting_status="PENDING_CONFIRMATION",
                confidence=0.0,
                charge_direction="ambiguous",
                reasoning=[
                    f"document_class={classification.document_class}",
                    f"billing_status={classification.billing_status}",
                    "not a confirmed billing document; no AR/AP posting",
                ],
            )

        if not accounting:
            return ArapResult(
                accounting_entity=None,
                accounting_status="PENDING_CONFIRMATION",
                confidence=0.0,
                charge_direction="ambiguous",
                reasoning=["accounting entity is not configured"],
            )

        payer = classification.payer
        payee = classification.payee or classification.beneficiary
        issuer = classification.issuer
        recipient = classification.recipient

        obligation_explicit = bool(payer and self.resolver.matches(accounting, payer))
        right_explicit = bool(payee and self.resolver.matches(accounting, payee))
        obligation_fallback = bool(
            recipient and self.resolver.matches(accounting, recipient)
        )
        right_fallback = bool(issuer and self.resolver.matches(accounting, issuer))

        reasoning.append(f"accounting_entity={accounting}")
        if payer:
            reasoning.append(f"payer={payer}")
        if payee:
            reasoning.append(f"payee={payee}")
        if issuer:
            reasoning.append(f"issuer={issuer}")
        if recipient:
            reasoning.append(f"recipient={recipient}")

        posting: PostingType | None = None
        candidate: PostingType | None = None
        accounting_direction: ChargeDirection | None = None
        candidate_direction: ChargeDirection | None = None
        status: AccountingStatus | None = None
        confidence = 0.0
        inherited = False

        if obligation_explicit and right_explicit:
            status = "PENDING_CONFIRMATION"
            reasoning.append("conflict: accounting entity is both payer and payee")
        elif obligation_explicit:
            posting = candidate = "AP"
            accounting_direction = candidate_direction = "to_us"
            status = "CONFIRMED"
            confidence = 0.9
            reasoning.append("accounting entity is the explicit payer -> AP (confirmed)")
        elif right_explicit:
            posting = candidate = "AR"
            accounting_direction = candidate_direction = "by_us"
            status = "CONFIRMED"
            confidence = 0.9
            reasoning.append("accounting entity is the explicit payee -> AR (confirmed)")
        elif obligation_fallback and right_fallback:
            status = "PENDING_CONFIRMATION"
            reasoning.append("conflict: accounting entity matches both recipient and issuer")
        elif obligation_fallback:
            candidate = "AP"
            candidate_direction = "to_us"
            status = "PENDING_CONFIRMATION"
            confidence = 0.75
            reasoning.append(
                "accounting entity is the recipient/BILL TO -> candidate AP only"
            )
        elif right_fallback:
            candidate = "AR"
            candidate_direction = "by_us"
            status = "PENDING_CONFIRMATION"
            confidence = 0.75
            reasoning.append(
                "accounting entity is the explicit issuer -> candidate AR only"
            )
        elif existing_bill is not None and existing_bill.posting_type:
            # Inherit only when explicit money-flow evidence does not contradict it.
            conflict = (
                existing_bill.posting_type == "AP" and right_explicit
            ) or (
                existing_bill.posting_type == "AR" and obligation_explicit
            )
            if conflict:
                status = "PENDING_CONFIRMATION"
                reasoning.append(
                    "existing posting conflicts with new payer/payee evidence"
                )
            else:
                posting = candidate = existing_bill.posting_type
                accounting_direction = candidate_direction = (
                    "to_us" if posting == "AP" else "by_us"
                )
                status = "CONFIRMED"
                confidence = 0.9
                inherited = True
                reasoning.append(
                    f"inherited posting_type={posting} from {existing_bill.bill_id}"
                )
        else:
            reasoning.append("no payer/payee/obligation evidence; AR/AP undetermined")

        if status is None:
            status = "PENDING_CONFIRMATION"

        if posting == "AP":
            collection_right, payment_obligation, direction = False, True, "to_us"
        elif posting == "AR":
            collection_right, payment_obligation, direction = True, False, "by_us"
        else:
            collection_right, payment_obligation = None, None
            direction = accounting_direction or "ambiguous"

        return ArapResult(
            accounting_entity=accounting,
            posting_type=posting,
            candidate_posting_type=candidate,
            accounting_direction=accounting_direction,
            candidate_direction=candidate_direction,
            accounting_status=status,
            collection_right=collection_right,
            payment_obligation=payment_obligation,
            charge_direction=direction,
            confidence=confidence,
            inherited_from_bill=inherited,
            reasoning=reasoning,
        )

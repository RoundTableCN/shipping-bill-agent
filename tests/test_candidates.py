from decimal import Decimal
from pathlib import Path

from shipping_agent.candidates import build_candidates, collect_candidates
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file
from shipping_agent.io.text_normalize import parse_amount
from shipping_agent.models.bundle import DocumentBundle, SourceRef, TextBlock


def _text_bundle(lines: list[str], media_type: str = "text/plain") -> DocumentBundle:
    blocks = [
        TextBlock(block_id=f"L{i}", kind="line", text=line, order=i)
        for i, line in enumerate(lines)
    ]
    text = "\n".join(lines)
    return DocumentBundle(
        bundle_id="test",
        source=SourceRef(file_id="abc123", file_name="test.txt", media_type=media_type),
        media_type=media_type,
        raw_text=text,
        norm_text=text,
        blocks=blocks,
    )


def test_text_line_h_c_dollar():
    bundle = _text_bundle(["SHA pay TAR：H/C $50"])
    candidates = build_candidates(bundle)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.charge_raw == "H/C"
    assert parse_amount(candidate.amount_raw) == Decimal("50")
    assert candidate.currency_raw == "USD"
    assert "CURRENCY_INFERRED" in candidate.deterministic_flags


def test_text_line_total_is_ignored():
    bundle = _text_bundle(["TOTAL CHARGES TO BE PAID: USD 245.00"])
    assert build_candidates(bundle) == []


def test_text_line_legal_boilerplate_is_ignored():
    bundle = _text_bundle(
        ["The merchant shall be liable for all charges incurred under this clause and applicable law."]
    )
    assert build_candidates(bundle) == []


def test_text_line_explicit_currency():
    bundle = _text_bundle(["HANDLING CHARGE USD 65.00"])
    candidates = build_candidates(bundle)
    assert len(candidates) == 1
    assert candidates[0].currency_raw == "USD"
    assert "CURRENCY_INFERRED" not in candidates[0].deterministic_flags


def test_email_body_source_kind(fixtures_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="mock")
    bundle = parse_file(fixtures_dir / "sample_prealert.eml", ctx)
    candidates = collect_candidates(bundle)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source_kind == "email_body"
    assert parse_amount(candidate.amount_raw) == Decimal("50")
    assert candidate.currency_raw == "USD"
    assert "SHA pay TAR" in candidate.evidence.quote


def test_collect_candidates_skips_reference_attachments(fixtures_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="mock")
    bundle = parse_file(fixtures_dir / "sample_prealert.eml", ctx)

    # Two reference PDFs are parsed (children exist) but must not add candidates.
    assert sum(1 for a in bundle.attachments if a.role == "reference") == 2
    assert len(collect_candidates(bundle)) == 1


def test_line_ids_unique_and_stable(fixtures_dir: Path, tmp_path: Path):
    def candidates():
        ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
        bundle = parse_file(fixtures_dir / "formal_invoice.pdf", ctx)
        return build_candidates(bundle)

    first = candidates()
    second = candidates()

    ids = [c.line_id for c in first]
    assert len(ids) == len(set(ids)) == 3
    assert ids == [c.line_id for c in second]
    assert all(c.line_id == c.source_position_id for c in first)

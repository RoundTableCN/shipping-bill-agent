from shipping_agent.business.duplicate import dedupe_candidates
from shipping_agent.models.bundle import SourceRef
from shipping_agent.models.candidate import RawChargeLine


def _candidate(
    candidate_id: str,
    source_position_id: str,
    amount: str,
    currency: str = "USD",
    charge: str = "Handling Charge",
) -> RawChargeLine:
    return RawChargeLine(
        line_id=f"line-{candidate_id}",
        source_position_id=source_position_id,
        content_fingerprint=f"fp-{candidate_id}",
        candidate_id=candidate_id,
        charge_raw=charge,
        amount_raw=amount,
        currency_raw=currency,
        source_kind="table_row",
        evidence=SourceRef(
            file_id="file-1",
            file_name="bill.pdf",
            media_type="application/pdf",
            quote=f"{charge} {amount}",
        ),
    )


def test_same_source_position_is_merged():
    report = dedupe_candidates(
        [
            _candidate("c1", "pos-1", "65.00"),
            _candidate("c2", "pos-1", "65.00"),
        ]
    )

    assert len(report.kept) == 1
    assert report.kept[0].candidate_id == "c1"
    assert report.merged == ["line-c2"]
    assert any("E_DUPLICATE_LINE" in warning for warning in report.warnings)


def test_same_values_different_rows_are_kept():
    report = dedupe_candidates(
        [
            _candidate("c1", "pos-1", "35.00"),
            _candidate("c2", "pos-2", "35.00"),
        ]
    )

    assert len(report.kept) == 2
    assert report.merged == []
    assert any("W_POSSIBLE_DUPLICATE" in warning for warning in report.warnings)


def test_same_name_different_amount_is_not_duplicate():
    report = dedupe_candidates(
        [
            _candidate("c1", "pos-1", "65.00"),
            _candidate("c2", "pos-2", "35.00"),
        ]
    )

    assert len(report.kept) == 2
    assert not any("W_POSSIBLE_DUPLICATE" in warning for warning in report.warnings)

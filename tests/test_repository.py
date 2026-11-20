from decimal import Decimal
from pathlib import Path

from shipping_agent.business.repository import BillRepository


def test_load_existing_bills(fixtures_dir: Path):
    repo = BillRepository.from_file(fixtures_dir / "existing_bills.json")

    assert len(repo.bills) == 2
    bill = repo.bills[0]
    assert bill.bill_id == "BILL-FIX-001"
    assert bill.reference_no == "INV-FIXTURE-001"
    assert bill.bl_no == "MAEU888777666"
    assert bill.booking_no == "CGTSE260888888"
    assert "FIXU1234567" in bill.container_nos
    assert bill.payer == "IMPORTER BETA (SHANGHAI)"
    assert bill.payee == "CARRIER ALPHA LIMITED"
    assert bill.posting_type == "AP"
    assert len(bill.charges) == 3
    assert bill.charges[0].amount == Decimal("65.00")
    assert bill.charges[0].currency == "USD"


def test_indexes_and_lookup(fixtures_dir: Path):
    repo = BillRepository.from_file(fixtures_dir / "existing_bills.json")

    assert repo.by_reference_no("INV-FIXTURE-001")[0].bill_id == "BILL-FIX-001"
    assert repo.by_bl_no("MAEU888777666")[0].bill_id == "BILL-FIX-001"
    assert repo.by_booking_no("CGTSE260888888")[0].bill_id == "BILL-FIX-001"
    assert repo.by_container("FIXU1234567")[0].bill_id == "BILL-FIX-001"
    assert repo.by_reference_no("missing") == []


def test_duplicate_pair_bill(fixtures_dir: Path):
    repo = BillRepository.from_file(fixtures_dir / "existing_bills.json")
    bill = repo.bills[1]

    assert bill.bill_id == "BILL-FIX-002"
    assert [line.line_id for line in bill.charges] == [
        "BILL-FIX-002-L1",
        "BILL-FIX-002-L2",
    ]
    assert [line.amount for line in bill.charges] == [Decimal("35.00"), Decimal("35.00")]

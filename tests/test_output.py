import json
from decimal import Decimal

from shipping_agent.models.output import OutputRecord
from shipping_agent.output.serializer import (
    REQUIRED_STRICT_KEYS,
    dumps,
    to_full_dict,
    to_strict_dict,
    write_output,
)


def test_full_amount_is_json_number(sample_record: OutputRecord):
    text = dumps([sample_record], "full")
    data = json.loads(text, parse_float=Decimal)

    amount = data[0]["charge_details"]["amount"]
    assert not isinstance(amount, str)
    assert isinstance(amount, Decimal)
    assert amount == Decimal("50.00")


def test_strict_keys_exact(sample_record: OutputRecord):
    data = json.loads(dumps([sample_record], "strict"))
    record = data[0]

    assert set(record.keys()) == set(REQUIRED_STRICT_KEYS)
    assert set(record["document_info"].keys()) == {
        "document_type",
        "reference_no",
        "document_date",
    }
    assert set(record["transaction_party"].keys()) == {"issuer", "recipient"}
    assert set(record["charge_details"].keys()) == {
        "charge_item",
        "amount",
        "currency",
        "payment_term",
    }
    assert set(record["financial_attributes"].keys()) == {
        "accounting_entity",
        "posting_type",
    }
    assert set(record["audit_trail"].keys()) == {"ai_reasoning"}
    assert isinstance(record["audit_trail"]["ai_reasoning"], list)


def test_strict_dict_has_no_audit_extensions(sample_record: OutputRecord):
    strict = to_strict_dict(sample_record)
    assert "document_class" not in strict["audit_trail"]
    assert "source_position_id" not in strict["audit_trail"]


def test_full_dict_has_audit_extensions(sample_record: OutputRecord):
    full = to_full_dict(sample_record)
    audit = full["audit_trail"]

    assert audit["document_class"] == "notice"
    assert audit["billing_status"] == "tentative"
    assert audit["source_position_id"] == "eml-body-line-12"
    assert audit["candidate_amount"] == Decimal("50.00")
    assert audit["document_totals"] == {
        "subtotal": None,
        "tax": None,
        "total": None,
    }
    assert audit["strict_attempts"][0]["rule"] == "STRICT_L1"


def test_amount_quantized_by_currency(sample_record: OutputRecord):
    record = sample_record.model_copy(deep=True)
    record.charge_details.amount = Decimal("1.005")
    full = to_full_dict(record)
    assert full["charge_details"]["amount"] == Decimal("1.01")

    record.charge_details.currency = "JPY"
    record.charge_details.amount = Decimal("1.5")
    full = to_full_dict(record)
    assert full["charge_details"]["amount"] == Decimal("2")


def test_empty_list_is_valid_json():
    assert dumps([], "strict") == "[]"
    assert dumps([], "full") == "[]"


def test_write_output_strict_creates_audit_file(tmp_path, sample_record: OutputRecord):
    out = tmp_path / "out.json"
    audit = tmp_path / "audit.json"

    written = write_output([sample_record], out, mode="strict", audit_path=audit)

    assert written["output"] == out
    assert written["audit"] == audit
    assert out.exists() and audit.exists()

    strict_data = json.loads(out.read_text(encoding="utf-8"))
    assert set(strict_data[0]["audit_trail"].keys()) == {"ai_reasoning"}

    audit_data = json.loads(audit.read_text(encoding="utf-8"))
    assert audit_data[0]["document_class"] == "notice"


def test_write_output_full_does_not_create_audit(tmp_path, sample_record: OutputRecord):
    out = tmp_path / "out.json"
    written = write_output([sample_record], out, mode="full")
    assert written == {"output": out}
    assert not (tmp_path / "audit.json").exists()


def test_unknown_mode_rejected(sample_record: OutputRecord):
    try:
        dumps([sample_record], mode="invalid")  # type: ignore[arg-type]
    except ValueError as exc:
        assert "unknown output mode" in str(exc)
    else:
        raise AssertionError("expected ValueError")

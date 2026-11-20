import json

import pytest
from jsonschema.exceptions import ValidationError

from shipping_agent.models.output import OutputRecord
from shipping_agent.output.serializer import dumps
from shipping_agent.validate.schema import (
    full_schema,
    strict_schema,
    validate_full,
    validate_strict,
)


def test_schemas_are_generated():
    full = full_schema()
    strict = strict_schema()

    assert full["type"] == "array"
    assert strict["type"] == "array"
    assert full["$defs"]
    assert strict["$defs"]


def test_strict_output_validates(sample_record: OutputRecord):
    data = json.loads(dumps([sample_record], "strict"))
    validate_strict(data)


def test_full_output_validates(sample_record: OutputRecord):
    data = json.loads(dumps([sample_record], "full"))
    validate_full(data)


def test_strict_rejects_extra_audit_key(sample_record: OutputRecord):
    data = json.loads(dumps([sample_record], "strict"))
    data[0]["audit_trail"]["document_class"] = "notice"

    with pytest.raises(ValidationError):
        validate_strict(data)


def test_strict_rejects_extra_charge_key(sample_record: OutputRecord):
    data = json.loads(dumps([sample_record], "strict"))
    data[0]["charge_details"]["quantity"] = 1

    with pytest.raises(ValidationError):
        validate_strict(data)


def test_strict_rejects_missing_operation(sample_record: OutputRecord):
    data = json.loads(dumps([sample_record], "strict"))
    del data[0]["operation"]

    with pytest.raises(ValidationError):
        validate_strict(data)


def test_strict_schema_amount_is_number():
    schema = strict_schema()
    amount_schema = schema["$defs"]["ChargeDetails"]["properties"]["amount"]
    rendered = json.dumps(amount_schema)
    assert '"number"' in rendered
    assert '"string"' not in rendered

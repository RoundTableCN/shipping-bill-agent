from decimal import Decimal

import pytest
from pydantic import ValidationError

from shipping_agent.io.text_normalize import parse_currency
from shipping_agent.models.output import ChargeDetails
from shipping_agent.models.types import quantize_money, to_decimal


def test_to_decimal_from_string_with_commas():
    assert to_decimal("1,410.40") == Decimal("1410.40")


def test_to_decimal_from_float_uses_str():
    # Decimal(0.1) would be 0.1000000000000000055511151231257827...
    assert to_decimal(0.1) == Decimal("0.1")


def test_to_decimal_rejects_bool_and_empty():
    with pytest.raises(ValueError):
        to_decimal(True)
    with pytest.raises(ValueError):
        to_decimal("")


def test_to_decimal_tolerates_llm_string_shapes():
    assert to_decimal("USD 65.00") == Decimal("65.00")
    assert to_decimal("(65.00)") == Decimal("-65.00")
    assert to_decimal("65.00-") == Decimal("-65.00")


def test_quantize_usd_half_up():
    assert quantize_money(Decimal("1.005"), "USD") == Decimal("1.01")


def test_quantize_jpy_zero_decimals():
    assert quantize_money(Decimal("1.5"), "JPY") == Decimal("2")


def test_quantize_kwd_three_decimals():
    assert quantize_money(Decimal("1.2345"), "KWD") == Decimal("1.235")


def test_quantize_none():
    assert quantize_money(None, "USD") is None


def test_charge_details_accepts_string_amount():
    charge = ChargeDetails(charge_item="Handling Charge", amount="40.00", currency="USD")
    assert charge.amount == Decimal("40.00")


def test_charge_details_rejects_invalid_currency():
    with pytest.raises(ValidationError):
        ChargeDetails(charge_item="Handling Charge", amount="40.00", currency="US")


def test_charge_details_allows_null_amount_and_currency():
    charge = ChargeDetails(charge_item="Handling Charge")
    assert charge.amount is None
    assert charge.currency is None


def test_parse_currency_iso_whitelist():
    assert parse_currency("USD") == ("USD", False)
    assert parse_currency("$") == ("USD", True)
    assert parse_currency("US$") == ("USD", True)
    # Three letters are not automatically a currency (e.g. "FEE").
    assert parse_currency("FEE") == (None, False)

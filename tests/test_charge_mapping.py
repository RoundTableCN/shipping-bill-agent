import pytest

from shipping_agent.business.charge_mapper import ChargeMapper, default_mapper


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("H/C", "Handling Charge"),
        ("H/D Fee", "Handling Charge"),
        ("Handling Fee", "Handling Charge"),
        ("Doc Fee", "Documentation Fee"),
        ("THC", "Terminal Handling Charge"),
        ("Trucking Fee", "Trucking Charge"),
        ("Customs Fee", "Customs Clearance Fee"),
        ("Storage Fee", "Storage Charge"),
        ("DMR", "Detention Charge"),
        ("4 ADD'L DETENTION FREE TIME CHARGE", "Detention Free Time Extension Charge"),
        ("Ocean Freight", "Ocean Freight"),
        ("Wharfage Administration Fee", "Wharfage Administration Fee"),
    ],
)
def test_known_aliases(raw, expected):
    standard, mapped = default_mapper().standardize(raw)
    assert mapped is True
    assert standard == expected


def test_substring_alias_in_noisy_name():
    standard, mapped = default_mapper().standardize(
        "Waybill OCA17 On Carriage Additional - US Em"
    )
    assert mapped is True
    assert standard == "On Carriage Additional"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HANDLING CHARGE", "MATCHED"),
        ("H/C", "CANDIDATE"),
        ("4 ADD'L DETENTION FREE TIME CHARGE", "PENDING_CONFIRMATION"),
        ("Waybill OCA17 On Carriage Additional - US Em", "CANDIDATE"),
        ("SOME NEW SURCHARGE", "UNMATCHED"),
    ],
)
def test_mapping_status(raw, expected):
    _, status = default_mapper().standardize_with_status(raw)
    assert status == expected


def test_mapping_status_none():
    _, status = default_mapper().standardize_with_status(None)
    assert status == "UNMATCHED"


def test_unknown_charge_is_preserved():
    standard, mapped = default_mapper().standardize("SOME NEW SURCHARGE")
    assert mapped is False
    assert standard == "SOME NEW SURCHARGE"


def test_none_returns_none():
    assert default_mapper().standardize(None) == (None, False)


def test_mapper_can_load_custom_file(tmp_path):
    path = tmp_path / "mapping.yaml"
    path.write_text(
        "version: '1'\nmappings:\n  - standard: Test Charge\n    aliases: [TC]\n",
        encoding="utf-8",
    )
    mapper = ChargeMapper(path)
    assert mapper.standardize("TC") == ("Test Charge", True)

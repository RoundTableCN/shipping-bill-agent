from pathlib import Path

import pytest

from shipping_agent.examples import sample_prealert_record
from shipping_agent.models.output import OutputRecord

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sample_record() -> OutputRecord:
    return sample_prealert_record()


@pytest.fixture
def fixtures_dir() -> Path:
    return ROOT / "data" / "fixtures"


@pytest.fixture
def samples_dir() -> Path:
    path = ROOT / "data" / "samples"
    if not path.exists():
        pytest.skip("sample data omitted from this checkout")
    return path


_PREALERT_DEPENDENT = {
    "test_arap.py",
    "test_business_rules.py",
    "test_candidates.py",
    "test_checklist_fixes.py",
    "test_cli.py",
    "test_decision.py",
    "test_detect.py",
    "test_document_class.py",
    "test_eml.py",
    "test_eval.py",
    "test_evidence.py",
    "test_golden.py",
    "test_llm_grounding.py",
    "test_rule_extractor.py",
    "test_totals.py",
    "test_ui_service.py",
}

_SAMPLE_DEPENDENT = {
    "test_arap.py",
    "test_business_rules.py",
    "test_checklist_fixes.py",
    "test_decision.py",
    "test_document_class.py",
    "test_eval.py",
    "test_extract_cli.py",
    "test_golden.py",
    "test_llm_grounding.py",
    "test_manual_ocr_fixture.py",
    "test_ocr.py",
    "test_ocr_wiring.py",
    "test_pdf.py",
    "test_real_ocr_fixture.py",
    "test_rule_extractor.py",
    "test_totals.py",
    "test_vision_fallback.py",
}


def pytest_collection_modifyitems(config, items):
    """Skip real-sample tests when a privacy-cleaned checkout omits them."""
    have_prealert = (ROOT / "data" / "fixtures" / "sample_prealert.eml").exists()
    have_samples = (ROOT / "data" / "samples").exists()
    for item in items:
        filename = Path(str(item.fspath)).name
        if not have_prealert and filename in _PREALERT_DEPENDENT:
            item.add_marker(pytest.mark.skip(reason="sample_prealert.eml omitted"))
        elif not have_samples and filename in _SAMPLE_DEPENDENT:
            item.add_marker(pytest.mark.skip(reason="data/samples omitted"))

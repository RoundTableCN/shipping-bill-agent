from pathlib import Path

from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file


def test_parse_prealert(fixtures_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="mock")
    bundle = parse_file(fixtures_dir / "sample_prealert.eml", ctx)

    assert bundle.media_type == "message/rfc822"
    assert "PRE-ALERT" in bundle.meta["subject"]
    assert "SHA pay TAR" in bundle.raw_text
    assert "H/C $50" in bundle.raw_text

    names = [a.file_name for a in bundle.attachments]
    assert any("MBL" in name for name in names)
    assert any("HBL" in name for name in names)
    assert any("InsertPic" in name for name in names)


def test_attachment_roles_and_children(fixtures_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="mock")
    bundle = parse_file(fixtures_dir / "sample_prealert.eml", ctx)

    by_role = {a.role: a for a in bundle.attachments}
    assert by_role["media"].file_name.lower().endswith(".jpg")
    assert by_role["reference"].media_type == "application/pdf"
    assert by_role["reference"].child is not None
    assert by_role["reference"].child.raw_text
    assert by_role["reference"].child.tables == []


def test_attachments_saved_to_run_dir(fixtures_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="mock")
    parse_file(fixtures_dir / "sample_prealert.eml", ctx)

    saved = list((tmp_path / "run" / "attachments").iterdir())
    assert len(saved) == 3
    assert all(path.stat().st_size > 0 for path in saved)

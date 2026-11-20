from pathlib import Path

from PIL import Image

from shipping_agent.io.detect import MediaType, detect_media_type, detect_media_type_bytes


def test_pdf_magic(fixtures_dir: Path):
    data = (fixtures_dir / "formal_invoice.pdf").read_bytes()
    assert detect_media_type_bytes(data, "x.bin") is MediaType.PDF
    assert detect_media_type(fixtures_dir / "formal_invoice.pdf") is MediaType.PDF


def test_xlsx_magic(fixtures_dir: Path):
    data = (fixtures_dir / "charges.xlsx").read_bytes()
    assert detect_media_type_bytes(data, "x.bin") is MediaType.XLSX


def test_docx_magic(fixtures_dir: Path):
    data = (fixtures_dir / "statement.docx").read_bytes()
    assert detect_media_type_bytes(data, "x.bin") is MediaType.DOCX


def test_eml_headers(fixtures_dir: Path):
    data = (fixtures_dir / "sample_prealert.eml").read_bytes()
    assert detect_media_type_bytes(data, "x.bin") is MediaType.EML
    assert detect_media_type(fixtures_dir / "sample_prealert.eml") is MediaType.EML


def test_png_magic(samples_dir: Path):
    data = (samples_dir / "sample_carrier_invoice.png").read_bytes()
    assert detect_media_type_bytes(data, "x.bin") is MediaType.PNG


def test_tiff_and_jpeg_magic(tmp_path: Path):
    image = Image.new("RGB", (10, 10), "white")
    for suffix, expected in (("tiff", MediaType.TIFF), ("jpg", MediaType.JPEG)):
        path = tmp_path / f"sample.{suffix}"
        image.save(path)
        assert detect_media_type_bytes(path.read_bytes(), "x.bin") is expected


def test_unknown_bytes():
    assert detect_media_type_bytes(b"\x00\x01\x02\x03", "x.bin") is MediaType.UNKNOWN


def test_extension_fallback_for_plain_text():
    assert detect_media_type_bytes(b"hello, world", "notes.txt") is MediaType.TEXT
    assert detect_media_type_bytes(b"a,b\n1,2", "data.csv") is MediaType.CSV

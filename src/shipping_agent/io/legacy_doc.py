"""Legacy Word 97-2003 ``.doc`` text extraction.

LibreOffice is the preferred converter when it is installed.  This module is
the fallback for machines that have neither LibreOffice nor Microsoft Word:
it reads the WordDocument/0Table/1Table OLE streams and walks the Word piece
table directly.

The parser intentionally focuses on text extraction.  Table cell markers
(``\\x07``) are preserved as ``|`` so the normal text/table candidate builders
can still find charge lines.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

WORD_IDENT = 0xA5EC
FIB_WHICH_TABLE = 0x0200
FIB_FC_CLX = 0x01A2
FIB_LCB_CLX = 0x01A6


class LegacyDocError(ValueError):
    pass


def _read_stream(ole, name: str) -> bytes:
    if not ole.exists(name):
        raise LegacyDocError(f"missing OLE stream: {name}")
    return ole.openstream(name).read()


def _decode_piece(stream: bytes, offset: int, length: int, compressed: bool) -> str:
    if compressed:
        raw = stream[offset:offset + length]
        if len(raw) < length:
            raise LegacyDocError("compressed text piece is truncated")
        # Word's compressed pieces use the document ANSI code page.  CP1252 is
        # the standard Word 97 choice; GBK/other pages still decode losslessly
        # enough for field matching when the document uses Unicode pieces.
        return raw.decode("cp1252", errors="replace")
    raw = stream[offset:offset + length * 2]
    if len(raw) < length * 2:
        raise LegacyDocError("Unicode text piece is truncated")
    return raw.decode("utf-16le", errors="replace")


def _piece_table_text(word: bytes, table: bytes) -> str:
    if len(word) < 0x01AA:
        raise LegacyDocError("WordDocument stream is too short for a Word 97 FIB")
    w_ident = struct.unpack_from("<H", word, 0)[0]
    if w_ident != WORD_IDENT:
        raise LegacyDocError(f"unsupported Word identifier: 0x{w_ident:04x}")

    fc_clx = struct.unpack_from("<I", word, FIB_FC_CLX)[0]
    lcb_clx = struct.unpack_from("<I", word, FIB_LCB_CLX)[0]
    if lcb_clx == 0:
        return ""
    if fc_clx + lcb_clx > len(table):
        raise LegacyDocError("CLX range is outside the table stream")

    clx = table[fc_clx:fc_clx + lcb_clx]
    position = 0
    plc = None
    while position < len(clx):
        kind = clx[position]
        if kind == 0x01:  # Prc: grpprl
            if position + 3 > len(clx):
                raise LegacyDocError("truncated Prc")
            cb = struct.unpack_from("<H", clx, position + 1)[0]
            position += 3 + cb
            continue
        if kind == 0x02:  # Pcdt
            if position + 5 > len(clx):
                raise LegacyDocError("truncated Pcdt")
            lcb = struct.unpack_from("<I", clx, position + 1)[0]
            plc = clx[position + 5:position + 5 + lcb]
            break
        raise LegacyDocError(f"unknown CLX record type: 0x{kind:02x}")

    if plc is None or len(plc) < 4:
        return ""
    piece_count = (len(plc) - 4) // 12
    if piece_count <= 0:
        raise LegacyDocError("empty piece table")

    cps = [
        struct.unpack_from("<I", plc, 4 * index)[0]
        for index in range(piece_count + 1)
    ]
    parts: list[str] = []
    for index in range(piece_count):
        cp_start, cp_end = cps[index], cps[index + 1]
        if cp_end <= cp_start:
            continue
        pcd_offset = 4 * (piece_count + 1) + 8 * index
        if pcd_offset + 8 > len(plc):
            raise LegacyDocError("truncated PCD entry")
        fc = struct.unpack_from("<I", plc, pcd_offset + 2)[0]
        compressed = bool(fc & 0x40000000)
        real_fc = (fc & 0x3FFFFFFF) // 2 if compressed else fc
        parts.append(
            _decode_piece(
                word,
                real_fc,
                cp_end - cp_start,
                compressed,
            )
        )
    return "".join(parts)


def _clean_text(text: str) -> str:
    text = (
        text.replace("\r", "\n")
        .replace("\x0b", "\n")
        .replace("\x0c", "\n")
        .replace("\x07", " | ")
        .replace("\x00", "")
    )
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def extract_legacy_doc_text(path: str | Path) -> str:
    """Extract readable text from a Word 97-2003 binary .doc file."""
    path = Path(path)
    try:
        import olefile
    except ImportError as exc:  # pragma: no cover - requirements.txt includes it
        raise LegacyDocError("install olefile to read legacy .doc files") from exc

    try:
        with olefile.OleFileIO(str(path)) as ole:
            word = _read_stream(ole, "WordDocument")
            flags = struct.unpack_from("<H", word, 0x0A)[0] if len(word) >= 0x0C else 0
            table_name = "1Table" if flags & FIB_WHICH_TABLE else "0Table"
            table = _read_stream(ole, table_name)
            text = _piece_table_text(word, table)
    except LegacyDocError:
        raise
    except Exception as exc:  # noqa: BLE001 - olefile raises several types
        raise LegacyDocError(f"cannot read legacy .doc: {exc}") from exc

    return _clean_text(text)

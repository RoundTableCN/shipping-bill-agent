"""Charge-name standardization from a versioned YAML mapping."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

from ..models.output import MappingStatus

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MAPPING = ROOT / "config" / "charge_mapping.yaml"


def normalize_charge(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").upper()
    text = re.sub(r"[^A-Z0-9一-鿿]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class ChargeMapper:
    def __init__(self, mapping_path: str | Path | None = None):
        path = Path(mapping_path) if mapping_path else DEFAULT_MAPPING
        if not path.exists():
            path = Path.cwd() / "config" / "charge_mapping.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self.version = data.get("version")
        self.exact: dict[str, tuple[str, MappingStatus]] = {}
        self.aliases: list[tuple[str, str, MappingStatus]] = []
        for entry in data.get("mappings", []):
            standard = entry.get("standard")
            if not standard:
                continue
            entry_status: MappingStatus = entry.get("status", "MATCHED")
            alias_status = {
                normalize_charge(key): value
                for key, value in (entry.get("alias_status") or {}).items()
            }
            for alias in [*entry.get("aliases", []), standard]:
                normalized = normalize_charge(alias)
                if not normalized:
                    continue
                status = alias_status.get(normalized, entry_status)
                self.exact.setdefault(normalized, (standard, status))
                self.aliases.append((normalized, standard, status))
        # Longest alias first so "WHARFAGE ADMINISTRATION FEE" wins over "WHARFAGE".
        self.aliases.sort(key=lambda item: len(item[0]), reverse=True)

    def standardize_with_status(
        self, raw: str | None
    ) -> tuple[str | None, MappingStatus]:
        """Return (standard_name, mapping_status)."""
        if not raw:
            return None, "UNMATCHED"
        normalized = normalize_charge(raw)
        if not normalized:
            return raw.strip(), "UNMATCHED"
        if normalized in self.exact:
            return self.exact[normalized]

        padded = f" {normalized} "
        for alias, standard, status in self.aliases:
            if not alias:
                continue
            if f" {alias} " in padded:
                return standard, status
        return raw.strip(), "UNMATCHED"

    def standardize(self, raw: str | None) -> tuple[str | None, bool]:
        """Backward-compatible wrapper: (standard_name, mapped)."""
        standard, status = self.standardize_with_status(raw)
        return standard, status != "UNMATCHED"


@lru_cache(maxsize=1)
def default_mapper() -> ChargeMapper:
    return ChargeMapper()

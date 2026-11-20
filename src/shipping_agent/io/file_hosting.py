"""Public file hosting adapter.

The OCR API needs a URL the OCR server can reach. P0-B only provides a mock
adapter and a static base-URL adapter; real upload (OSS/S3/tunnel) is P1+.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Protocol


class FileHosting(Protocol):
    def url_for(self, path: Path) -> str | None:
        ...


class MockHosting:
    def url_for(self, path: Path) -> str | None:
        return None


class StaticBaseHosting:
    """Assume the file has been uploaded under ``<base>/<sha><suffix>``."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def url_for(self, path: Path) -> str | None:
        if not self.base_url:
            return None
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        return f"{self.base_url}/{digest}{Path(path).suffix}"


class LocalHttpHosting:
    """Copy files into a directory served by an external HTTP server/tunnel.

    Example:
        python -m http.server 8765 --directory out/ocr_serve
        cloudflared tunnel --url http://localhost:8765
        set OCR_FILE_BASE_URL=https://<tunnel-host>
    """

    def __init__(self, base_url: str, serve_dir: str | Path):
        self.base_url = base_url.rstrip("/")
        self.serve_dir = Path(serve_dir)
        self.serve_dir.mkdir(parents=True, exist_ok=True)

    def url_for(self, path: Path) -> str | None:
        if not self.base_url:
            return None
        path = Path(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        target = self.serve_dir / f"{digest}{path.suffix.lower()}"
        if not target.exists():
            shutil.copy2(path, target)
        return f"{self.base_url}/{target.name}"

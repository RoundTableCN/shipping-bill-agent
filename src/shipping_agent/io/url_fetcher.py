"""Download a public HTTP(S) document for the normal parser pipeline.

This is an input adapter, not a parser: the downloaded bytes still go through
``detect_media_type_bytes`` and the same EML/PDF/image/Excel/Word parsers.
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from .context import ParseError
from .text_normalize import safe_filename

DEFAULT_TIMEOUT = (10, 120)
DEFAULT_MAX_BYTES = 200 * 1024 * 1024
_CONTENT_TYPE_EXTENSIONS = {
    "application/pdf": ".pdf",
    "message/rfc822": ".eml",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/tiff": ".tiff",
    "text/html": ".html",
    "text/plain": ".txt",
    "text/csv": ".csv",
}


def is_url(value: str | None) -> bool:
    return bool(value and re.match(r"^https?://", value.strip(), re.IGNORECASE))


def split_urls(value: str | None) -> list[str]:
    """Split a textarea/CLI value into one URL per line, preserving order."""
    if not value:
        return []
    urls: list[str] = []
    for line in str(value).splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        if not is_url(item):
            raise ParseError(
                "URL_INVALID",
                f"only http(s) URLs are supported: {item[:120]}",
            )
        if item not in urls:
            urls.append(item)
    return urls


def _name_from_response(response: requests.Response, url: str) -> str:
    disposition = response.headers.get("content-disposition", "")
    match = re.search(
        r"filename\*?=(?:UTF-8''|\")?([^\";]+)",
        disposition,
        re.IGNORECASE,
    )
    if match:
        raw = unquote(match.group(1).strip().strip('"'))
        name = Path(raw).name
    else:
        name = Path(unquote(urlparse(url).path)).name
    if not name:
        name = "download"
    if "." not in name:
        content_type = (
            response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        )
        extension = _CONTENT_TYPE_EXTENSIONS.get(content_type)
        if extension is None:
            extension = mimetypes.guess_extension(content_type) or ""
        name += extension
    return safe_filename(name, fallback="download")


def download_url(
    url: str,
    dest_dir: str | Path,
    *,
    timeout: tuple[int, int] = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> Path:
    """Download *url* to *dest_dir* and return the local path.

    Only http/https is accepted. The returned filename is safe for Windows and
    is derived from Content-Disposition, the URL path, or Content-Type.
    """
    url = (url or "").strip()
    if not is_url(url):
        raise ParseError(
            "URL_INVALID",
            "only public http:// or https:// URLs are supported",
        )

    destination = Path(dest_dir)
    destination.mkdir(parents=True, exist_ok=True)
    host_path = urlparse(url)
    display = f"{host_path.netloc}{host_path.path}" or url

    response: requests.Response | None = None
    try:
        response = requests.get(
            url,
            stream=True,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": "shipping-bill-agent/1.0"},
        )
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > max_bytes:
                    raise ParseError(
                        "URL_TOO_LARGE",
                        f"{display} is larger than {max_bytes} bytes",
                    )
            except ValueError:
                pass

        filename = _name_from_response(response, url)
        target = destination / filename
        received = 0
        with target.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                received += len(chunk)
                if received > max_bytes:
                    handle.close()
                    target.unlink(missing_ok=True)
                    raise ParseError(
                        "URL_TOO_LARGE",
                        f"{display} exceeds {max_bytes} bytes",
                    )
                handle.write(chunk)
    except ParseError:
        raise
    except requests.Timeout as exc:
        raise ParseError("URL_TIMEOUT", f"timed out downloading {display}") from exc
    except requests.RequestException as exc:
        raise ParseError(
            "URL_DOWNLOAD_FAILED", f"could not download {display}: {exc}"
        ) from exc
    finally:
        if response is not None:
            response.close()

    if target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise ParseError("URL_EMPTY", f"{display} returned an empty body")
    return target


def resolve_input(value: str | Path, run_dir: str | Path) -> Path:
    """Resolve a local path or a public URL into a local file path."""
    if is_url(str(value)):
        return download_url(str(value), Path(run_dir) / "downloads")
    return Path(value)

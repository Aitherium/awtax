"""Reading pages that have no text layer (scans, photos of a mailed form).

awtax does NOT bundle an OCR engine. The aw* stack already has a vision brick --
`awvision` -- and a vision model extracts form fields *structurally* (it can answer
"what is in box 1?"), which is strictly better than raw OCR text you then have to
re-parse. So the primary path is awvision; a local OCR engine (tesseract) is only an
offline fallback for a stranger who has neither a vision endpoint nor a network.

Both paths are optional. If neither is available, the caller gets a clear
`needs_review` signal rather than a silent zero -- the exact failure mode
(TaxDesk's parse_w2_pdf returning all-zeros on a scan) that awtax exists to fix.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any


class VisionUnavailableError(RuntimeError):
    pass


def _render_page_png(pdf_path: str, page_index: int, dpi: int = 300) -> str:
    """Render one page to a temp PNG, return its path. Requires PyMuPDF."""
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    pix = doc[page_index].get_pixmap(dpi=dpi)
    out = os.path.join(tempfile.gettempdir(), f"awtax_p{page_index}.png")
    pix.save(out)
    return out


def _coerce_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply, tolerating prose around it."""
    if isinstance(text, dict):
        return text
    m = re.search(r"\{.*\}", str(text), re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


def vision_available() -> bool:
    try:
        import awvision  # noqa: F401
        return True
    except Exception:
        return False


def local_ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def extract_fields_via_vision(
    pdf_path: str,
    page_index: int,
    question: str,
    *,
    endpoint: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Ask the awvision plane to read a scanned page; return a JSON object of fields.

    Raises VisionUnavailableError if awvision is not installed / no endpoint resolves,
    so the caller can fall back rather than treat an outage as an empty form.
    """
    try:
        from awvision import ask_vision  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise VisionUnavailableError(f"awvision not available: {exc}") from exc

    png = _render_page_png(pdf_path, page_index)
    prompt = (
        f"{question}\n\n"
        "Return ONLY a compact JSON object mapping each field name to its value. "
        "Use numbers for money (no $ or commas). If a field is absent, omit it."
    )
    answer = ask_vision(png, prompt, endpoint=endpoint, model=model)
    return _coerce_json(answer)


def extract_text_via_local_ocr(pdf_path: str, page_index: int) -> str:
    """Offline fallback: render the page and run tesseract, returning raw text.

    Returns '' if tesseract is not installed -- never raises, because the caller
    treats empty text as needs_review, not as a valid empty form.
    """
    if not local_ocr_available():
        return ""
    png = _render_page_png(pdf_path, page_index)
    try:
        out = subprocess.run(
            ["tesseract", png, "stdout", "--psm", "6"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return out.stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return ""

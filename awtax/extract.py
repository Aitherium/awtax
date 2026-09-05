"""The extraction core: any tax PDF -> a provider-neutral, self-checked schema.

Native-text pages are parsed directly (PyMuPDF). Scanned pages route to awvision
(ocr.py). Every recognized document runs arithmetic cross-checks -- a tax number
that does not satisfy the identity it is defined by (taxable = AGI - deduction,
refund = payments - tax) is flagged, not trusted. That self-validation is what let
this code read a real 2024 return this session and *prove* the figures pair
correctly instead of asserting a fragile label->value guess.
"""
from __future__ import annotations

import re

from .ocr import (
    extract_fields_via_vision,
    extract_text_via_local_ocr,
    vision_available,
)
from .schema import Document, Extraction, Figure

_MONEY = re.compile(r"^-?\d[\d,]*\.?$")
_SCAN_TEXT_THRESHOLD = 40  # a page with fewer chars than this is treated as a scan


def _num(tok: str) -> float | None:
    try:
        return float(tok.replace(",", "").rstrip("."))
    except ValueError:
        return None


def _page_text(page) -> str:
    return page.get_text().replace("\xa0", " ").replace(" ", " ")




# --- Form 1040 -------------------------------------------------------------

_1040_LINES = {
    "total_income": r"total income",
    "adjusted_gross_income": r"adjusted gross income",
    "standard_deduction": r"standard deduction or itemized",
    "taxable_income": r"taxable income",
    "tax": r"Tax \(see instructions\)",
    "total_tax": r"total tax",
    "withholding": r"federal income tax withheld",
    "total_payments": r"total payments",
    "refund": r"amount you overpaid|refunded to you",
    "amount_owed": r"amount you owe",
}


def _extract_1040(doc_pages, pdf, form: str = "1040") -> Document:
    d = Document(form=form, pages=[p + 1 for p in doc_pages])
    for pi in doc_pages:
        page = pdf[pi]
        words = page.get_text("words")  # (x0, y0, x1, y1, text, block, line, wordno)
        # On a real IRS 1040 the line DESCRIPTION and its filled AMOUNT are not in one
        # token row -- the description sits in a y-BAND, and the amount is in the right
        # column. So for each amount, reconstruct its label from every word within a
        # small y-band and to the LEFT of the amount (its own line, whatever the
        # baseline jitter), then match. Amount->label direction + the arithmetic
        # cross-check below guard against a wrong pairing producing a wrong number.
        amounts = [
            (w[0], (w[1] + w[3]) / 2, w[4])
            for w in words
            if _MONEY.match(w[4]) and w[0] > 380 and ("." in w[4] or "," in w[4]) and len(w[4]) > 2
        ]
        for ax, ay, atok in amounts:
            band = [
                w[4]
                for w in words
                if abs((w[1] + w[3]) / 2 - ay) <= 8 and w[2] <= ax and not _MONEY.match(w[4])
            ]
            label = " ".join(band)
            for key, pat in _1040_LINES.items():
                if key in d.figures:
                    continue
                if re.search(pat, label, re.I):
                    d.figures[key] = Figure(_num(atok), key, page=pi + 1, source="text")
                    break
    if not d.figures:
        d.warnings.append(
            f"{form}: recognized the form but extracted no figures "
            "(label/value pairing did not resolve) -- needs review"
        )
    _crosscheck_1040(d)
    return d


def _crosscheck_1040(d: Document) -> None:
    def g(k):
        f = d.figures.get(k)
        return f.value if f and isinstance(f.value, (int, float)) else None

    agi, sd, ti = g("adjusted_gross_income"), g("standard_deduction"), g("taxable_income")
    if None not in (agi, sd, ti):
        (d.checks if abs(agi - sd - ti) < 1 else d.warnings).append(
            f"taxable_income = AGI - deduction ({agi:.0f} - {sd:.0f} = {ti:.0f})"
        )
    pay, tax, ref = g("total_payments"), g("total_tax"), g("refund")
    if None not in (pay, tax, ref):
        (d.checks if abs(pay - tax - ref) < 1 else d.warnings).append(
            f"refund = payments - total_tax ({pay:.0f} - {tax:.0f} = {ref:.0f})"
        )


# --- W-2 -------------------------------------------------------------------

_W2_BOXES = {
    "wages_box1": "box 1 wages, tips, other compensation",
    "fed_withheld_box2": "box 2 federal income tax withheld",
    "ss_wages_box3": "box 3 social security wages",
    "ss_tax_box4": "box 4 social security tax withheld",
    "medicare_wages_box5": "box 5 medicare wages and tips",
    "medicare_tax_box6": "box 6 medicare tax withheld",
    "state_wages_box16": "box 16 state wages",
    "state_tax_box17": "box 17 state income tax",
}


def _extract_w2(doc_pages, pdf, *, endpoint=None, model=None) -> Document:
    d = Document(form="W-2", pages=[p + 1 for p in doc_pages])
    pi = doc_pages[0]
    text = _page_text(pdf[pi])
    if len(text.strip()) >= _SCAN_TEXT_THRESHOLD:
        d.warnings.append("native-text W-2 parsing not yet implemented; use vision")
        return d
    # scanned -> vision first, then offline OCR, else needs_review (never silent zeros)
    q = "This is a US W-2 wage and tax statement. Extract: " + "; ".join(
        f"{k} ({desc})" for k, desc in _W2_BOXES.items()
    )
    fields: dict = {}
    src = "vision"
    if vision_available():
        try:
            fields = extract_fields_via_vision(pdf.name, pi, q, endpoint=endpoint, model=model)
        except Exception as exc:
            # any vision failure (unavailable, timeout, bad reply) degrades to OCR /
            # needs_review -- a scanned form must never crash the whole extraction
            d.warnings.append(f"vision path failed ({type(exc).__name__}); fell back")
            fields = {}
    if not fields:
        raw = extract_text_via_local_ocr(pdf.name, pi)
        if raw:
            fields = _w2_from_ocr_text(raw)
            src = "ocr"
    if not fields:
        d.warnings.append("scanned W-2 and no vision/OCR backend available -- needs review")
        return d
    for k in _W2_BOXES:
        if k in fields and fields[k] not in (None, ""):
            d.figures[k] = Figure(_num_any(fields[k]), k, page=pi + 1, source=src, confidence=0.8)
    return d


def _num_any(v):
    if isinstance(v, (int, float)):
        return float(v)
    return _num(str(v))


def _w2_from_ocr_text(text: str) -> dict:
    """Best-effort parse of raw OCR text into the box values (offline fallback)."""
    out: dict[str, float] = {}
    # Fallback is deliberately conservative: label-anchored, not positional guessing.
    for line in text.splitlines():
        low = line.lower()
        for k, desc in _W2_BOXES.items():
            hint = desc.split("(")[0]
            frag = hint.replace("box 1 ", "").replace("box 2 ", "")[:12]
            if frag and frag in low:
                m = re.search(r"(\d[\d,]*\.\d\d)", line)
                if m:
                    out[k] = _num(m.group(1))
    return out


# --- form recognition + entry point ---------------------------------------

def _is_amended(text: str) -> bool:
    # A 1040-X page mentions "Form 1040" in its BODY ("from Form 1040 or 1040-SR"),
    # so a negative-lookahead on the header alone misclassifies it as a primary 1040.
    # Detect the amendment markers directly instead.
    return bool(re.search(r"1040-?X|Amended U\.S|Correct amount|column A\b", text, re.I))


def _classify_pages(pdf) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = {}
    for i, page in enumerate(pdf):
        t = _page_text(page)
        has_1040 = re.search(r"Form\s*1040\b", t) and re.search(r"adjusted gross income", t, re.I)
        if _is_amended(t) and (has_1040 or re.search(r"total tax", t, re.I)):
            groups.setdefault("1040-X", []).append(i)
        elif has_1040:
            groups.setdefault("1040", []).append(i)
        elif re.search(r"W-?2\b.*Wage", t) or len(t.strip()) < _SCAN_TEXT_THRESHOLD:
            groups.setdefault("W-2", []).append(i)
    return groups


def extract(pdf_path: str, *, endpoint: str | None = None, model: str | None = None) -> Extraction:
    """Read a tax PDF into a self-checked, provider-neutral schema."""
    import fitz  # PyMuPDF

    pdf = fitz.open(pdf_path)
    result = Extraction(source_path=pdf_path, page_count=len(pdf))
    groups = _classify_pages(pdf)
    if "1040" in groups:
        result.documents.append(_extract_1040(groups["1040"], pdf))
    if "1040-X" in groups:
        result.documents.append(_extract_1040(groups["1040-X"], pdf, form="1040-X"))
    if "W-2" in groups:
        result.documents.append(
            _extract_w2(groups["W-2"], pdf, endpoint=endpoint, model=model)
        )
    return result

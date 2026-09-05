"""awtax tests. Build a synthetic native-text 1040 page so the core is provable
without shipping anyone's real return, and assert the arithmetic self-check both
PASSES on consistent numbers and FLAGS inconsistent ones (the property that makes
the extraction trustworthy rather than a fragile label->value guess).
"""
from __future__ import annotations

import os
import tempfile

import pytest

fitz = pytest.importorskip("fitz")

from awtax import extract  # noqa: E402
from awtax.schema import Document  # noqa: E402
from awtax.extract import _crosscheck_1040  # noqa: E402
from awtax.schema import Figure  # noqa: E402


def _make_1040(agi, deduction, taxable, tmp):
    """Render a minimal 1040-shaped page: label on the left, amount in the right column."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    rows = [
        (400, "11 This is your adjusted gross income", f"{agi:,.0f}."),
        (430, "12 Standard deduction or itemized deductions", f"{deduction:,.0f}."),
        (460, "15 This is your taxable income", f"{taxable:,.0f}."),
    ]
    page.insert_text((36, 60), "Form 1040 (2024)")
    page.insert_text((36, 80), "adjusted gross income")  # classifier anchor
    for y, label, amt in rows:
        page.insert_text((36, y), label, fontsize=9)
        page.insert_text((500, y), amt, fontsize=9)  # right column (x>380)
    path = os.path.join(tmp, "synthetic_1040.pdf")
    doc.save(path)
    return path


def test_1040_extraction_and_passing_crosscheck(tmp_path):
    path = _make_1040(171890, 21900, 149990, str(tmp_path))
    result = extract(path)
    forms = {d.form: d for d in result.documents}
    assert "1040" in forms, "1040 page should be recognized"
    d = forms["1040"]
    assert d.figures["adjusted_gross_income"].value == 171890
    assert d.figures["taxable_income"].value == 149990
    # 171890 - 21900 == 149990 -> the identity holds -> recorded as a passed check
    assert any("taxable_income = AGI - deduction" in c for c in d.checks)
    assert not d.warnings


def test_crosscheck_flags_inconsistent_numbers():
    d = Document(form="1040")
    d.figures["adjusted_gross_income"] = Figure(100000, "agi")
    d.figures["standard_deduction"] = Figure(20000, "sd")
    d.figures["taxable_income"] = Figure(75000, "ti")  # WRONG: should be 80000
    _crosscheck_1040(d)
    assert d.warnings, "an inconsistent taxable-income must be flagged, not trusted"
    assert d.needs_review


def _make_1040x(tmp):
    """A Form 1040-X page: it mentions 'Form 1040' in its body, which is exactly why
    a naive header lookahead misclassifies it as the primary return."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((36, 60), "Form 1040-X  Amended U.S. Individual Income Tax Return")
    page.insert_text((36, 80), "adjusted gross income")            # 1040 anchor (bait)
    page.insert_text((36, 100), "amounts from Form 1040 or 1040-SR, column A  Correct amount")
    page.insert_text((36, 130), "11 Total tax", fontsize=9)
    page.insert_text((500, 130), "25,347.", fontsize=9)
    path = os.path.join(tmp, "synthetic_1040x.pdf")
    doc.save(path)
    return path


def _make_1040_offset_baseline(agi, deduction, taxable, tmp):
    """A 1040 page where the amount sits on a DIFFERENT text baseline than its label --
    which is how a real IRS form renders (right-column values are not row-aligned to the
    left labels). This is the case the naive same-row pairing missed on the real return."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((36, 60), "Form 1040 (2024)")
    page.insert_text((36, 80), "adjusted gross income")
    rows = [
        (400, "11 This is your adjusted gross income", agi),
        (430, "12 Standard deduction or itemized deductions", deduction),
        (460, "15 This is your taxable income", taxable),
    ]
    for y, label, amt in rows:
        page.insert_text((36, y), label, fontsize=9)
        page.insert_text((505, y + 3), f"{amt:,.0f}.", fontsize=9)  # +3px baseline offset
    path = os.path.join(tmp, "synthetic_1040_offset.pdf")
    doc.save(path)
    return path


def test_1040_reads_offset_baseline_and_crosschecks(tmp_path):
    # regression for the real return: labels and values on different baselines must
    # still pair, and the arithmetic identity must hold -> proves correct pairing.
    path = _make_1040_offset_baseline(171890, 21900, 149990, str(tmp_path))
    d = {x.form: x for x in extract(path).documents}["1040"]
    assert d.figures["adjusted_gross_income"].value == 171890
    assert d.figures["standard_deduction"].value == 21900
    assert d.figures["taxable_income"].value == 149990
    assert any("AGI - deduction" in c for c in d.checks)
    assert not d.needs_review


def test_1040x_is_not_classified_as_primary_1040(tmp_path):
    # regression: on a real 61-page packet the amended page was read AS the 1040.
    path = _make_1040x(str(tmp_path))
    result = extract(path)
    forms = {d.form for d in result.documents}
    assert "1040-X" in forms, "the amended page must be recognized as 1040-X"
    assert "1040" not in forms, "a 1040-X page must NOT be misread as the primary 1040"


def test_empty_recognized_form_needs_review():
    # a recognized form with zero figures must NOT report clean (silent-zero guard)
    d = Document(form="1040")
    assert d.needs_review is True


def test_needs_review_exit_signal(tmp_path):
    # a doc with a failed check must surface needs_review True
    path = _make_1040(100000, 20000, 75000, str(tmp_path))  # inconsistent on purpose
    result = extract(path)
    assert result.to_dict()["needs_review"] is True

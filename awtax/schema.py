"""Provider-neutral tax-document schema.

Every extracted figure carries where it came from (page) and how confident we are,
because a tax number with no provenance is a number nobody can check. This is the
whole point of awtax: not "trust the vendor's sealed file", but "here is every value,
and the page it sits on".
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Figure:
    """One extracted monetary/identifier value with provenance."""
    value: float | str | None
    label: str
    page: int | None = None          # 1-indexed source page
    source: str = "text"             # 'text' (native PDF text) | 'vision' | 'ocr'
    confidence: float = 1.0          # 0..1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Document:
    """A single recognized tax document within a PDF (a 1040, a W-2, a 1099...)."""
    form: str                        # e.g. '1040', '1040-X', 'W-2', '1099-INT'
    tax_year: int | None = None
    figures: dict[str, Figure] = field(default_factory=dict)
    checks: list[str] = field(default_factory=list)      # arithmetic cross-checks that PASSED
    warnings: list[str] = field(default_factory=list)    # cross-checks that FAILED / needs_review
    pages: list[int] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        # A recognized form that yielded NO figures is not "clean" -- it is a failed
        # read. Reporting it clean is the silent-zero failure awtax exists to prevent.
        return (
            not self.figures
            or bool(self.warnings)
            or any(f.confidence < 0.75 for f in self.figures.values())
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "form": self.form,
            "tax_year": self.tax_year,
            "pages": self.pages,
            "figures": {k: v.to_dict() for k, v in self.figures.items()},
            "checks": self.checks,
            "warnings": self.warnings,
            "needs_review": self.needs_review,
        }


@dataclass
class Extraction:
    """The full result of reading one tax PDF."""
    source_path: str
    page_count: int
    documents: list[Document] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "page_count": self.page_count,
            "documents": [d.to_dict() for d in self.documents],
            "needs_review": any(d.needs_review for d in self.documents),
        }

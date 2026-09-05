"""awtax -- turn any tax PDF into structured data you can check.

Open-source extraction core. Point it at a tax PDF (a filed return, a W-2, a 1099,
a statement -- scans included) and get every figure out as a provider-neutral schema
with per-figure provenance and arithmetic self-checks. It reads a document; it does
not give tax advice. Preparation, deduction discovery, worksheets and filing are the
premium TaxDesk packs that compose on top.
"""
from __future__ import annotations

from .extract import extract
from .schema import Document, Extraction, Figure

__all__ = ["extract", "Extraction", "Document", "Figure", "__version__"]
__version__ = "0.1.0"

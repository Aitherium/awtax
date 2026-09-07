# awtax

**Turn any tax PDF — returns, W-2, 1099, statements, even scans — into structured data you can check.**

Your own tax data gets locked inside one vendor's encrypted format, and a filed return or a
mailed W-2 is a PDF nobody's code can read — half of them are scans with no text layer at all.
Getting your own numbers back out means re-typing them or re-buying the app that sealed them.

`awtax` reads the document. It does **not** give tax advice — it hands you every figure, the page
it came from, and whether the arithmetic checks out.

```bash
git clone https://github.com/Aitherium/awtax && cd awtax && pip install -e .
awtax path/to/return.pdf          # -> structured JSON on stdout
```

> Not on PyPI yet, so `pip install awtax` does **not** work — that name resolves
> to nothing today. Install from the clone until a release exists.

## What you get

- **Provider-neutral schema** — every figure carries its `page`, its `source` (`text` / `vision` /
  `ocr`), and a `confidence`. A tax number with no provenance is a number nobody can check.
- **Arithmetic self-checks** — `taxable = AGI − deduction`, `refund = payments − tax`. A figure that
  fails the identity it is defined by is **flagged**, not trusted. The CLI exits `3` when anything
  needs review — silence is not a pass.
- **Scans handled** — a page with no text layer routes to [`awvision`](../awvision) (a vision model
  reads the form fields *structurally*, far better than raw OCR), with a local `tesseract` fallback
  for fully-offline use. If neither is available you get an explicit `needs_review` — **never a
  silent zero.** (That silent-zero-on-a-scan failure is exactly what this fixes.)

## Scan backends (optional)

| backend | how | when |
|---|---|---|
| **awvision** (preferred) | `pip install -e '.[vision]'` from the clone, pass `--endpoint` | a vision model extracts fields as JSON |
| **tesseract** (offline fallback) | install the `tesseract` system binary | no network / no vision endpoint |
| neither | — | pages return `needs_review` with a reason |

## Where awtax stops, and the premium packs begin

awtax is the open-source **extraction core**. Preparation, deduction discovery, worksheets, ledgers
and CPA-ready output are the premium **TaxDesk** agent / skill / tool packs that compose on top via
`awpack` / `awskills`. awtax reads; the packs advise.

## Status

`0.1.0` — reads native-text 1040 pages and scanned W-2s, self-validates, degrades gracefully.
Known next work: 1040-vs-1040-X disambiguation on multi-form packets, richer 1099 coverage,
and native-text W-2 parsing. MIT licensed.

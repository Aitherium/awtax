"""awtax command-line: `awtax path/to/return.pdf` -> JSON on stdout."""
from __future__ import annotations

import argparse
import json
import sys

from .extract import extract


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="awtax",
        description="Turn any tax PDF into structured data you can check.",
    )
    ap.add_argument("pdf", help="path to a tax PDF (return, W-2, 1099, statement)")
    ap.add_argument("--endpoint", default=None, help="awvision endpoint for scanned pages")
    ap.add_argument("--model", default=None, help="vision model override")
    ap.add_argument("--indent", type=int, default=2)
    args = ap.parse_args(argv)

    try:
        result = extract(args.pdf, endpoint=args.endpoint, model=args.model)
    except FileNotFoundError:
        print(f"awtax: no such file: {args.pdf}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover
        print(f"awtax: failed to read {args.pdf}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.to_dict(), indent=args.indent))
    # exit 3 (not 0) when anything needs human review -- silence is not a pass
    return 3 if result.to_dict()["needs_review"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

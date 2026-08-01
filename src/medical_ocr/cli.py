"""Command-line interface for medical-ocr."""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="medical-ocr",
        description=(
            "Extract structured data from medical images via multiple "
            "backends (VLM/Claude/Surya) and score against ground truth."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verbose:
        print("medical-ocr: verbose mode on", file=sys.stderr)
    print("Hello from medical-ocr.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

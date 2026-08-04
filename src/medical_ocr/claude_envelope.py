"""`claude-envelope` — persist a Claude in-session extraction as a standard
envelope (F5 / UC-003 / architecture C3).

Claude is a backend **without a script** (C3): it reads the image *in-session*
from the canonical prompt (``docs/claude-extraction-prompt.md``) and returns one
JSON payload::

    {"raw_text": "<faithful transcription>", "fields": {<ADR-0002 shape>}}

This CLI makes **no LLM or network call**. It only *persists* that payload as the
shared ADR-0002 envelope through ``common.write_envelope`` — ``technique="claude"``,
``model`` set to the Claude model id (Claude is not pure OCR, so ``model`` is never
null) — so ``compare`` treats a Claude run identically to ``vlm-read``/``surya-ocr``.

Usage::

    # Claude returns the JSON in-session; pipe it straight in:
    claude-envelope sample-data/00.jpg < answer.json
    claude-envelope sample-data/00.jpg --from answer.json --model claude-opus-4-8

The payload may also carry ``model`` and ``duration_sec``; the ``--model`` flag
wins over the payload, which wins over the default. ``raw_text``/``fields`` default
to empty (a perception gap still yields a valid envelope). ``durations`` is always
``{}`` — an interactive run has no per-call breakdown.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from medical_ocr.common import Envelope, write_envelope

# The Claude model id recorded when the payload names none and no --model is given.
DEFAULT_MODEL = "claude-opus-4-8"


class ClaudeEnvelopeError(Exception):
    """A user-actionable failure; ``code`` is the process exit code.

    Codes: 2 = usage (missing image, unparseable/wrong-shape payload).
    """

    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------- #
# Payload
# --------------------------------------------------------------------------- #


def _validate_payload(data: Any) -> dict[str, Any]:
    """Structurally validate a Claude extraction payload; return it unchanged.

    Enforces the ADR-0002 shape the envelope depends on: a JSON object whose
    ``fields`` (if present) is itself an object — never an escaped fenced blob —
    and whose ``raw_text`` (if present) is a string. Shared by the stdin/file CLI
    (``_read_payload``) and any in-process caller (``write_from_payload``), so both
    entry points reject the same malformed input identically.
    """
    if not isinstance(data, dict):
        raise ClaudeEnvelopeError("payload must be a JSON object with raw_text and fields")

    if "fields" in data and not isinstance(data["fields"], dict):
        raise ClaudeEnvelopeError(
            "payload 'fields' must be a JSON object (parsed extraction), "
            "not a string or fenced blob — see ADR-0002"
        )
    if "raw_text" in data and not isinstance(data["raw_text"], str):
        raise ClaudeEnvelopeError("payload 'raw_text' must be a string")
    if "model" in data and not isinstance(data["model"], str):
        raise ClaudeEnvelopeError("payload 'model' must be a string")
    # bool is a subclass of int — accept only real numbers, so a stray "duration_sec":
    # true or "4s" fails cleanly (exit 2) rather than crashing later at float()/write.
    if "duration_sec" in data and (
        isinstance(data["duration_sec"], bool) or not isinstance(data["duration_sec"], (int, float))
    ):
        raise ClaudeEnvelopeError("payload 'duration_sec' must be a number")

    return data


def _read_payload(source: Path | None) -> dict[str, Any]:
    """Load and validate Claude's JSON payload from a file or stdin."""
    text = source.read_text() if source is not None else sys.stdin.read()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ClaudeEnvelopeError(f"payload is not valid JSON: {exc}") from exc
    return _validate_payload(data)


def write_from_payload(
    image: str | Path,
    *,
    model: str,
    payload: dict[str, Any],
    duration_sec: float | None = None,
    base: str | Path | None = None,
    output_root: str | Path | None = None,
) -> Path:
    """Validate ``payload`` and write it as a ``technique="claude"`` envelope.

    The single seam other Claude entry points reuse (the stdin/file CLI here, and
    ``claude-extract``) so the envelope shape and validation live in exactly one
    place. ``model`` is recorded verbatim (never null — Claude is not pure OCR).
    ``duration_sec``, if given, overrides the payload's (e.g. ``claude-extract``
    passes the wall-clock the ``claude`` CLI measured); otherwise the payload's
    value is used, defaulting to ``0.0`` for an interactive run. ``durations`` is
    always ``{}`` — a Claude run has no per-call breakdown. Returns the path written.
    """
    _validate_payload(payload)
    dur = duration_sec if duration_sec is not None else float(payload.get("duration_sec", 0.0))
    envelope = Envelope(
        filename=Path(image).name,
        technique="claude",
        model=model,
        raw_text=payload.get("raw_text", ""),
        fields=payload.get("fields", {}),
        duration_sec=dur,
        durations={},
    )
    return write_envelope(envelope, image, base=base, output_root=output_root)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude-envelope",
        description=(
            "Persist a Claude in-session extraction (raw_text + fields JSON) as a "
            "standard extraction envelope. Makes no LLM call — Claude does the "
            "reading in-session (see docs/claude-extraction-prompt.md)."
        ),
        epilog=(
            "examples:\n"
            "  claude-envelope sample-data/00.jpg < answer.json\n"
            "  claude-envelope scan.png --from answer.json --model claude-opus-4-8\n"
            "\n"
            "The payload is one JSON object: "
            '{"raw_text": "…", "fields": {…}} (optional "model", "duration_sec").'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("image", help="path to the image Claude read (used for naming + metadata)")
    parser.add_argument(
        "--from",
        dest="payload_file",
        default=None,
        help="read the JSON payload from this file (default: stdin)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"Claude model id to record (default: payload's, else {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--output-root",
        default=None,
        help="top-level output dir (default: ./output)",
    )
    parser.add_argument(
        "--base",
        default=None,
        help="dir image paths are mirrored under in output/ (default: cwd)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose output")
    return parser


def _run(args: argparse.Namespace) -> None:
    image = Path(args.image)
    if not image.is_file():
        raise ClaudeEnvelopeError(f"image not found: {image}", code=2)

    payload = _read_payload(Path(args.payload_file) if args.payload_file else None)

    # Precedence: --model flag > payload "model" > default. Claude is not pure OCR,
    # so model is always a real id (never null, unlike Surya).
    model = args.model or payload.get("model") or DEFAULT_MODEL

    if args.verbose:
        print(
            f"claude-envelope: recording {image} as technique=claude model={model}", file=sys.stderr
        )

    dest = write_from_payload(
        image, model=model, payload=payload, base=args.base, output_root=args.output_root
    )
    print(dest)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _run(args)
    except ClaudeEnvelopeError as exc:
        print(f"claude-envelope: error: {exc}", file=sys.stderr)
        return exc.code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

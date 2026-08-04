"""`claude-extract` — one-command Claude extraction backend (F7 / #20).

Automates the F5 convention: instead of pasting the canonical prompt into a Claude
session by hand and copying the reply, this runs headless ``claude -p`` for you,
parses the ``{raw_text, fields}`` answer, and hands it to the shared
``claude_envelope`` writer — so the output is byte-identical to a ``claude-envelope``
run and ``compare`` treats it like any other backend.

    claude-extract sample-data/00.jpg [--model claude-opus-4-8] [-v]

**Architecture note (reverses C3):** F5 kept Claude a "convention, not a script"
to avoid depending on a specific Claude CLI. This command deliberately takes that
dependency — it requires the ``claude`` CLI (Claude Code) installed and
authenticated, and each run makes a billable model call — in exchange for a
reproducible one-command flow. See ADR-0005.

The image reaches Claude via its ``Read`` tool: the prompt names the absolute
image path and we pass ``--allowedTools Read --add-dir <image dir>`` so headless
Claude may open it without a permission prompt. ``claude`` is invoked via an argv
list (never a shell), so an image path with shell metacharacters cannot inject.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from medical_ocr import claude_envelope

# Recorded verbatim in the envelope AND passed to `claude --model` (pass-through).
DEFAULT_MODEL = "claude-opus-4-8"

# The Claude Code executable. A module attribute so tests can point elsewhere.
CLAUDE_BIN = "claude"

# Wall-clock ceiling for one headless `claude` call. A real run is ~20–40s; this
# is generous headroom so a wedged CLI fails loudly instead of hanging forever.
CLAUDE_TIMEOUT_SEC = 300

# The canonical extraction instruction (the operational source of the prompt; the
# human-facing walkthrough in docs/claude-extraction-prompt.md documents the same
# convention). Ask for two distinct outputs in one JSON object — a faithful
# transcription (raw_text, "what Claude sees") and the structured extraction
# (fields) — so a missing field is diagnosable as a schema vs. perception gap
# (ADR-0002).
EXTRACTION_PROMPT = """\
You are reading a photo of a hand-written medical prescription. Produce ONE JSON
object and nothing else (no prose, no code fence), with exactly these two keys:

- "raw_text": a faithful, plain-text transcription of EVERYTHING on the note —
  every word, number, and marking — preserving the layout line by line. Do not
  interpret, correct, summarize, or add commentary.
- "fields": the structured data you can read, as a JSON object. Suggested keys
  (include any others you find, omit ones you cannot read): patient_name, date,
  prescriber, medications (a list of objects, each {name, dose, frequency}),
  notes.

"fields" must be a real JSON object, never a string.
"""

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class ClaudeExtractError(Exception):
    """A user-actionable failure; ``code`` is the process exit code.

    Codes: 1 = the `claude` call failed / gave an unusable answer · 2 = usage
    (bad image) · 3 = precondition (`claude` CLI not installed).
    """

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def build_prompt(image_abs: Path) -> str:
    """The full headless prompt: read the image at this path, then extract."""
    return f"Read the image at {image_abs}\n\n{EXTRACTION_PROMPT}"


def _parse_result_object(text: str | None) -> dict[str, Any] | None:
    """Best-effort recover a ``{raw_text, fields}`` JSON object from Claude's reply.

    Handles a bare object, a ```json``` fenced block, and — crucially — an object
    followed by trailing content. Headless Claude inherits the user's global
    instructions, so the reply can carry a trailing end-of-turn sentinel
    (``<!-- CC:DONE -->``) or stray prose after the JSON. We therefore scan from
    each ``{`` and use ``raw_decode``, which reads the first *complete* JSON value
    and ignores whatever follows — robust where a first-brace/last-brace slice
    breaks if the trailing text contains braces. Returns ``None`` when no JSON
    *object* can be recovered.
    """
    if not text:
        return None
    stripped = text.strip()

    fence = _FENCE_RE.match(stripped)
    if fence:
        stripped = fence.group(1).strip()

    # Fast path: the whole thing is exactly one JSON object.
    try:
        whole = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        whole = None
    if isinstance(whole, dict):
        return whole

    # Otherwise, find the first '{' that begins a complete JSON object, ignoring
    # any trailing sentinel/prose. Skip false '{'s (e.g. in leading commentary).
    decoder = json.JSONDecoder()
    index = stripped.find("{")
    while index != -1:
        try:
            value, _ = decoder.raw_decode(stripped, index)
        except (json.JSONDecodeError, ValueError):
            value = None
        if isinstance(value, dict):
            return value
        index = stripped.find("{", index + 1)
    return None


def _child_env() -> dict[str, str]:
    """The environment to hand the spawned ``claude`` — with our venv scrubbed out.

    ``claude-extract`` is typically launched inside the project venv (``uv run`` /
    an activated ``.venv``), which sets ``VIRTUAL_ENV`` and puts ``.venv/bin`` first
    on ``PATH``. If the child ``claude`` inherited that, the user's own hooks (e.g.
    a ``UserPromptSubmit`` hook that runs ``python3``) would resolve tools to *our*
    venv instead of the interpreter they'd use interactively — breaking hooks that
    depend on packages absent from our venv. We therefore drop ``VIRTUAL_ENV`` and
    remove that venv's ``bin`` from ``PATH``, so the nested ``claude`` runs in the
    environment it would have if the user had launched it themselves.
    """
    env = dict(os.environ)
    venv = env.pop("VIRTUAL_ENV", None)
    if venv:
        venv_bin = str(Path(venv) / "bin")
        parts = [p for p in env.get("PATH", "").split(os.pathsep) if p and p != venv_bin]
        env["PATH"] = os.pathsep.join(parts)
    return env


def _run_claude(image_abs: Path, model: str, *, verbose: bool) -> dict[str, Any]:
    """Invoke headless ``claude`` and return the parsed ``--output-format json`` wrapper.

    Raises :class:`ClaudeExtractError` if the CLI is absent (code 3), exits
    non-zero, reports an error result, or does not emit parseable JSON (code 1).
    """
    argv = [
        CLAUDE_BIN,
        "-p",
        build_prompt(image_abs),
        "--model",
        model,
        "--output-format",
        "json",
        "--allowedTools",
        "Read",
        "--add-dir",
        str(image_abs.parent),
    ]
    if verbose:
        print(f"claude-extract: running {CLAUDE_BIN} -p … --model {model}", file=sys.stderr)

    try:
        # env=_child_env(): don't leak our venv onto the nested claude's hooks.
        proc = subprocess.run(
            argv, capture_output=True, text=True, env=_child_env(), timeout=CLAUDE_TIMEOUT_SEC
        )  # noqa: S603 (argv, no shell)
    except FileNotFoundError as exc:
        raise ClaudeExtractError(
            f"`{CLAUDE_BIN}` CLI not found on PATH — install Claude Code and sign in "
            f"(https://claude.com/claude-code). ({exc})",
            code=3,
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ClaudeExtractError(
            f"claude did not respond within {CLAUDE_TIMEOUT_SEC}s — aborted.", code=1
        ) from exc

    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "(no output)"
        raise ClaudeExtractError(f"claude exited {proc.returncode}: {detail}", code=1)

    try:
        wrapper = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ClaudeExtractError(
            f"could not parse `claude --output-format json` output: {exc}", code=1
        ) from exc

    if not isinstance(wrapper, dict) or wrapper.get("is_error"):
        detail = (
            (wrapper.get("result") or wrapper.get("subtype"))
            if isinstance(wrapper, dict)
            else wrapper
        )
        raise ClaudeExtractError(f"claude returned an error result: {detail}", code=1)

    return wrapper


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude-extract",
        description=(
            "Extract structured data from a medical image with Claude in one "
            "command: runs headless `claude -p` and writes a standard extraction "
            "envelope (identical to the claude-envelope convention)."
        ),
        epilog=(
            "examples:\n"
            "  claude-extract sample-data/00.jpg\n"
            "  claude-extract scan.png --model claude-opus-4-8 --output-root output\n"
            "\n"
            "Requires the `claude` CLI (Claude Code) installed and signed in; each "
            "run makes a billable model call. See ADR-0005."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("image", help="path to the image file to read")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Claude model id — passed to `claude --model` and recorded (default: %(default)s)",
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
        raise ClaudeExtractError(f"image not found: {image}", code=2)
    image_abs = image.resolve()

    wrapper = _run_claude(image_abs, args.model, verbose=args.verbose)

    payload = _parse_result_object(wrapper.get("result"))
    if payload is None:
        snippet = str(wrapper.get("result"))[:300].replace("\n", " ")
        raise ClaudeExtractError(
            "claude's reply was not the expected {raw_text, fields} JSON object; "
            f"got: {snippet!r}",
            code=1,
        )

    # Prefer the wall-clock the claude CLI actually measured over a best-effort 0.
    duration_ms = wrapper.get("duration_ms")
    duration_sec = round(duration_ms / 1000, 3) if isinstance(duration_ms, (int, float)) else 0.0

    dest = claude_envelope.write_from_payload(
        image,
        model=args.model,
        payload=payload,
        duration_sec=duration_sec,
        base=args.base,
        output_root=args.output_root,
    )
    print(dest)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _run(args)
    except ClaudeExtractError as exc:
        print(f"claude-extract: error: {exc}", file=sys.stderr)
        return exc.code
    except claude_envelope.ClaudeEnvelopeError as exc:
        # The shared writer rejected the payload shape (e.g. fields not an object).
        print(f"claude-extract: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

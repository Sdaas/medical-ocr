"""`vlm-read` — extract structured data from an image via a named VLM (F2).

Usage::

    vlm-read <image> <model> [--output-root DIR] [--base DIR] [-v]

Makes **two** focused VLM calls through LiteLLM (ADR-0001) into one ADR-0002
envelope (issue #13): call 1 *transcribes* the note as plain text → ``raw_text``
("what the VLM sees"); call 2 *extracts* structured data → parsed into ``fields``
("what our schema captured"). Each call is timed separately (``durations``); the
total is ``duration_sec``. ``--no-transcribe`` skips call 1 (extraction only) and
falls back to keeping the extraction reply in ``raw_text`` only if it fails to
parse, so a run never loses output.

**Scope (F2):** only local **Ollama** models (``ollama/<model>`` or
``ollama_chat/<model>``) are supported today. Cloud providers are stubbed and
error out with a pointer to issue #5. Before calling, the command preflights the
local Ollama server (reachable? model pulled?) so failures are actionable.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from litellm import completion

from medical_ocr.common import Envelope, Timer, write_envelope

# Deferred cloud-provider work (Anthropic/OpenAI/Gemini) lives in this issue.
CLOUD_ISSUE = "#5"

# Ollama's default context window (num_ctx) is only 2048 tokens. A photo can eat
# ~3000 input tokens on its own, so with the default the prompt+image alone can
# overflow the window — and a *reasoning* model (qwen3-vl, …) then spends what
# little is left on its private "thinking" and gets cut off (finish_reason
# "length") before writing any answer to `content`. We raise the window so there
# is room for the image, the reasoning, and the answer.
DEFAULT_NUM_CTX = 16384

# Call 1 — transcribe. Ask the VLM to faithfully read *everything* on the note
# as plain text. Stored in `raw_text`: "what the VLM sees", independent of our
# schema. Comparing this against `fields` tells a perception gap (unreadable) from
# a schema gap (read but not captured under ADR-0002). See issue #13.
TRANSCRIBE_PROMPT = """\
You are reading a photo of a hand-written medical prescription. Transcribe
EVERYTHING you can see on the note — every word, number, and marking — as
faithfully as possible, in plain text, preserving the layout line by line.

Do not interpret, summarize, correct, or add commentary. Output only the
transcription.
"""

# Call 2 — extract. The ADR-0002 extraction prompt (unchanged): its JSON reply is
# parsed into the envelope's `fields`. Starter field set is suggested, not enforced
# — the model may add or omit keys; scoring and other backends converge on these.
EXTRACT_PROMPT = """\
You are extracting structured data from a photo of a hand-written medical
prescription. Return ONLY a JSON object with the fields you can read.

Suggested keys (include any others you find, omit ones you cannot read):
- patient_name
- date
- prescriber
- medications: a list of objects, each {name, dose, frequency}
- notes

Do not include any commentary or explanation — output the JSON object only.
"""

_MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


class VlmReadError(Exception):
    """A user-actionable failure; ``code`` is the process exit code.

    Codes: 1 = model/API call failed · 2 = usage (bad image) · 3 = precondition
    (cloud model unsupported / Ollama down / model not pulled).
    """

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------- #
# Response parsing (best-effort)
# --------------------------------------------------------------------------- #

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _try_json_object(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _parse_fields(text: str | None) -> dict | None:
    """Best-effort extract a JSON object from a model reply.

    Handles a bare object, a ```json``` fenced block, and an object embedded in
    prose. Returns ``None`` when no JSON *object* can be recovered.
    """
    if not text:
        return None
    stripped = text.strip()

    fence = _FENCE_RE.match(stripped)
    if fence:
        stripped = fence.group(1).strip()

    obj = _try_json_object(stripped)
    if obj is not None:
        return obj

    start, end = stripped.find("{"), stripped.rfind("}")
    if 0 <= start < end:
        obj = _try_json_object(stripped[start : end + 1])
        if obj is not None:
            return obj
    return None


# --------------------------------------------------------------------------- #
# Image encoding
# --------------------------------------------------------------------------- #


def _image_data_uri(path: str | Path) -> str:
    """Encode an image file as a ``data:`` URI for the LiteLLM vision message."""
    path = Path(path)
    mime = _MIME_BY_SUFFIX.get(path.suffix.lower(), "image/jpeg")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _build_messages(prompt: str, data_uri: str) -> list[dict]:
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        }
    ]


# --------------------------------------------------------------------------- #
# Ollama preflight (runtime — server-running and model-present drift)
# --------------------------------------------------------------------------- #


def _ollama_base() -> str:
    """Base URL of the Ollama server (LiteLLM's ``OLLAMA_API_BASE``)."""
    return os.environ.get("OLLAMA_API_BASE") or "http://localhost:11434"


def _ollama_model_name(model: str) -> str | None:
    """The Ollama model name behind a LiteLLM id, or ``None`` if not Ollama."""
    for prefix in ("ollama/", "ollama_chat/"):
        if model.startswith(prefix):
            return model[len(prefix) :]
    return None


def _ollama_models(base: str) -> list[str]:
    """Names of models the Ollama server currently has (``GET /api/tags``)."""
    url = base.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 (local URL)
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise VlmReadError(
            f"Ollama not reachable at {base} — is `ollama serve` running? ({exc})",
            code=3,
        ) from exc
    return [m.get("name", "") for m in data.get("models", [])]


def _model_present(name: str, tags: list[str]) -> bool:
    """Whether ``name`` matches a pulled tag (untagged matches ``:latest`` etc.)."""
    if name in tags:
        return True
    if ":" not in name:
        return any(tag.split(":", 1)[0] == name for tag in tags)
    return False


def _require_ollama(model: str) -> None:
    """Preflight: the model must be a supported, reachable, pulled Ollama model."""
    name = _ollama_model_name(model)
    if name is None:
        raise VlmReadError(
            f"cloud VLM providers are not implemented yet (see issue {CLOUD_ISSUE}); "
            f"only local Ollama models are supported — use e.g. `ollama/{model}`.",
            code=3,
        )
    tags = _ollama_models(_ollama_base())
    if not _model_present(name, tags):
        available = ", ".join(sorted(tags)) or "(none)"
        raise VlmReadError(
            f"Ollama model '{name}' not pulled — run `ollama pull {name}`. Available: {available}",
            code=3,
        )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vlm-read",
        description=(
            "Extract structured data from a medical image via a named VLM "
            "(through LiteLLM) and write an extraction envelope JSON."
        ),
        epilog=(
            "examples:\n"
            "  vlm-read sample-data/00.jpg ollama/llava\n"
            "  vlm-read scan.png ollama/llama3.2-vision --output-root output\n"
            "\n"
            "Only local Ollama models (ollama/<model>) are supported today; "
            f"cloud providers are tracked in issue {CLOUD_ISSUE}."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("image", help="path to the image file to read")
    parser.add_argument("model", help="LiteLLM model id, e.g. ollama/llava")
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
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=DEFAULT_NUM_CTX,
        help=(
            "Ollama context window in tokens (default: %(default)s). Raise it if "
            "output is truncated on large images or reasoning models."
        ),
    )
    parser.add_argument(
        "--no-transcribe",
        action="store_true",
        help=(
            "skip the plain-text transcription call (call 1); extract only. "
            "raw_text is left empty unless the extraction reply fails to parse."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose output")
    return parser


def _vlm_call(
    model: str,
    messages: list[dict],
    *,
    api_base: str,
    num_ctx: int,
    label: str,
) -> tuple[str, float]:
    """Make one VLM completion and return ``(text, duration_sec)``.

    Pins the endpoint to the one preflight verified (so LiteLLM's default can't
    reroute) and forwards ``num_ctx`` so the window fits image + reasoning +
    answer. Warns on truncation, and — honouring "never lose output" — falls back
    to the reasoning channel if the model answered only there. ``label``
    ("transcribe"/"extract") tags the warnings so the user knows which call.
    """
    try:
        with Timer() as timer:
            response = completion(
                model=model,
                messages=messages,
                api_base=api_base,
                num_ctx=num_ctx,
            )
    except Exception as exc:  # noqa: BLE001 — surface any provider error as exit 1
        raise VlmReadError(f"model call failed for {model}: {exc}", code=1) from exc

    choice = response.choices[0]
    text = choice.message.content or ""
    # Reasoning models put their "thinking" here; LiteLLM surfaces it separately.
    reasoning = getattr(choice.message, "reasoning_content", None) or ""

    # If the model was cut off (finish_reason "length"), the answer is likely
    # truncated or — for a reasoning model that never got to answer — empty.
    if getattr(choice, "finish_reason", None) == "length":
        print(
            f"vlm-read: warning: {label} response hit the context limit "
            f"(num_ctx={num_ctx}); output may be truncated — retry with a larger "
            "--num-ctx.",
            file=sys.stderr,
        )

    # Never lose the model's output: if it answered only in its reasoning channel,
    # fall back to that so the text is not silently empty.
    if not text and reasoning:
        print(
            f"vlm-read: warning: {label} returned an empty answer but non-empty "
            "reasoning; keeping the reasoning.",
            file=sys.stderr,
        )
        text = reasoning

    return text, timer.duration_sec


def _run(args: argparse.Namespace) -> None:
    image = Path(args.image)
    if not image.is_file():
        raise VlmReadError(f"image not found: {image}", code=2)

    _require_ollama(args.model)

    if args.verbose:
        print(f"vlm-read: sending {image} to {args.model}", file=sys.stderr)

    data_uri = _image_data_uri(image)
    api_base = _ollama_base()
    transcribe = not args.no_transcribe
    durations: dict[str, float] = {}

    # Call 1 — transcribe (default): plain-text "what the VLM sees" → raw_text.
    raw_text = ""
    if transcribe:
        raw_text, durations["transcribe"] = _vlm_call(
            args.model,
            _build_messages(TRANSCRIBE_PROMPT, data_uri),
            api_base=api_base,
            num_ctx=args.num_ctx,
            label="transcribe",
        )

    # Call 2 — extract: JSON reply parsed into `fields` ("what our schema captured").
    extract_text, durations["extract"] = _vlm_call(
        args.model,
        _build_messages(EXTRACT_PROMPT, data_uri),
        api_base=api_base,
        num_ctx=args.num_ctx,
        label="extract",
    )

    fields = _parse_fields(extract_text)
    if fields is None:
        print(
            "vlm-read: warning: could not parse JSON fields from the extraction "
            "reply; writing empty fields.",
            file=sys.stderr,
        )
        fields = {}
        # Preserve "never lose output": with no transcription there is nothing else
        # in raw_text, so keep the unparseable extraction reply there. On a normal
        # run raw_text already holds the transcription, which we must not clobber
        # (AC #4: raw_text is never a fenced/escaped JSON blob on a normal run).
        if not transcribe:
            raw_text = extract_text

    # `durations` records a number per call performed; the breakdown is only
    # meaningful when more than one call ran, so a single-call run leaves it empty.
    total = sum(durations.values())
    envelope = Envelope(
        filename=image.name,
        technique="vlm",
        model=args.model,
        raw_text=raw_text,
        fields=fields,
        duration_sec=total,
        durations=durations if transcribe else {},
    )
    dest = write_envelope(envelope, image, base=args.base, output_root=args.output_root)
    print(dest)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _run(args)
    except VlmReadError as exc:
        print(f"vlm-read: error: {exc}", file=sys.stderr)
        return exc.code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

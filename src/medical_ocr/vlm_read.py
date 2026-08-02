"""`vlm-read` — extract structured data from an image via a named VLM (F2).

Usage::

    vlm-read <image> <model> [--output-root DIR] [--base DIR] [-v]

Sends the image to ``model`` through LiteLLM (ADR-0001), times the call, and
writes an ADR-0002 envelope via :mod:`medical_ocr.common`. The model reply is
best-effort parsed into the envelope's structured ``fields``; the full reply is
always kept in ``raw_text`` so nothing is lost.

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

# Starter field set (ADR-0002 example). Suggested, not enforced — the model may
# add or omit keys; scoring and other backends converge on these names.
PROMPT = """\
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
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose output")
    return parser


def _run(args: argparse.Namespace) -> None:
    image = Path(args.image)
    if not image.is_file():
        raise VlmReadError(f"image not found: {image}", code=2)

    _require_ollama(args.model)

    if args.verbose:
        print(f"vlm-read: sending {image} to {args.model}", file=sys.stderr)

    messages = _build_messages(PROMPT, _image_data_uri(image))
    try:
        with Timer() as timer:
            # Pin the endpoint to the one preflight verified, so LiteLLM's own
            # default can't route the call to a different Ollama server.
            response = completion(model=args.model, messages=messages, api_base=_ollama_base())
    except Exception as exc:  # noqa: BLE001 — surface any provider error as exit 1
        raise VlmReadError(f"model call failed for {args.model}: {exc}", code=1) from exc

    raw_text = response.choices[0].message.content or ""
    fields = _parse_fields(raw_text)
    if fields is None:
        print(
            "vlm-read: warning: could not parse JSON fields from the model reply; "
            "writing raw_text only.",
            file=sys.stderr,
        )
        fields = {}

    envelope = Envelope(
        filename=image.name,
        technique="vlm",
        model=args.model,
        raw_text=raw_text,
        fields=fields,
        duration_sec=timer.duration_sec,
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

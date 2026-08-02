#!/usr/bin/env python3
"""Throwaway debug harness — talk to the Ollama HTTP API directly (no litellm).

Goal: find out WHY `vlm-read` got an empty `raw_text`. We bypass litellm entirely
and hit Ollama's `/api/chat` ourselves so we can see the *whole* response —
including `message.thinking`, `done_reason`, and token counts — none of which the
CLI surfaces.

Run Ollama with verbose logs in one terminal:

    OLLAMA_DEBUG=1 ollama serve

Then, from another terminal:

    uv run python tools/debug_ollama.py                  # sample-data/01.jpg, qwen3-vl:8b
    uv run python tools/debug_ollama.py sample-data/00.jpg ollama/llava

An ad-hoc developer tool for poking Ollama directly (not part of the product,
not run by test.sh). Run it from the repo root so the sample-data paths resolve.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

BASE = os.environ.get("OLLAMA_API_BASE") or "http://localhost:11434"

# Same instruction shape as the real CLI would send (text + image), but simple —
# we only care whether the model returns *any* answer text at all.
PROMPT = (
    "Extract all handwritten text from this image exactly as written. "
    "If anything is unreadable write [unclear]."
)


def _post(path: str, payload: dict, timeout: float = 300.0) -> dict:
    """POST JSON to the Ollama server and return the decoded JSON reply."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (local)
        return json.loads(resp.read())


def _get(path: str, timeout: float = 10.0) -> dict:
    with urllib.request.urlopen(BASE.rstrip("/") + path, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read())


def _strip_prefix(model: str) -> str:
    """Accept either `qwen3-vl:8b` or litellm-style `ollama/qwen3-vl:8b`."""
    for p in ("ollama/", "ollama_chat/"):
        if model.startswith(p):
            return model[len(p) :]
    return model


def _summarize(resp: dict) -> None:
    """Print the fields that actually diagnose an empty answer."""
    msg = resp.get("message", {}) or {}
    content = msg.get("content") or ""
    thinking = msg.get("thinking") or msg.get("reasoning") or ""
    print("---- summary -------------------------------------------------")
    print(f"  done            : {resp.get('done')}")
    print(f"  done_reason     : {resp.get('done_reason')!r}")
    print(f"  prompt_eval_cnt : {resp.get('prompt_eval_count')}   (input tokens)")
    print(f"  eval_count      : {resp.get('eval_count')}   (output tokens)")
    print(f"  content length  : {len(content)} chars")
    print(f"  thinking length : {len(thinking)} chars")
    if not content and thinking:
        print("  >> DIAGNOSIS: model put its output in `thinking`, `content` is EMPTY.")
        print("     That is exactly why vlm-read's raw_text is blank.")
    elif not content:
        print("  >> content is empty AND no thinking — model returned nothing at all.")
    print("--------------------------------------------------------------")


def _chat(model: str, image_b64: str, *, think: bool | None) -> dict:
    payload: dict = {
        "model": model,
        "messages": [
            {"role": "user", "content": PROMPT, "images": [image_b64]},
        ],
        "stream": False,
    }
    if think is not None:
        payload["think"] = think  # Ollama flag to force thinking on/off
    label = "default" if think is None else f"think={think}"
    print(f"\n===== POST /api/chat  ({model}, {label}) =====")
    resp = _post("/api/chat", payload)
    print(json.dumps(resp, indent=2))
    _summarize(resp)
    return resp


def main(argv: list[str]) -> int:
    image_path = Path(argv[1]) if len(argv) > 1 else Path("sample-data/01.jpg")
    model = _strip_prefix(argv[2] if len(argv) > 2 else "qwen3-vl:8b")

    if not image_path.is_file():
        print(f"image not found: {image_path}", file=sys.stderr)
        return 2

    print(f"Ollama base : {BASE}")
    print(f"image       : {image_path}  ({image_path.stat().st_size} bytes)")
    print(f"model       : {model}")

    # 1) Is the server up, and is the model pulled?
    print("\n===== GET /api/tags =====")
    tags = _get("/api/tags")
    names = [m.get("name") for m in tags.get("models", [])]
    print("available models:", names)
    if not any(n == model or n.split(":", 1)[0] == model.split(":", 1)[0] for n in names):
        print(f"WARNING: '{model}' not in the pulled list — `ollama pull {model}`")

    image_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")

    # 2) The real call, default behavior.
    resp = _chat(model, image_b64, think=None)

    # 3) If content is empty but the model was thinking, prove the hypothesis by
    #    forcing thinking OFF and seeing whether the answer text appears.
    msg = resp.get("message", {}) or {}
    if not (msg.get("content") or "") and (msg.get("thinking") or ""):
        print("\n>> content was empty with thinking present — retrying with think=False...")
        _chat(model, image_b64, think=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

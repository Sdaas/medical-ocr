#!/usr/bin/env python3
"""Phase-1 model characterization matrix (research tool, NOT product code).

Runs each installed vision model on a sample image at both the Ollama default
context window and a raised one, using vlm-read's REAL extraction prompt and
parser, so every cell answers: does this model return parseable JSON — and if
not, why (empty? truncated? reasoning-only?).

Hits Ollama's /api/chat directly (bypassing litellm) so we can read done_reason,
`thinking`, and token counts unfiltered. Results stream to a JSONL file so
partial progress survives interruption; a markdown table is printed at the end.

    uv run python tools/bench_models.py

An ad-hoc developer tool (not part of the product, not run by test.sh). Run it
from the repo root so the sample-data paths resolve.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.request
from pathlib import Path

from medical_ocr.vlm_read import PROMPT, _parse_fields  # reuse the real prompt/parser

BASE = os.environ.get("OLLAMA_API_BASE") or "http://localhost:11434"
IMAGE = Path("sample-data/01.jpg")  # the 2 MB image that exposed the bug
MODELS = [
    "qwen3-vl:2b",
    "qwen3-vl:4b",
    "qwen3-vl:8b",
    "qwen2.5vl:7b",
    "llama3.2-vision:11b",
    "gemma3:12b",
]
CTX_SETTINGS = [None, 16384]  # None = Ollama default (2048)
RESULTS = Path("/tmp/bench_results.jsonl")


def chat(model: str, image_b64: str, num_ctx: int | None) -> dict:
    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT, "images": [image_b64]}],
        "stream": False,
    }
    if num_ctx is not None:
        payload["options"] = {"num_ctx": num_ctx}
    req = urllib.request.Request(
        BASE.rstrip("/") + "/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=600) as resp:  # noqa: S310 (local)
        body = json.loads(resp.read())
    body["_wall_sec"] = round(time.perf_counter() - t0, 1)
    return body


def one_cell(model: str, image_b64: str, num_ctx: int | None) -> dict:
    try:
        r = chat(model, image_b64, num_ctx)
        msg = r.get("message", {}) or {}
        content = msg.get("content") or ""
        thinking = msg.get("thinking") or ""
        raw_text = content or thinking  # mirror vlm-read's fallback
        parsed = _parse_fields(raw_text)
        return {
            "model": model,
            "num_ctx": num_ctx or "default",
            "done_reason": r.get("done_reason"),
            "reasoning": bool(thinking),
            "content_len": len(content),
            "thinking_len": len(thinking),
            "parseable": parsed is not None,
            "n_fields": len(parsed) if parsed else 0,
            "prompt_tok": r.get("prompt_eval_count"),
            "out_tok": r.get("eval_count"),
            "wall_sec": r.get("_wall_sec"),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 — record and continue the matrix
        return {"model": model, "num_ctx": num_ctx or "default", "error": repr(exc)}


def main() -> int:
    image_b64 = base64.b64encode(IMAGE.read_bytes()).decode()
    RESULTS.write_text("")  # fresh run
    rows: list[dict] = []
    for model in MODELS:  # model-outer so each loads once
        for ctx in CTX_SETTINGS:
            print(f"... {model:22} ctx={ctx or 'default'}", flush=True)
            row = one_cell(model, image_b64, ctx)
            rows.append(row)
            with RESULTS.open("a") as f:
                f.write(json.dumps(row) + "\n")

    # Markdown table
    hdr = (
        "| model | num_ctx | done_reason | reason? | content | think | "
        "parseable | fields | in_tok | out_tok | sec |"
    )
    sep = "|" + "---|" * 11
    lines = [hdr, sep]
    for r in rows:
        if r.get("error"):
            lines.append(f"| {r['model']} | {r['num_ctx']} | ERROR: {r['error'][:40]} |||||||||")
            continue
        lines.append(
            f"| {r['model']} | {r['num_ctx']} | {r['done_reason']} | "
            f"{'Y' if r['reasoning'] else 'n'} | {r['content_len']} | {r['thinking_len']} | "
            f"{'YES' if r['parseable'] else 'no'} | {r['n_fields']} | "
            f"{r['prompt_tok']} | {r['out_tok']} | {r['wall_sec']} |"
        )
    table = "\n".join(lines)
    Path("/tmp/bench_table.md").write_text(table + "\n")
    print("\n" + table)
    print("\nDONE — results in /tmp/bench_results.jsonl and /tmp/bench_table.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

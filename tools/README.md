# tools/ — ad-hoc developer utilities

Throwaway-but-kept scripts for poking a local Ollama server directly. **Not part
of the product, not run by `test.sh`, not covered by CI.** Run them from the repo
root (they resolve `sample-data/...` relative to the working directory) with a
local Ollama running (`ollama serve`).

- **`debug_ollama.py`** — send one image to one model via Ollama's `/api/chat`
  (bypassing litellm) and dump the full response: `content`, `thinking`,
  `done_reason`, and token counts. Use it to see *why* a call misbehaves.

  ```bash
  uv run python tools/debug_ollama.py sample-data/01.jpg qwen3-vl:8b
  ```

- **`bench_models.py`** — characterization matrix: each installed vision model ×
  the sample image × {default context, `num_ctx=16384`}, using vlm-read's real
  prompt and parser. Prints a markdown table of reasoning?/`done_reason`/parseable
  /tokens. This is how issue #9 (empty output) and #10 (llama3.2-vision 500) were
  diagnosed.

  ```bash
  uv run python tools/bench_models.py
  ```

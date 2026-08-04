# Claude extraction convention (F5 · UC-003 · architecture C3)

Claude is a backend **without a script**. Unlike `vlm-read` (F2) or `surya-ocr`
(F4), there is no executable that calls an LLM — Claude reads the image **in the
session you are already in** and you persist its answer as the *same* envelope the
CLIs write, to the *same* `output/` location. `compare` (F3) then scores it with
**no Claude-specific handling**.

This page is the repeatable procedure. It has three parts: the **canonical
prompt**, the **convention** for the envelope, and the **`claude-envelope`
helper** that writes it.

> **Have the `claude` CLI?** `claude-extract <image>` (ADR-0005) automates this
> entire page in one command — it runs headless `claude -p` with this prompt and
> writes the envelope for you. This page remains the source of the prompt/envelope
> shape and the fallback when the CLI isn't available. See the README.

---

## 1. The canonical prompt

Attach the prescription image to a Claude session and send the prompt below
verbatim. It asks for **two distinct outputs in one JSON object**: a faithful
transcription (`raw_text` — "what Claude sees") and a structured extraction
(`fields` — "what our schema captured"). Keeping them distinct is what makes a
missing field diagnosable (ADR-0002): present in `raw_text` but absent from
`fields` → a **schema** gap; absent from both → a **perception** gap.

> You are reading a photo of a hand-written medical prescription. Produce **one
> JSON object and nothing else**, with exactly these two keys:
>
> - `"raw_text"`: a faithful, plain-text transcription of EVERYTHING on the note
>   — every word, number, and marking — preserving the layout line by line. Do
>   not interpret, correct, summarize, or add commentary.
> - `"fields"`: the structured data you can read, as a JSON object. Suggested
>   keys (include any others you find; omit ones you cannot read):
>   - `patient_name`
>   - `date`
>   - `prescriber`
>   - `medications`: a list of objects, each `{name, dose, frequency}`
>   - `notes`
>
> Output only the JSON object — no prose, no code fence. `fields` must be a real
> JSON object, never a string.

The suggested field set mirrors `vlm-read`'s extract prompt so all backends
converge on the same shape. The model may add or omit keys.

## 2. The convention (what the envelope must contain)

Claude's reply *is* the payload. Persisting it yields a standard ADR-0002
envelope with these backend-specific values:

| Field | Value |
|---|---|
| `technique` | `"claude"` |
| `model` | the Claude model id used, e.g. `claude-opus-4-8` — **never null** (Claude is not pure OCR, unlike Surya) |
| `raw_text` | the faithful transcription from the reply |
| `fields` | the structured extraction, as **real parsed JSON** in the ADR-0002 shape — never an escaped/fenced string, and there is **no `raw_json` field** |
| `duration_sec` | best-effort; `0.0` is fine for an interactive run |
| `durations` | always `{}` — an interactive run has no per-call breakdown |
| `filename`, `timestamp` | filled automatically |

The envelope is written via `common.output_path` / `common.write_envelope`, so it
lands at the same conventional location the CLIs use and in the same key order:

```
output/<image_parent_rel>/<stem>.claude.<model>.json
```

The model segment is part of the C8 output-path convention (exactly like
`vlm-read`'s `….vlm.ollama-llava.json`), so runs from different Claude models
never collide — no special-casing versus the other backends.

## 3. The `claude-envelope` helper

Save Claude's JSON reply to a file (or pipe it directly), then:

```bash
# from a file
claude-envelope sample-data/00.jpg --from answer.json --model claude-opus-4-8

# or straight from stdin
claude-envelope sample-data/00.jpg --model claude-opus-4-8 < answer.json
```

The helper makes **no LLM or network call** — Claude already did the reading. It
only validates the payload shape and writes the envelope. Flags:

- `--model` — the Claude model id to record (default: the payload's `model`, else
  `claude-opus-4-8`). The flag wins over the payload.
- `--from FILE` — read the payload from a file instead of stdin.
- `--output-root DIR` / `--base DIR` — same meaning as in `vlm-read`.

It exits non-zero (code 2) with a clear message if the payload is not valid JSON,
is not a JSON object, or its `fields` is not an object (i.e. an escaped blob).

### Worked example

For image `sample-data/00.jpg`, Claude returns (illustrative):

```json
{
  "raw_text": "Patient: Jane Doe\nRx: amoxicillin 500mg\nSig: 1 tab tid",
  "fields": {
    "patient_name": "Jane Doe",
    "medications": [{ "name": "amoxicillin", "dose": "500mg", "frequency": "tid" }]
  }
}
```

Piping that through `claude-envelope sample-data/00.jpg` writes
`output/sample-data/00.claude.claude-opus-4-8.json`:

```json
{
  "filename": "00.jpg",
  "technique": "claude",
  "model": "claude-opus-4-8",
  "duration_sec": 0.0,
  "durations": {},
  "timestamp": "2026-08-04T…",
  "raw_text": "Patient: Jane Doe\nRx: amoxicillin 500mg\nSig: 1 tab tid",
  "fields": {
    "patient_name": "Jane Doe",
    "medications": [{ "name": "amoxicillin", "dose": "500mg", "frequency": "tid" }]
  }
}
```

This validates via `common.Envelope.from_dict` and shares `vlm-read`'s exact key
order, so `compare <that>.json --truth sample-data/00.truth.json` scores it with
no Claude-specific handling. (The ground-truth sidecar is authored separately per
ADR-0003; the machine output above stays in the gitignored `output/` tree.)

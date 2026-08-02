"""Tests for the `vlm-read` CLI (F2).

`vlm-read file.jpg model-name` sends an image to a named VLM via LiteLLM
(ADR-0001), times it, and writes an ADR-0002 envelope through `common`. For now
only local Ollama models are supported; cloud providers are stubbed (issue #5).

Nearly all tests are hermetic: `litellm.completion` and the Ollama `/api/tags`
lookup are stubbed, so no network call or real model is ever touched. The one
exception is `test_data_uri_survives_real_ollama_image_conversion`, which drives
litellm's real (local, offline) image-conversion to guard the Pillow dependency
(#7).
"""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest

from medical_ocr import vlm_read

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def fake_response(content: str):
    """Mimic the shape of a litellm completion response."""
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def make_image(tmp_path, name="scan.jpg"):
    img = tmp_path / "sample-data" / name
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes(b"\xff\xd8\xff fake jpeg bytes")
    return img


@pytest.fixture
def ollama_ok(monkeypatch):
    """Pretend the Ollama server is up with `llava` pulled."""
    monkeypatch.setattr(vlm_read, "_ollama_models", lambda base: ["llava:latest"])


def run(argv, monkeypatch, content=None, completion=None):
    """Run main() with `completion` stubbed; return (rc, calls)."""
    calls = []

    def default_completion(**kwargs):
        calls.append(kwargs)
        return fake_response(content if content is not None else "{}")

    monkeypatch.setattr(vlm_read, "completion", completion or default_completion)
    rc = vlm_read.main(argv)
    return rc, calls


# --------------------------------------------------------------------------- #
# Parser / help
# --------------------------------------------------------------------------- #


def test_parser_prog_and_help_text():
    parser = vlm_read.build_parser()
    assert parser.prog == "vlm-read"
    assert parser.description
    assert parser.epilog  # usage examples for --help


# --------------------------------------------------------------------------- #
# Field parsing (best-effort)
# --------------------------------------------------------------------------- #


def test_parse_fields_plain_json():
    assert vlm_read._parse_fields('{"patient_name": "Jane"}') == {"patient_name": "Jane"}


def test_parse_fields_strips_json_fences():
    text = '```json\n{"a": 1}\n```'
    assert vlm_read._parse_fields(text) == {"a": 1}


def test_parse_fields_finds_object_in_prose():
    text = 'Sure! Here is the data: {"a": 1, "b": 2} — hope that helps.'
    assert vlm_read._parse_fields(text) == {"a": 1, "b": 2}


def test_parse_fields_none_on_prose():
    assert vlm_read._parse_fields("I cannot read this image.") is None


def test_parse_fields_none_on_non_object():
    # A JSON array is valid JSON but not a fields object.
    assert vlm_read._parse_fields("[1, 2, 3]") is None


# --------------------------------------------------------------------------- #
# Image encoding
# --------------------------------------------------------------------------- #


def test_image_data_uri_jpeg(tmp_path):
    img = make_image(tmp_path, "scan.jpg")
    uri = vlm_read._image_data_uri(img)
    assert uri.startswith("data:image/jpeg;base64,")
    payload = uri.split(",", 1)[1]
    assert base64.b64decode(payload) == img.read_bytes()


def test_image_data_uri_png(tmp_path):
    img = make_image(tmp_path, "scan.png")
    assert vlm_read._image_data_uri(img).startswith("data:image/png;base64,")


# A minimal valid 1x1 PNG — real image bytes so litellm's PIL decode path
# actually runs (fake bytes would hit its fallback branch instead).
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9"
    "awAAAABJRU5ErkJggg=="
)


def test_data_uri_survives_real_ollama_image_conversion(tmp_path):
    """Regression for #7: the data URI we build must pass through litellm's REAL
    Ollama image-conversion (which needs Pillow) without raising.

    This is deliberately *not* hermetic — it drives litellm's actual
    `_convert_image` (the code every other test mocks past). Without Pillow
    declared as a dependency it raises `ollama image conversion failed ...`;
    with it, the base64 payload comes back. Guards the transitive runtime dep.
    """
    from litellm.llms.ollama.common_utils import _convert_image

    img = tmp_path / "tiny.png"
    img.write_bytes(_TINY_PNG)
    data_uri = vlm_read._image_data_uri(img)

    result = _convert_image(data_uri)
    assert result and isinstance(result, str)


# --------------------------------------------------------------------------- #
# Ollama model matching
# --------------------------------------------------------------------------- #


def test_ollama_model_name_strips_prefix():
    assert vlm_read._ollama_model_name("ollama/llava") == "llava"
    assert vlm_read._ollama_model_name("ollama_chat/llava:7b") == "llava:7b"


def test_ollama_model_name_none_for_cloud():
    assert vlm_read._ollama_model_name("gpt-4o") is None
    assert vlm_read._ollama_model_name("anthropic/claude-3-5-sonnet") is None


def test_model_present_untagged_matches_latest():
    assert vlm_read._model_present("llava", ["llava:latest", "mistral:latest"])


def test_model_present_exact_tag():
    assert vlm_read._model_present("llava:7b", ["llava:7b"])
    assert not vlm_read._model_present("llava:13b", ["llava:latest"])


def test_model_present_absent():
    assert not vlm_read._model_present("llava", ["mistral:latest"])


# --------------------------------------------------------------------------- #
# main() — happy path
# --------------------------------------------------------------------------- #


def test_main_writes_envelope_with_parsed_fields(tmp_path, monkeypatch, ollama_ok):
    img = make_image(tmp_path)
    root = tmp_path / "output"
    fields = {"patient_name": "Jane Doe", "medications": [{"name": "amoxicillin"}]}
    content = json.dumps(fields)

    rc, calls = run(
        [str(img), "ollama/llava", "--base", str(tmp_path), "--output-root", str(root)],
        monkeypatch,
        content=content,
    )

    assert rc == 0
    dest = root / "sample-data" / "scan.vlm.ollama-llava.json"
    assert dest.exists()
    env = json.loads(dest.read_text())
    assert env["technique"] == "vlm"
    assert env["model"] == "ollama/llava"
    assert env["filename"] == "scan.jpg"
    assert env["fields"] == fields
    assert env["raw_text"] == content
    assert env["duration_sec"] >= 0.0
    assert env["timestamp"]

    # the model string is passed straight through to litellm
    assert len(calls) == 1
    assert calls[0]["model"] == "ollama/llava"
    # the call is pinned to the same Ollama endpoint preflight verified
    assert calls[0]["api_base"] == vlm_read._ollama_base()
    # the image rides along as a data URI in the vision message
    blob = json.dumps(calls[0]["messages"])
    assert "data:image/jpeg;base64," in blob


def test_main_strips_fenced_json(tmp_path, monkeypatch, ollama_ok):
    img = make_image(tmp_path)
    root = tmp_path / "output"
    rc, _ = run(
        [str(img), "ollama/llava", "--base", str(tmp_path), "--output-root", str(root)],
        monkeypatch,
        content='```json\n{"patient_name": "Jane"}\n```',
    )
    assert rc == 0
    dest = root / "sample-data" / "scan.vlm.ollama-llava.json"
    assert json.loads(dest.read_text())["fields"] == {"patient_name": "Jane"}


def test_main_unparseable_falls_back_but_writes(tmp_path, monkeypatch, ollama_ok, capsys):
    img = make_image(tmp_path)
    root = tmp_path / "output"
    prose = "I'm unable to read this prescription clearly."

    rc, _ = run(
        [str(img), "ollama/llava", "--base", str(tmp_path), "--output-root", str(root)],
        monkeypatch,
        content=prose,
    )

    assert rc == 0  # best-effort: never lose the run
    dest = root / "sample-data" / "scan.vlm.ollama-llava.json"
    env = json.loads(dest.read_text())
    assert env["fields"] == {}
    assert env["raw_text"] == prose
    assert "parse" in capsys.readouterr().err.lower()  # warned


# --------------------------------------------------------------------------- #
# main() — error handling
# --------------------------------------------------------------------------- #


def test_main_missing_image_exits_2_without_calling(tmp_path, monkeypatch, capsys):
    def boom(**kwargs):
        raise AssertionError("completion must not be called for a missing image")

    monkeypatch.setattr(vlm_read, "completion", boom)
    rc = vlm_read.main([str(tmp_path / "nope.jpg"), "ollama/llava"])
    assert rc == 2
    assert "not found" in capsys.readouterr().err.lower()


def test_main_cloud_model_stubbed_exits_3(tmp_path, monkeypatch, capsys):
    img = make_image(tmp_path)

    def boom(**kwargs):
        raise AssertionError("no completion for a cloud model yet")

    monkeypatch.setattr(vlm_read, "completion", boom)
    rc = vlm_read.main([str(img), "gpt-4o", "--base", str(tmp_path)])
    assert rc == 3
    err = capsys.readouterr().err.lower()
    assert "ollama" in err and "#5" in err


def test_main_ollama_not_running_exits_3(tmp_path, monkeypatch, capsys):
    img = make_image(tmp_path)

    class FakeURLError(OSError):
        pass

    def raise_conn(*a, **k):
        raise FakeURLError("connection refused")

    # exercise the real _ollama_models -> friendly-error conversion
    monkeypatch.setattr(vlm_read.urllib.request, "urlopen", raise_conn)
    rc = vlm_read.main([str(img), "ollama/llava", "--base", str(tmp_path)])
    assert rc == 3
    assert "serve" in capsys.readouterr().err.lower()


def test_main_model_not_pulled_exits_3(tmp_path, monkeypatch, capsys):
    img = make_image(tmp_path)
    monkeypatch.setattr(vlm_read, "_ollama_models", lambda base: ["mistral:latest"])
    rc = vlm_read.main([str(img), "ollama/llava", "--base", str(tmp_path)])
    assert rc == 3
    assert "pull llava" in capsys.readouterr().err.lower()


def test_main_api_error_exits_1_no_envelope(tmp_path, monkeypatch, ollama_ok, capsys):
    img = make_image(tmp_path)
    root = tmp_path / "output"

    def raise_api(**kwargs):
        raise RuntimeError("model exploded")

    rc, _ = run(
        [str(img), "ollama/llava", "--base", str(tmp_path), "--output-root", str(root)],
        monkeypatch,
        completion=raise_api,
    )
    assert rc == 1
    assert not (root / "sample-data" / "scan.vlm.ollama-llava.json").exists()
    assert capsys.readouterr().err  # some diagnostic


# --------------------------------------------------------------------------- #
# Context window & reasoning capture (issue #9)
#
# The default Ollama context window is tiny; a large image overflows it and the
# model is cut off (finish_reason "length") before answering — yielding an empty
# raw_text. vlm-read must raise num_ctx, warn on truncation, and never drop a
# reasoning-only answer.
# --------------------------------------------------------------------------- #


def full_response(content, reasoning=None, finish_reason="stop"):
    """A litellm-style response carrying finish_reason and reasoning_content."""
    message = SimpleNamespace(content=content, reasoning_content=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


def test_main_passes_default_num_ctx(tmp_path, monkeypatch, ollama_ok):
    img = make_image(tmp_path)
    rc, calls = run(
        [str(img), "ollama/llava", "--base", str(tmp_path), "--output-root", str(tmp_path / "o")],
        monkeypatch,
    )
    assert rc == 0
    # the context window is forwarded to Ollama so image + answer fit
    assert calls[0]["num_ctx"] == vlm_read.DEFAULT_NUM_CTX


def test_main_num_ctx_override(tmp_path, monkeypatch, ollama_ok):
    img = make_image(tmp_path)
    rc, calls = run(
        [
            str(img),
            "ollama/llava",
            "--num-ctx",
            "4096",
            "--base",
            str(tmp_path),
            "--output-root",
            str(tmp_path / "o"),
        ],
        monkeypatch,
    )
    assert rc == 0
    assert calls[0]["num_ctx"] == 4096


def test_main_warns_when_truncated(tmp_path, monkeypatch, ollama_ok, capsys):
    img = make_image(tmp_path)

    def completion(**kwargs):
        return full_response('{"a": 1}', finish_reason="length")

    rc, _ = run(
        [str(img), "ollama/llava", "--base", str(tmp_path), "--output-root", str(tmp_path / "o")],
        monkeypatch,
        completion=completion,
    )
    assert rc == 0
    err = capsys.readouterr().err.lower()
    assert "num_ctx" in err or "truncat" in err  # told the user why/what to do


def test_main_falls_back_to_reasoning_when_content_empty(tmp_path, monkeypatch, ollama_ok, capsys):
    img = make_image(tmp_path)
    root = tmp_path / "o"
    reasoning = '{"patient_name": "Jane"}'

    def completion(**kwargs):
        # A reasoning model that spent its budget thinking: empty content, but the
        # answer is recoverable from reasoning_content.
        return full_response("", reasoning=reasoning, finish_reason="length")

    rc, _ = run(
        [str(img), "ollama/llava", "--base", str(tmp_path), "--output-root", str(root)],
        monkeypatch,
        completion=completion,
    )
    assert rc == 0
    env = json.loads((root / "sample-data" / "scan.vlm.ollama-llava.json").read_text())
    assert env["raw_text"] == reasoning  # nothing lost
    assert env["fields"] == {"patient_name": "Jane"}
    assert "reasoning" in capsys.readouterr().err.lower()  # warned about the fallback

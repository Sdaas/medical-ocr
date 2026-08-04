"""Tests for the `claude-envelope` CLI (F5 / UC-003 / architecture C3).

Claude is a backend *without a script*: it reads the image in-session from the
canonical prompt (`docs/claude-extraction-prompt.md`) and returns one JSON
payload ``{"raw_text": …, "fields": {…}}``. This CLI only *persists* that payload
as a standard ADR-0002 envelope through `common.write_envelope`, so `compare`
treats a Claude run identically to `vlm-read`/`surya-ocr`. It makes **no** LLM or
network call — every test here is fully hermetic.
"""

from __future__ import annotations

import io
import json

import pytest

from medical_ocr import claude_envelope, common

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def make_image(tmp_path, name="scan.jpg"):
    img = tmp_path / "sample-data" / name
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes(b"\xff\xd8\xff fake jpeg bytes")
    return img


def sample_payload(**overrides):
    payload = {
        "raw_text": "Patient: Jane Doe\nRx: amoxicillin 500mg\nSig: 1 tab tid",
        "fields": {
            "patient_name": "Jane Doe",
            "medications": [{"name": "amoxicillin", "dose": "500mg", "frequency": "tid"}],
        },
    }
    payload.update(overrides)
    return payload


def run(argv, monkeypatch, stdin=None):
    """Run main() with an optional stdin payload string; return rc."""
    if stdin is not None:
        monkeypatch.setattr(claude_envelope.sys, "stdin", io.StringIO(stdin))
    return claude_envelope.main(argv)


# write_envelope includes the (sanitized) model segment, exactly like vlm-read's
# `scan.vlm.ollama-llava.json`, so a Claude run with the default model lands at
# `scan.claude.claude-opus-4-8.json`. No Claude special-casing of the path.
DEFAULT_DEST_NAME = "scan.claude.claude-opus-4-8.json"


def load_dest(root, parent="sample-data", name=DEFAULT_DEST_NAME):
    return json.loads((root / parent / name).read_text())


# --------------------------------------------------------------------------- #
# Parser / help
# --------------------------------------------------------------------------- #


def test_parser_prog_and_help_text():
    parser = claude_envelope.build_parser()
    assert parser.prog == "claude-envelope"
    assert parser.description
    assert parser.epilog  # usage examples for --help


# --------------------------------------------------------------------------- #
# Happy path — writes a conformant envelope
# --------------------------------------------------------------------------- #


def test_writes_envelope_from_stdin(tmp_path, monkeypatch, capsys):
    img = make_image(tmp_path)
    root = tmp_path / "output"
    payload = sample_payload()

    rc = run(
        [str(img), "--base", str(tmp_path), "--output-root", str(root)],
        monkeypatch,
        stdin=json.dumps(payload),
    )

    assert rc == 0
    dest = root / "sample-data" / DEFAULT_DEST_NAME
    assert dest.exists()
    # the written path is echoed to stdout
    assert str(dest) in capsys.readouterr().out

    env = load_dest(root)
    assert env["technique"] == "claude"
    assert env["model"] == "claude-opus-4-8"  # Claude is not pure OCR — model is set
    assert env["filename"] == "scan.jpg"
    assert env["raw_text"] == payload["raw_text"]
    assert env["fields"] == payload["fields"]
    assert env["durations"] == {}  # interactive run: no per-call breakdown
    assert env["duration_sec"] == 0.0  # best-effort, omitted-as-0 for an interactive run
    assert env["timestamp"]


def test_writes_envelope_from_file(tmp_path, monkeypatch):
    img = make_image(tmp_path)
    root = tmp_path / "output"
    payload_file = tmp_path / "answer.json"
    payload_file.write_text(json.dumps(sample_payload()))

    rc = run(
        [
            str(img),
            "--from",
            str(payload_file),
            "--base",
            str(tmp_path),
            "--output-root",
            str(root),
        ],
        monkeypatch,
    )

    assert rc == 0
    env = load_dest(root)
    assert env["technique"] == "claude"
    assert env["fields"]["patient_name"] == "Jane Doe"


def test_envelope_key_order_matches_the_shared_contract(tmp_path, monkeypatch):
    """No special-casing in `compare`: the key order must be exactly the shared
    ADR-0002 order that `vlm-read`/`surya-ocr` emit."""
    img = make_image(tmp_path)
    root = tmp_path / "output"

    run(
        [str(img), "--base", str(tmp_path), "--output-root", str(root)],
        monkeypatch,
        stdin=json.dumps(sample_payload()),
    )

    dest = root / "sample-data" / DEFAULT_DEST_NAME
    keys = list(json.loads(dest.read_text()).keys())
    assert keys == list(common._ENVELOPE_ORDER)


def test_envelope_roundtrips_through_common_from_dict(tmp_path, monkeypatch):
    """The worked example must validate via `common.Envelope.from_dict`."""
    img = make_image(tmp_path)
    root = tmp_path / "output"
    payload = sample_payload()

    run(
        [str(img), "--base", str(tmp_path), "--output-root", str(root)],
        monkeypatch,
        stdin=json.dumps(payload),
    )

    data = load_dest(root)
    env = common.Envelope.from_dict(data)
    assert env.technique == "claude"
    assert env.model == "claude-opus-4-8"
    assert env.fields == payload["fields"]
    assert env.raw_text == payload["raw_text"]
    # round-trips cleanly back to the same serialized shape
    assert env.to_dict() == data


def test_written_via_common_output_path(tmp_path, monkeypatch):
    """The envelope lands at exactly `common.output_path`, not a hand-placed path."""
    img = make_image(tmp_path)
    root = tmp_path / "output"

    run(
        [str(img), "--base", str(tmp_path), "--output-root", str(root)],
        monkeypatch,
        stdin=json.dumps(sample_payload()),
    )

    expected = common.output_path(img, "claude", "claude-opus-4-8", base=tmp_path, output_root=root)
    assert expected.exists()


# --------------------------------------------------------------------------- #
# Model resolution
# --------------------------------------------------------------------------- #


def test_model_flag_overrides_payload(tmp_path, monkeypatch):
    img = make_image(tmp_path)
    root = tmp_path / "output"

    run(
        [
            str(img),
            "--model",
            "claude-sonnet-5",
            "--base",
            str(tmp_path),
            "--output-root",
            str(root),
        ],
        monkeypatch,
        stdin=json.dumps(sample_payload(model="claude-opus-4-8")),
    )

    # filename carries the sanitized model too, and the recorded model is the flag
    dest = root / "sample-data" / "scan.claude.claude-sonnet-5.json"
    assert dest.exists()
    assert json.loads(dest.read_text())["model"] == "claude-sonnet-5"


def test_model_from_payload_when_no_flag(tmp_path, monkeypatch):
    img = make_image(tmp_path)
    root = tmp_path / "output"

    run(
        [str(img), "--base", str(tmp_path), "--output-root", str(root)],
        monkeypatch,
        stdin=json.dumps(sample_payload(model="claude-3-7-sonnet")),
    )

    env = load_dest(root, name="scan.claude.claude-3-7-sonnet.json")
    assert env["model"] == "claude-3-7-sonnet"


def test_default_model_when_absent_everywhere(tmp_path, monkeypatch):
    img = make_image(tmp_path)
    root = tmp_path / "output"

    run(
        [str(img), "--base", str(tmp_path), "--output-root", str(root)],
        monkeypatch,
        stdin=json.dumps(sample_payload()),  # no model key, no --model flag
    )

    assert load_dest(root)["model"] == claude_envelope.DEFAULT_MODEL == "claude-opus-4-8"


def test_model_is_never_null(tmp_path, monkeypatch):
    """Claude is not pure OCR (unlike Surya), so `model` must never be null."""
    img = make_image(tmp_path)
    root = tmp_path / "output"

    run(
        [str(img), "--base", str(tmp_path), "--output-root", str(root)],
        monkeypatch,
        stdin=json.dumps(sample_payload()),
    )

    assert load_dest(root)["model"] is not None


# --------------------------------------------------------------------------- #
# `fields` is real parsed JSON, never an escaped blob
# --------------------------------------------------------------------------- #


def test_fields_stays_a_parsed_object(tmp_path, monkeypatch):
    img = make_image(tmp_path)
    root = tmp_path / "output"

    run(
        [str(img), "--base", str(tmp_path), "--output-root", str(root)],
        monkeypatch,
        stdin=json.dumps(sample_payload()),
    )

    env = load_dest(root)
    assert isinstance(env["fields"], dict)  # parsed object, not a string
    assert "raw_json" not in env  # ADR-0002: there is no raw_json field


def test_fields_as_string_is_rejected(tmp_path, monkeypatch, capsys):
    """A fenced/escaped JSON *string* in `fields` is exactly what ADR-0002
    forbids — reject it rather than persist a blob."""
    img = make_image(tmp_path)
    root = tmp_path / "output"

    rc = run(
        [str(img), "--base", str(tmp_path), "--output-root", str(root)],
        monkeypatch,
        stdin=json.dumps({"raw_text": "…", "fields": '```json\n{"a": 1}\n```'}),
    )

    assert rc == 2
    assert not (root / "sample-data" / DEFAULT_DEST_NAME).exists()
    assert "fields" in capsys.readouterr().err.lower()


# --------------------------------------------------------------------------- #
# Error handling
# --------------------------------------------------------------------------- #


def test_missing_image_exits_2(tmp_path, monkeypatch, capsys):
    rc = run(
        [str(tmp_path / "nope.jpg"), "--base", str(tmp_path)],
        monkeypatch,
        stdin=json.dumps(sample_payload()),
    )
    assert rc == 2
    assert "not found" in capsys.readouterr().err.lower()


def test_unparseable_payload_exits_2(tmp_path, monkeypatch, capsys):
    img = make_image(tmp_path)
    rc = run(
        [str(img), "--base", str(tmp_path), "--output-root", str(tmp_path / "o")],
        monkeypatch,
        stdin="this is not json",
    )
    assert rc == 2
    assert "json" in capsys.readouterr().err.lower()


def test_non_object_payload_exits_2(tmp_path, monkeypatch, capsys):
    img = make_image(tmp_path)
    rc = run(
        [str(img), "--base", str(tmp_path), "--output-root", str(tmp_path / "o")],
        monkeypatch,
        stdin=json.dumps([1, 2, 3]),  # valid JSON, but not an object
    )
    assert rc == 2
    assert capsys.readouterr().err  # some diagnostic


@pytest.mark.parametrize(
    "bad, needle",
    [
        ({"duration_sec": "4s"}, "duration_sec"),
        ({"duration_sec": True}, "duration_sec"),  # bool is not a number here
        ({"model": 123}, "model"),
    ],
)
def test_wrong_typed_optional_fields_exit_2(tmp_path, monkeypatch, capsys, bad, needle):
    """A model-generated payload with a mis-typed optional value fails cleanly
    (exit 2) instead of crashing with a traceback at float()/write time."""
    img = make_image(tmp_path)
    root = tmp_path / "output"
    rc = run(
        [str(img), "--base", str(tmp_path), "--output-root", str(root)],
        monkeypatch,
        stdin=json.dumps(sample_payload(**bad)),
    )
    assert rc == 2
    assert needle in capsys.readouterr().err.lower()
    assert not (root / "sample-data" / DEFAULT_DEST_NAME).exists()


# --------------------------------------------------------------------------- #
# Best-effort defaults for an interactive run
# --------------------------------------------------------------------------- #


def test_duration_sec_passthrough_when_provided(tmp_path, monkeypatch):
    img = make_image(tmp_path)
    root = tmp_path / "output"

    run(
        [str(img), "--base", str(tmp_path), "--output-root", str(root)],
        monkeypatch,
        stdin=json.dumps(sample_payload(duration_sec=4.2)),
    )

    assert load_dest(root)["duration_sec"] == 4.2


def test_missing_raw_text_and_fields_default_to_empty(tmp_path, monkeypatch):
    """A perception gap (Claude read nothing) still yields a valid envelope."""
    img = make_image(tmp_path)
    root = tmp_path / "output"

    run(
        [str(img), "--base", str(tmp_path), "--output-root", str(root)],
        monkeypatch,
        stdin=json.dumps({}),  # empty payload object
    )

    env = load_dest(root)
    assert env["raw_text"] == ""
    assert env["fields"] == {}

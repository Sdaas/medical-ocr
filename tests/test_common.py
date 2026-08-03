"""Tests for the `common` foundation (F1).

These pin the contract every backend and `compare` depend on:
the extraction envelope (ADR-0002), the duration timer (C7), the output-file
writer + path convention (C8), and the ground-truth sidecar locate/validate
helpers (ADR-0003). Written test-first, before the implementation exists.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import pytest

from medical_ocr import common

# --------------------------------------------------------------------------- #
# Envelope (C4 / ADR-0002)
# --------------------------------------------------------------------------- #

ENVELOPE_KEYS = {
    "filename",
    "technique",
    "model",
    "duration_sec",
    "durations",
    "timestamp",
    "raw_text",
    "fields",
}


def make_env(**over):
    kwargs = dict(
        filename="rx_001.jpg",
        technique="vlm",
        model="gpt-4o",
        raw_text="Rx: amoxicillin 500mg",
        fields={"patient_name": "Jane Doe"},
    )
    kwargs.update(over)
    return common.Envelope(**kwargs)


def test_envelope_to_dict_has_exact_adr0002_keys():
    d = make_env().to_dict()
    assert set(d) == ENVELOPE_KEYS


def test_envelope_defaults_duration_and_timestamp():
    env = make_env()
    assert env.duration_sec == 0.0
    # per-call durations default to an empty dict (single-call / pure-OCR backends)
    assert env.durations == {}
    # timestamp defaults to a parseable ISO-8601 string
    assert isinstance(env.timestamp, str) and env.timestamp
    datetime.fromisoformat(env.timestamp)  # must not raise


def test_envelope_round_trips():
    env = make_env(duration_sec=3.2)
    assert common.Envelope.from_dict(env.to_dict()) == env


def test_envelope_carries_per_call_durations():
    env = make_env(duration_sec=3.3, durations={"transcribe": 1.2, "extract": 2.1})
    d = env.to_dict()
    assert d["durations"] == {"transcribe": 1.2, "extract": 2.1}
    assert common.Envelope.from_dict(d) == env


def test_envelope_model_may_be_none_for_pure_ocr():
    env = make_env(technique="surya", model=None, fields={})
    d = env.to_dict()
    assert d["model"] is None
    assert common.Envelope.from_dict(d) == env


# --------------------------------------------------------------------------- #
# Timer (C7) — context manager AND decorator
# --------------------------------------------------------------------------- #


def test_timer_context_manager_measures_elapsed():
    with common.Timer() as t:
        time.sleep(0.02)
    assert t.duration_sec >= 0.02


def test_timed_decorator_returns_result_and_duration():
    @common.timed
    def work(x):
        time.sleep(0.01)
        return x * 2

    result, duration = work(21)
    assert result == 42
    assert duration >= 0.01


# --------------------------------------------------------------------------- #
# Output path + writer (C8)
# --------------------------------------------------------------------------- #


# Outputs mirror the image's location under a top-level `output/` tree. Paths
# are computed relative to `base` (the repo root at runtime); tests pin `base`
# explicitly so they don't depend on the process's cwd.


def test_output_path_mirrors_under_output_root():
    p = common.output_path("sample-data/rx_001.jpg", "vlm", "gpt-4o", base=".")
    assert p == Path("output/sample-data/rx_001.vlm.gpt-4o.json")


def test_output_path_omits_model_when_none():
    p = common.output_path("sample-data/rx_001.jpg", "surya", base=".")
    assert p == Path("output/sample-data/rx_001.surya.json")


def test_output_path_sanitizes_slashes_in_model():
    p = common.output_path("sample-data/rx_001.jpg", "vlm", "ollama/llava", base=".")
    assert p == Path("output/sample-data/rx_001.vlm.ollama-llava.json")


def test_output_path_sanitizes_ollama_version_tag():
    # Ollama ids carry a ':' version tag (local-first backend); ':' is not
    # filename-safe on macOS, so it must be sanitized too.
    p = common.output_path("sample-data/rx_001.jpg", "vlm", "ollama/llava:7b", base=".")
    assert p == Path("output/sample-data/rx_001.vlm.ollama-llava-7b.json")


def test_output_path_preserves_multi_dot_stem():
    p = common.output_path("dir/scan.2026.jpg", "vlm", "gpt-4o", base=".")
    assert p == Path("output/dir/scan.2026.vlm.gpt-4o.json")


def test_output_path_handles_image_outside_base(tmp_path):
    # An image outside `base` still lands under output_root with its name intact
    # (no collision, no crash) rather than escaping the tree.
    outside = tmp_path / "elsewhere" / "scan.jpg"
    root = tmp_path / "output"
    p = common.output_path(outside, "vlm", "gpt-4o", base=tmp_path / "other", output_root=root)
    assert p.name == "scan.vlm.gpt-4o.json"
    assert root in p.parents


def test_write_envelope_creates_dirs_and_round_trips(tmp_path):
    img = tmp_path / "sample-data" / "rx_001.jpg"
    img.parent.mkdir()
    img.write_bytes(b"fake")
    env = make_env()
    root = tmp_path / "output"

    written = common.write_envelope(env, img, base=tmp_path, output_root=root)

    assert written == root / "sample-data" / "rx_001.vlm.gpt-4o.json"
    assert written.exists()
    reloaded = json.loads(written.read_text())
    assert reloaded == env.to_dict()


# --------------------------------------------------------------------------- #
# Ground truth (C5 / ADR-0003)
# --------------------------------------------------------------------------- #


def test_truth_path_is_sidecar_next_to_image():
    assert common.truth_path("dir/rx_001.jpg") == Path("dir/rx_001.truth.json")


def test_locate_truth_finds_sidecar(tmp_path):
    img = tmp_path / "rx_001.jpg"
    img.write_bytes(b"fake")
    sidecar = tmp_path / "rx_001.truth.json"
    sidecar.write_text(json.dumps({"fields": {}}))

    assert common.locate_truth(img) == sidecar


def test_locate_truth_returns_none_when_absent(tmp_path):
    img = tmp_path / "rx_001.jpg"
    img.write_bytes(b"fake")
    assert common.locate_truth(img) is None


def test_locate_truth_override_wins(tmp_path):
    img = tmp_path / "rx_001.jpg"
    img.write_bytes(b"fake")
    override = tmp_path / "elsewhere.json"
    override.write_text(json.dumps({"fields": {}}))

    assert common.locate_truth(img, override=override) == override


def test_locate_truth_override_missing_raises(tmp_path):
    img = tmp_path / "rx_001.jpg"
    img.write_bytes(b"fake")
    with pytest.raises(FileNotFoundError):
        common.locate_truth(img, override=tmp_path / "nope.json")


def _write(tmp_path, text):
    p = tmp_path / "rx_001.truth.json"
    p.write_text(text)
    return p


def test_validate_truth_accepts_well_formed(tmp_path):
    p = _write(tmp_path, json.dumps({"fields": {"patient_name": "Jane"}}))
    assert common.validate_truth(p) == {"fields": {"patient_name": "Jane"}}


def test_validate_truth_missing_file_raises(tmp_path):
    with pytest.raises(common.TruthValidationError):
        common.validate_truth(tmp_path / "nope.truth.json")


def test_validate_truth_bad_json_raises(tmp_path):
    p = _write(tmp_path, "{ not valid json ")
    with pytest.raises(common.TruthValidationError):
        common.validate_truth(p)


def test_validate_truth_non_object_raises(tmp_path):
    p = _write(tmp_path, json.dumps([1, 2, 3]))
    with pytest.raises(common.TruthValidationError):
        common.validate_truth(p)


def test_validate_truth_missing_fields_raises(tmp_path):
    p = _write(tmp_path, json.dumps({"patient_name": "Jane"}))
    with pytest.raises(common.TruthValidationError):
        common.validate_truth(p)


def test_validate_truth_fields_not_dict_raises(tmp_path):
    p = _write(tmp_path, json.dumps({"fields": ["a", "b"]}))
    with pytest.raises(common.TruthValidationError):
        common.validate_truth(p)


def test_load_truth_convenience(tmp_path):
    img = tmp_path / "rx_001.jpg"
    img.write_bytes(b"fake")
    (tmp_path / "rx_001.truth.json").write_text(json.dumps({"fields": {"a": 1}}))
    assert common.load_truth(img) == {"fields": {"a": 1}}

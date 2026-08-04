"""Tests for the `claude-extract` CLI (F7 / #20 — one-command Claude backend).

`claude-extract <image>` runs headless `claude -p` with the canonical prompt +
image, parses the `{raw_text, fields}` reply, and hands it to the existing
`claude_envelope` writer — so the output is byte-identical to a `claude-envelope`
run. These tests are hermetic: a **fake `claude`** executable is put on `PATH`, so
no real LLM call is ever made. The real `claude` boundary is exercised once,
un-mocked, at VERIFY (see the retrospective / PR).
"""

from __future__ import annotations

import json
import os
import stat
import subprocess

import pytest

from medical_ocr import claude_extract

# A canonical successful `claude --output-format json` envelope: `.result` holds
# the assistant's text, which is our `{raw_text, fields}` JSON as a string.
GOOD_RESULT = {
    "raw_text": "Patient: Jane Doe\nRx: amoxicillin 500mg",
    "fields": {"patient_name": "Jane Doe", "medications": [{"name": "amoxicillin"}]},
}


def make_image(tmp_path, name="scan.jpg"):
    img = tmp_path / "sample-data" / name
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes(b"\xff\xd8\xff fake jpeg bytes")
    return img


def fake_claude(tmp_path, monkeypatch, *, stdout="", exit_code=0, argv_dump=None, env_dump=None):
    """Install a fake `claude` executable on PATH.

    The fake writes its argv (one per line) to ``argv_dump`` if given, prints
    ``stdout`` verbatim, and exits ``exit_code``. PATH is replaced so the real
    `claude` can never be found.
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    out_file = tmp_path / "claude_stdout.txt"
    out_file.write_text(stdout)

    dump_line = f'printf "%s\\n" "$@" > {argv_dump}\n' if argv_dump else ""
    env_line = f'printf "%s" "${{VIRTUAL_ENV:-<unset>}}" > {env_dump}\n' if env_dump else ""
    script = f"#!/usr/bin/env bash\n{dump_line}{env_line}cat {out_file}\nexit {exit_code}\n"
    claude = bin_dir / "claude"
    claude.write_text(script)
    claude.chmod(claude.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Prepend so the fake shadows any real `claude`, while system tools the fake's
    # shebang needs (bash, cat) still resolve on the inherited PATH.
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    return bin_dir


def outer_json(result, *, is_error=False, duration_ms=1500, subtype="success"):
    """Build a `claude --output-format json` envelope wrapping `result`."""
    inner = result if isinstance(result, str) else json.dumps(result)
    return json.dumps(
        {
            "type": "result",
            "subtype": subtype,
            "is_error": is_error,
            "duration_ms": duration_ms,
            "result": inner,
        }
    )


def load_dest(root, name="scan.claude.claude-opus-4-8.json", parent="sample-data"):
    return json.loads((root / parent / name).read_text())


# --------------------------------------------------------------------------- #
# Parser / help
# --------------------------------------------------------------------------- #


def test_parser_prog_and_help_text():
    parser = claude_extract.build_parser()
    assert parser.prog == "claude-extract"
    assert parser.description
    assert parser.epilog


# --------------------------------------------------------------------------- #
# Happy path — one command produces a conformant envelope
# --------------------------------------------------------------------------- #


def test_extract_writes_conformant_envelope(tmp_path, monkeypatch, capsys):
    img = make_image(tmp_path)
    root = tmp_path / "output"
    fake_claude(tmp_path, monkeypatch, stdout=outer_json(GOOD_RESULT))

    rc = claude_extract.main([str(img), "--base", str(tmp_path), "--output-root", str(root)])

    assert rc == 0
    dest = root / "sample-data" / "scan.claude.claude-opus-4-8.json"
    assert dest.exists()
    assert str(dest) in capsys.readouterr().out

    env = json.loads(dest.read_text())
    assert env["technique"] == "claude"
    assert env["model"] == "claude-opus-4-8"
    assert env["filename"] == "scan.jpg"
    assert env["raw_text"] == GOOD_RESULT["raw_text"]
    assert env["fields"] == GOOD_RESULT["fields"]
    assert env["durations"] == {}


def test_output_is_identical_to_claude_envelope(tmp_path, monkeypatch):
    """claude-extract must delegate to claude_envelope, not reimplement writing:
    the envelope equals what claude_envelope.write_from_payload would produce."""
    from medical_ocr import claude_envelope

    img = make_image(tmp_path)
    root = tmp_path / "output"
    fake_claude(tmp_path, monkeypatch, stdout=outer_json(GOOD_RESULT, duration_ms=0))

    claude_extract.main([str(img), "--base", str(tmp_path), "--output-root", str(root)])
    got = json.loads((root / "sample-data" / "scan.claude.claude-opus-4-8.json").read_text())

    # Build the reference directly through the shared writer.
    ref_root = tmp_path / "ref"
    ref = claude_envelope.write_from_payload(
        img, model="claude-opus-4-8", payload=dict(GOOD_RESULT), base=tmp_path, output_root=ref_root
    )
    want = json.loads(ref.read_text())
    want.pop("timestamp"), got.pop("timestamp")  # only the timestamp differs
    assert got == want


def test_duration_sec_comes_from_claude_wall_clock(tmp_path, monkeypatch):
    img = make_image(tmp_path)
    root = tmp_path / "output"
    fake_claude(tmp_path, monkeypatch, stdout=outer_json(GOOD_RESULT, duration_ms=22789))

    claude_extract.main([str(img), "--base", str(tmp_path), "--output-root", str(root)])
    assert load_dest(root)["duration_sec"] == pytest.approx(22.789)


def test_result_with_fences_is_recovered(tmp_path, monkeypatch):
    """Claude sometimes wraps JSON in a ```json fence — parse it anyway."""
    img = make_image(tmp_path)
    root = tmp_path / "output"
    fenced = "```json\n" + json.dumps(GOOD_RESULT) + "\n```"
    fake_claude(tmp_path, monkeypatch, stdout=outer_json(fenced))

    rc = claude_extract.main([str(img), "--base", str(tmp_path), "--output-root", str(root)])
    assert rc == 0
    assert load_dest(root)["fields"] == GOOD_RESULT["fields"]


def test_result_with_trailing_sentinel_is_recovered(tmp_path, monkeypatch):
    """VERIFY regression: headless Claude inherits the user's global end-of-turn
    sentinel, so the reply is `{...valid json...}\\n\\n<!-- CC:DONE -->`. The
    trailing content must not break parsing."""
    img = make_image(tmp_path)
    root = tmp_path / "output"
    noisy = json.dumps(GOOD_RESULT) + "\n\n<!-- CC:DONE -->"
    fake_claude(tmp_path, monkeypatch, stdout=outer_json(noisy))

    rc = claude_extract.main([str(img), "--base", str(tmp_path), "--output-root", str(root)])
    assert rc == 0
    assert load_dest(root)["fields"] == GOOD_RESULT["fields"]


def test_result_with_leading_prose_is_recovered(tmp_path, monkeypatch):
    """A stray preamble before the JSON (with its own braces) must not fool the
    parser — it scans for the first *complete* JSON object."""
    img = make_image(tmp_path)
    root = tmp_path / "output"
    noisy = "Here is the data (note the {a+b} shorthand):\n" + json.dumps(GOOD_RESULT)
    fake_claude(tmp_path, monkeypatch, stdout=outer_json(noisy))

    rc = claude_extract.main([str(img), "--base", str(tmp_path), "--output-root", str(root)])
    assert rc == 0
    assert load_dest(root)["fields"] == GOOD_RESULT["fields"]


# --------------------------------------------------------------------------- #
# The `claude` invocation contract (argv)
# --------------------------------------------------------------------------- #


def test_invokes_claude_with_expected_argv(tmp_path, monkeypatch):
    img = make_image(tmp_path)
    root = tmp_path / "output"
    dump = tmp_path / "argv.txt"
    fake_claude(tmp_path, monkeypatch, stdout=outer_json(GOOD_RESULT), argv_dump=dump)

    claude_extract.main(
        [
            str(img),
            "--model",
            "claude-sonnet-5",
            "--base",
            str(tmp_path),
            "--output-root",
            str(root),
        ]
    )

    argv = dump.read_text().splitlines()
    assert "-p" in argv
    assert "--output-format" in argv and argv[argv.index("--output-format") + 1] == "json"
    assert "--model" in argv and argv[argv.index("--model") + 1] == "claude-sonnet-5"
    # the Read tool is allowed (headless needs it to open the image) ...
    assert "--allowedTools" in argv and "Read" in argv
    # ... and the absolute image path is handed to claude (in the prompt and --add-dir)
    assert any(str(img.resolve()) in a for a in argv)
    assert "--add-dir" in argv and str(img.resolve().parent) in argv


def test_child_env_strips_our_venv(monkeypatch):
    """VERIFY regression: our venv must not leak onto the spawned claude, or the
    user's hooks would resolve `python3` to .venv (breaking hooks that need packages
    absent there). Drop VIRTUAL_ENV and remove its bin from PATH."""
    monkeypatch.setenv("VIRTUAL_ENV", "/proj/.venv")
    monkeypatch.setenv("PATH", os.pathsep.join(["/proj/.venv/bin", "/usr/bin", "/bin"]))
    env = claude_extract._child_env()
    assert "VIRTUAL_ENV" not in env
    assert env["PATH"].split(os.pathsep) == ["/usr/bin", "/bin"]


def test_child_env_noop_without_venv(monkeypatch):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join(["/usr/bin", "/bin"]))
    env = claude_extract._child_env()
    assert env["PATH"] == os.pathsep.join(["/usr/bin", "/bin"])


def test_spawned_claude_gets_scrubbed_env(tmp_path, monkeypatch):
    """End-to-end: the fake claude sees VIRTUAL_ENV unset even though the caller
    ran inside a venv."""
    img = make_image(tmp_path)
    root = tmp_path / "output"
    env_dump = tmp_path / "child_venv.txt"
    fake_claude(tmp_path, monkeypatch, stdout=outer_json(GOOD_RESULT), env_dump=env_dump)
    # fake_claude set PATH; now pretend we're inside a venv too.
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / ".venv"))

    rc = claude_extract.main([str(img), "--base", str(tmp_path), "--output-root", str(root)])
    assert rc == 0
    assert env_dump.read_text() == "<unset>"


def test_model_recorded_matches_flag(tmp_path, monkeypatch):
    img = make_image(tmp_path)
    root = tmp_path / "output"
    fake_claude(tmp_path, monkeypatch, stdout=outer_json(GOOD_RESULT))

    claude_extract.main(
        [
            str(img),
            "--model",
            "claude-sonnet-5",
            "--base",
            str(tmp_path),
            "--output-root",
            str(root),
        ]
    )
    env = load_dest(root, name="scan.claude.claude-sonnet-5.json")
    assert env["model"] == "claude-sonnet-5"


# --------------------------------------------------------------------------- #
# Error handling
# --------------------------------------------------------------------------- #


def test_missing_image_exits_2_without_calling_claude(tmp_path, monkeypatch):
    # Point claude at an absent binary: if the code reached the call it would be a
    # code-3 precondition, not code 2 — so code 2 proves the image check ran first.
    monkeypatch.setattr(claude_extract, "CLAUDE_BIN", str(tmp_path / "no-such-claude"))
    rc = claude_extract.main([str(tmp_path / "nope.jpg"), "--base", str(tmp_path)])
    assert rc == 2


def test_claude_not_on_path_exits_3(tmp_path, monkeypatch, capsys):
    img = make_image(tmp_path)
    monkeypatch.setattr(claude_extract, "CLAUDE_BIN", str(tmp_path / "no-such-claude"))
    rc = claude_extract.main([str(img), "--base", str(tmp_path)])
    assert rc == 3
    assert "claude" in capsys.readouterr().err.lower()


def test_claude_nonzero_exit_is_surfaced_exit_1(tmp_path, monkeypatch, capsys):
    img = make_image(tmp_path)
    root = tmp_path / "output"
    fake_claude(tmp_path, monkeypatch, stdout="boom on stderr side", exit_code=2)
    rc = claude_extract.main([str(img), "--base", str(tmp_path), "--output-root", str(root)])
    assert rc == 1
    assert not (root / "sample-data" / "scan.claude.claude-opus-4-8.json").exists()
    assert capsys.readouterr().err


def test_claude_is_error_result_exits_1(tmp_path, monkeypatch, capsys):
    img = make_image(tmp_path)
    root = tmp_path / "output"
    fake_claude(
        tmp_path, monkeypatch, stdout=outer_json("model failed", is_error=True, subtype="error")
    )
    rc = claude_extract.main([str(img), "--base", str(tmp_path), "--output-root", str(root)])
    assert rc == 1
    assert capsys.readouterr().err


def test_claude_non_json_stdout_exits_1(tmp_path, monkeypatch, capsys):
    img = make_image(tmp_path)
    root = tmp_path / "output"
    fake_claude(tmp_path, monkeypatch, stdout="I am not JSON at all")
    rc = claude_extract.main([str(img), "--base", str(tmp_path), "--output-root", str(root)])
    assert rc == 1
    assert capsys.readouterr().err


def test_result_not_a_fields_object_exits_1(tmp_path, monkeypatch, capsys):
    """The wrapper parses, but `.result` isn't the expected {raw_text, fields}."""
    img = make_image(tmp_path)
    root = tmp_path / "output"
    fake_claude(tmp_path, monkeypatch, stdout=outer_json("Sorry, I can't read this image."))
    rc = claude_extract.main([str(img), "--base", str(tmp_path), "--output-root", str(root)])
    assert rc == 1
    assert not (root / "sample-data" / "scan.claude.claude-opus-4-8.json").exists()
    assert capsys.readouterr().err


def test_result_object_with_bad_fields_exits_1(tmp_path, monkeypatch, capsys):
    """The reply parses to an object, but `fields` is a string — the shared writer
    rejects it (ADR-0002); main() surfaces that as a clean exit 1, not a crash."""
    img = make_image(tmp_path)
    root = tmp_path / "output"
    bad = {"raw_text": "x", "fields": "```json {} ```"}
    fake_claude(tmp_path, monkeypatch, stdout=outer_json(bad))
    rc = claude_extract.main([str(img), "--base", str(tmp_path), "--output-root", str(root)])
    assert rc == 1
    assert not (root / "sample-data" / "scan.claude.claude-opus-4-8.json").exists()
    assert "fields" in capsys.readouterr().err.lower()


def test_claude_timeout_exits_1(tmp_path, monkeypatch, capsys):
    img = make_image(tmp_path)

    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=claude_extract.CLAUDE_TIMEOUT_SEC)

    monkeypatch.setattr(claude_extract.subprocess, "run", boom)
    rc = claude_extract.main([str(img), "--base", str(tmp_path)])
    assert rc == 1
    assert "did not respond" in capsys.readouterr().err.lower()


@pytest.mark.skipif(os.name == "nt", reason="fake claude uses a bash shebang")
def test_uses_argv_not_shell(tmp_path, monkeypatch):
    """A shell-metachar-laden image name must not be interpreted by a shell —
    argv invocation keeps it literal (no injection)."""
    img = make_image(tmp_path, name="a b;echo pwned.jpg")
    root = tmp_path / "output"
    dump = tmp_path / "argv.txt"
    fake_claude(tmp_path, monkeypatch, stdout=outer_json(GOOD_RESULT), argv_dump=dump)

    rc = claude_extract.main([str(img), "--base", str(tmp_path), "--output-root", str(root)])
    assert rc == 0
    # the whole path survived as one literal argument fragment somewhere in argv
    assert any("a b;echo pwned.jpg" in line for line in dump.read_text().splitlines())

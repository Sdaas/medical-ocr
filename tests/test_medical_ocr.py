"""Tests for medical-ocr."""

from medical_ocr.cli import build_parser, main


def test_parser_builds():
    parser = build_parser()
    assert parser.prog == "medical-ocr"


def test_main_runs(capsys):
    rc = main([])
    captured = capsys.readouterr()
    assert rc == 0
    assert "medical-ocr" in captured.out


def test_verbose_flag(capsys):
    rc = main(["--verbose"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "verbose" in captured.err

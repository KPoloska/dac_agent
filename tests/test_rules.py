from pathlib import Path

from daisy.rules import load_rules


def test_load_rules_defaults_if_missing():
    r = load_rules(Path("this_file_should_not_exist_12345.yaml"))
    assert r.pdf_evidence.min_text_chars >= 0
    assert len(r.pdf_evidence.required_files) >= 1


def test_load_rules_from_config():
    r = load_rules(Path("config/rules.yaml"))
    assert "Chapter1.pdf" in r.pdf_evidence.required_files
    assert isinstance(r.pdf_evidence.min_text_chars, int)

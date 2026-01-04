from __future__ import annotations

from daisy.util import extract_yes_no
from daisy.agent import _extract_yes_no_near, _extract_value_from_text


def test_extract_yes_no_basic():
    assert extract_yes_no("yes") == "yes"
    assert extract_yes_no("no") == "no"
    assert extract_yes_no("Y") == "yes"
    assert extract_yes_no("n") == "no"


def test_extract_yes_no_with_punct():
    assert extract_yes_no("relevant? y") == "yes"
    assert extract_yes_no("Answer: No,") == "no"
    assert extract_yes_no("   YES.") == "yes"


def test_extract_value_from_text_same_line():
    t = "CMS Product ID 1513344\nIT Asset ID: AID551\nIT Asset Name: MICROSOFT OFFICE 365\n"
    assert _extract_value_from_text(t, ["CMS Product ID"]) == "1513344"
    assert _extract_value_from_text(t, ["IT Asset ID", "IT Asset ID:"]) == "AID551"
    assert _extract_value_from_text(t, ["IT Asset Name", "IT Asset Name:"]) == "MICROSOFT OFFICE 365"


def test_extract_yes_no_near_label():
    t = "Functional Area relevant? y\nDo you want to upload the entitlement composition? n\n"
    assert _extract_yes_no_near(t, [r"Functional\s+Area.*relevant"]) == "yes"
    assert _extract_yes_no_near(t, [r"upload\s+the\s+entitlement\s+composition"]) == "no"

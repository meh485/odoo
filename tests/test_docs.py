"""The brief names the topics DESIGN.md must cover, so the document is tested
like anything else rather than trusted to stay complete.
"""
import re
from pathlib import Path

DESIGN = Path(__file__).resolve().parents[1] / "DESIGN.md"

REQUIRED_SECTIONS = [
    "Security hardening",
    "Backup",
    "Observability",
    "Silent failures",
    "Scaling",
    "Trade-offs",
]


def test_design_covers_every_topic_the_brief_names():
    text = DESIGN.read_text().lower()
    for section in REQUIRED_SECTIONS:
        assert section.lower() in text, f"DESIGN.md does not cover {section}"


def test_design_states_the_numbers_for_five_hundred_tenants():
    assert "500" in DESIGN.read_text()


def test_design_names_what_it_does_not_do():
    text = DESIGN.read_text().lower()
    assert "limit" in text or "would do next" in text


def test_no_secret_material_in_documentation():
    assert not re.search(r"BEGIN (RSA|OPENSSH|PRIVATE) KEY", DESIGN.read_text())
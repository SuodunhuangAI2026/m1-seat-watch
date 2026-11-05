"""P1 测试：条款差异。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import diff  # noqa: E402

OLD = """5.2 Head restraints
5.2.1 The head restraint shall be at least 700 mm above the seat.
5.2.3 The height shall be measured with the manikin in position.
6.1 Static test
6.1.1 Apply a force of 500 N within 5 s.
"""

NEW = """5.2 Head restraints
5.2.1 The head restraint shall be at least 720 mm above the seat.
5.2.3 The height shall be measured with the manikin in position.
5.2.4 A rearward displacement of not more than 102 mm is allowed.
6.1 Static test
6.1.1 Apply a force of 500 N within 5 s.
"""


def test_clause_split():
    clauses = diff.to_clauses(OLD)
    assert "5.2" in clauses and "6.1.1" in clauses
    assert "(前言)" not in clauses


def test_modified_detected():
    changes = diff.diff(OLD, NEW)
    modified = [c for c in changes if c["kind"] == "modified"]
    assert len(modified) == 1
    assert modified[0]["clause"] == "5.2.1"
    assert "700" in modified[0]["old"] and "720" in modified[0]["new"]


def test_added_detected():
    changes = diff.diff(OLD, NEW)
    added = [c for c in changes if c["kind"] == "added"]
    assert [c["clause"] for c in added] == ["5.2.4"]


def test_no_change_is_empty():
    assert diff.diff(OLD, OLD) == []


def test_removed_detected():
    changes = diff.diff(NEW, OLD)
    removed = [c for c in changes if c["kind"] == "removed"]
    assert [c["clause"] for c in removed] == ["5.2.4"]


def test_summary_counts():
    s = diff.summarize(diff.diff(OLD, NEW))
    assert s["total"] == 2
    assert s["counts"] == {"added": 1, "removed": 0, "modified": 1}


def test_whitespace_only_change_ignored():
    bumped = OLD.replace("position.", "position.   ")
    assert diff.diff(OLD, bumped) == []

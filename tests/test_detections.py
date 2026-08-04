"""The pair is the unit: every flag fixture must fire its own kind, and its
near-identical clean twin must produce no findings at all. A detector that
flags everything passes the first half and fails the second."""

from pathlib import Path

import pytest

from tampercheck.engine import analyze

FIXTURES = Path(__file__).parent / "fixtures"

DETECTION_DIRS = sorted(
    d for d in FIXTURES.iterdir()
    if d.is_dir() and d.name not in ("allow", "error")
)

FLAG_CASES = sorted(p for d in DETECTION_DIRS for p in d.glob("*-flag.diff"))
CLEAN_CASES = sorted(p for d in DETECTION_DIRS for p in d.glob("*-clean.diff"))


def test_every_detection_has_fixtures():
    kinds = {d.name for d in DETECTION_DIRS}
    assert kinds == {
        "test-deleted", "test-focused", "unconditional-success",
        "test-skipped", "test-filtered", "assertion-weakened",
        "swallowed-error", "placeholder",
    }
    for d in DETECTION_DIRS:
        flags = list(d.glob("*-flag.diff"))
        cleans = list(d.glob("*-clean.diff"))
        assert flags, f"{d.name}: no flag fixture"
        assert len(flags) == len(cleans), f"{d.name}: unpaired fixtures"


@pytest.mark.parametrize("path", FLAG_CASES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_flag_fixture_fires_its_kind(path: Path):
    expected_kind = path.parent.name
    findings = analyze(path.read_text(encoding="utf-8"))
    kinds = {f.kind for f in findings if not f.allowed}
    assert expected_kind in kinds, (
        f"{path.name} did not produce a {expected_kind} finding "
        f"(got: {sorted(kinds) or 'nothing'})"
    )


@pytest.mark.parametrize("path", CLEAN_CASES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_clean_fixture_stays_clean(path: Path):
    findings = analyze(path.read_text(encoding="utf-8"))
    assert findings == [], (
        f"{path.name} should be clean but produced: "
        f"{[(f.kind, f.path, f.line) for f in findings]}"
    )


def test_allow_marker_suppresses_adjacent_finding():
    diff = (FIXTURES / "allow" / "js-skip-allowed.diff").read_text(encoding="utf-8")
    findings = analyze(diff)
    skipped = [f for f in findings if f.kind == "test-skipped"]
    assert skipped and all(f.allowed for f in skipped)
    assert "flaky" in skipped[0].reason


def test_allow_marker_covers_named_test_deletion():
    diff = (FIXTURES / "allow" / "python-deletion-allowed.diff").read_text(encoding="utf-8")
    findings = analyze(diff)
    deleted = [f for f in findings if f.kind == "test-deleted"]
    assert deleted and all(f.allowed for f in deleted)
    assert "test_user.py" in deleted[0].reason


def test_unrelated_allow_marker_does_not_cover_deletion():
    diff = (FIXTURES / "allow" / "python-deletion-allowed.diff").read_text(encoding="utf-8")
    diff = diff.replace("allow test_user.py superseded", "allow something else entirely")
    findings = analyze(diff)
    deleted = [f for f in findings if f.kind == "test-deleted"]
    assert deleted and not any(f.allowed for f in deleted)


def test_findings_only_fire_on_added_lines():
    # The same tampering REMOVED by a change must not fire: removing
    # `|| true` is a strengthening, not a weakening.
    diff = (
        "diff --git a/scripts/run_tests.sh b/scripts/run_tests.sh\n"
        "index 1234567..89abcde 100644\n"
        "--- a/scripts/run_tests.sh\n"
        "+++ b/scripts/run_tests.sh\n"
        "@@ -1,2 +1,2 @@\n"
        " #!/bin/sh\n"
        "-pytest tests/ || true\n"
        "+pytest tests/\n"
    )
    assert analyze(diff) == []

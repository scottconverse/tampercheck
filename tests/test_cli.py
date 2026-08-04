"""CLI contract tests, run through the real console entry point.

The most important one: exit code 2 (tool failure) is provably distinct from
exit code 1 (findings). A crashed tool must never look like a clean result —
or like a finding."""

import json
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def run_cli(*args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tampercheck.cli", *args],
        input=stdin, capture_output=True, text=True, encoding="utf-8",
    )


def test_empty_diff_is_clean_exit_0():
    proc = run_cli(stdin="")
    assert proc.returncode == 0


def test_flag_fixture_exits_1():
    diff = (FIXTURES / "test-focused" / "js-flag.diff").read_text()
    proc = run_cli(stdin=diff)
    assert proc.returncode == 1
    assert "test-focused" in proc.stdout


def test_garbage_input_exits_2_not_1_not_0():
    proc = run_cli(stdin=(FIXTURES / "error" / "not-a-diff.txt").read_text())
    assert proc.returncode == 2
    assert "tampercheck error" in proc.stderr


def test_truncated_hunk_exits_2():
    proc = run_cli(stdin=(FIXTURES / "error" / "truncated-hunk.diff").read_text())
    assert proc.returncode == 2


def test_git_failure_exits_2():
    proc = run_cli("--from", "no-such-ref-xyz", "--to", "also-missing")
    assert proc.returncode == 2


def test_min_severity_gates_exit_code():
    diff = (FIXTURES / "placeholder" / "python-flag.diff").read_text()
    assert run_cli(stdin=diff).returncode == 0            # medium < high default
    assert run_cli("--min-severity", "medium", stdin=diff).returncode == 1
    high = (FIXTURES / "test-skipped" / "python-flag.diff").read_text()
    assert run_cli("--min-severity", "critical", stdin=high).returncode == 0


def test_allowed_finding_does_not_gate():
    diff = (FIXTURES / "allow" / "js-skip-allowed.diff").read_text()
    proc = run_cli(stdin=diff)
    assert proc.returncode == 0
    assert "ALLOWED" in proc.stdout


def test_json_schema_stable():
    diff = (FIXTURES / "unconditional-success" / "shell-flag.diff").read_text()
    proc = run_cli("--json", stdin=diff)
    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert data["schema"] == 1
    assert data["tool"] == "tampercheck"
    assert set(data["counts"]) == {"critical", "high", "medium"}
    f = data["findings"][0]
    assert set(f) == {"kind", "severity", "path", "line", "evidence",
                      "rationale", "allowed", "reason"}
    assert f["kind"] == "unconditional-success"


def test_version_flag():
    proc = run_cli("--version")
    assert proc.returncode == 0

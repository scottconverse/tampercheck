"""Command-line interface.

Exit codes — the contract:
    0  nothing found at or above the failure threshold
    1  findings at or above the threshold
    2  the tool itself failed (bad input, git error, unreadable diff)

2 is never conflated with 1: a crashed tool must not look like a clean result.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from . import __version__
from .engine import Finding, analyze, worst_severity
from .patterns import SEVERITY_ORDER


def _read_diff(args: argparse.Namespace) -> str:
    if args.pr is not None:
        proc = subprocess.run(
            ["gh", "pr", "diff", str(args.pr)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0:
            raise RuntimeError(f"gh pr diff failed: {proc.stderr.strip()}")
        return proc.stdout
    if args.from_ref is not None:
        cmd = ["git", "diff", "--no-color", "--no-ext-diff", "--find-renames",
               args.from_ref, args.to_ref]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if proc.returncode not in (0, 1):
            raise RuntimeError(f"git diff failed: {proc.stderr.strip()}")
        return proc.stdout
    if sys.stdin.isatty():
        raise RuntimeError(
            "no diff on stdin and no --from/--pr given "
            "(usage: git diff | tampercheck)"
        )
    return sys.stdin.read()


def _human_report(findings: list[Finding], threshold: str) -> str:
    lines: list[str] = []
    live = [f for f in findings if not f.allowed]
    allowed = [f for f in findings if f.allowed]
    for f in live:
        where = f"{f.path}:{f.line}" if f.line else f.path
        lines.append(f"{f.severity.upper():8s} {f.kind}  {where}")
        lines.append(f"         {f.evidence}")
        lines.append(f"         why it matters: {f.rationale}")
    for f in allowed:
        where = f"{f.path}:{f.line}" if f.line else f.path
        lines.append(f"ALLOWED  {f.kind}  {where}  justified: {f.reason}")
    gating = [f for f in live if SEVERITY_ORDER[f.severity] >= SEVERITY_ORDER[threshold]]
    if not findings:
        lines.append("tampercheck: clean - this change does not weaken verification.")
    else:
        lines.append(
            f"tampercheck: {len(live)} finding(s) "
            f"({len(gating)} at or above --min-severity {threshold}), "
            f"{len(allowed)} allowed by inline justification."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tampercheck",
        description="Reads a code change and reports whether it weakened the "
                    "project's own verification (tests, assertions, checks).",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--from", dest="from_ref", metavar="REF",
                        help="diff from this git ref (runs git itself)")
    parser.add_argument("--to", dest="to_ref", metavar="REF", default="HEAD",
                        help="diff to this git ref (default: HEAD)")
    parser.add_argument("--pr", type=int, metavar="N",
                        help="diff of GitHub PR #N via the gh CLI")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output")
    parser.add_argument("--min-severity", choices=("critical", "high", "medium"),
                        default="high",
                        help="lowest severity that causes exit code 1 "
                             "(default: high)")
    args = parser.parse_args(argv)

    try:
        diff_text = _read_diff(args)
        findings = analyze(diff_text)
    except Exception as exc:  # noqa: BLE001 — anything here is a tool failure
        print(f"tampercheck error: {exc}", file=sys.stderr)
        return 2

    threshold = args.min_severity
    live = [f for f in findings if not f.allowed]
    gating = [f for f in live
              if SEVERITY_ORDER[f.severity] >= SEVERITY_ORDER[threshold]]

    if args.json:
        print(json.dumps({
            "schema": 1,
            "tool": "tampercheck",
            "version": __version__,
            "min_severity": threshold,
            "counts": {
                sev: sum(1 for f in live if f.severity == sev)
                for sev in ("critical", "high", "medium")
            },
            "allowed": len(findings) - len(live),
            "findings": [f.to_dict() for f in findings],
        }, indent=2))
    else:
        print(_human_report(findings, threshold))

    return 1 if gating else 0


if __name__ == "__main__":
    sys.exit(main())

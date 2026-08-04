"""False-positive corpus runner.

Runs the analyzer across real historical commits of one or more repositories.
Almost all ordinary commits should come back clean; the false-positive rate
is reported as a number. If ordinary history lights the tool up, the patterns
are wrong and must be tightened before shipping.

Usage: python scripts/corpus.py <repo-path> [<repo-path> ...] [--limit N]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tampercheck.engine import analyze  # noqa: E402
from tampercheck.patterns import SEVERITY_ORDER  # noqa: E402


def commits(repo: str, limit: int) -> list[str]:
    out = subprocess.run(
        ["git", "-C", repo, "log", "--no-merges", f"--max-count={limit}",
         "--format=%H"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.split()


def show(repo: str, sha: str) -> str:
    out = subprocess.run(
        ["git", "-C", repo, "show", "--format=", "--no-color", "-M", sha],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return out.stdout if out.returncode == 0 else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repos", nargs="+")
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--show-samples", type=int, default=3,
                    help="sample findings to print per kind")
    args = ap.parse_args()

    total = 0
    errored = 0
    commits_with_any = 0
    commits_with_gating = 0     # findings at >= high, the default gate
    by_kind: Counter[str] = Counter()
    samples: dict[str, list[str]] = {}

    for repo in args.repos:
        name = Path(repo).name
        shas = commits(repo, args.limit)
        print(f"[{name}] scanning {len(shas)} commits ...", flush=True)
        for sha in shas:
            diff = show(repo, sha)
            total += 1
            try:
                findings = [f for f in analyze(diff) if not f.allowed]
            except Exception:
                errored += 1
                continue
            if findings:
                commits_with_any += 1
            if any(SEVERITY_ORDER[f.severity] >= SEVERITY_ORDER["high"]
                   for f in findings):
                commits_with_gating += 1
            for f in findings:
                by_kind[f.kind] += 1
                samples.setdefault(f.kind, [])
                if len(samples[f.kind]) < args.show_samples:
                    samples[f.kind].append(
                        f"{name}@{sha[:8]} {f.path}:{f.line} {f.evidence[:100]}"
                    )

    print()
    print(f"commits scanned:            {total}")
    print(f"unparseable (skipped):      {errored}")
    print(f"commits with any finding:   {commits_with_any} "
          f"({100 * commits_with_any / total:.1f}%)")
    print(f"commits gating at >=high:   {commits_with_gating} "
          f"({100 * commits_with_gating / total:.1f}%)  <-- the FP rate that matters")
    print()
    print("findings by kind:")
    for kind, n in by_kind.most_common():
        print(f"  {kind:24s} {n}")
        for s in samples.get(kind, []):
            print(f"      e.g. {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

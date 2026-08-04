"""Mutation proof, run in CI: demonstrate every detector observably firing.

For each detection kind, in each language with a fixture pair: feed the
violating diff to the REAL CLI and require exit 1 with that specific kind in
the JSON findings; feed the near-identical clean diff and require exit 0.
A detector that has never been observed going red is not proven to work.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def run(diff_path: Path) -> tuple[int, dict | None]:
    proc = subprocess.run(
        [sys.executable, "-m", "tampercheck.cli", "--json",
         "--min-severity", "medium"],
        input=diff_path.read_text(encoding="utf-8"),
        capture_output=True, text=True, encoding="utf-8",
    )
    data = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc.returncode, data


def main() -> int:
    failures: list[str] = []
    rows: list[str] = []
    kinds_proven: set[str] = set()

    for kind_dir in sorted(d for d in FIXTURES.iterdir() if d.is_dir()):
        if kind_dir.name in ("allow", "error"):
            continue
        kind = kind_dir.name
        for flag in sorted(kind_dir.glob("*-flag.diff")):
            lang = flag.stem.removesuffix("-flag")
            clean = kind_dir / f"{lang}-clean.diff"

            code, data = run(flag)
            fired = data is not None and any(
                f["kind"] == kind and not f["allowed"] for f in data["findings"]
            )
            red_ok = code == 1 and fired

            clean_code, _ = run(clean)
            green_ok = clean_code == 0

            status = "RED->GREEN ok" if (red_ok and green_ok) else "FAILED"
            rows.append(f"  {kind:24s} {lang:8s} {status}")
            if not red_ok:
                failures.append(f"{kind}/{lang}: flag fixture exit={code}, "
                                f"kind-fired={fired} (expected exit 1 + kind)")
            if not green_ok:
                failures.append(f"{kind}/{lang}: clean fixture exit={clean_code} "
                                f"(expected 0)")
            if red_ok and green_ok:
                kinds_proven.add(kind)

    print("mutation proof: every detector observed going red, then green:")
    print("\n".join(rows))

    expected = {"test-deleted", "test-focused", "unconditional-success",
                "test-skipped", "test-filtered", "assertion-weakened",
                "swallowed-error", "placeholder"}
    missing = expected - kinds_proven
    if missing:
        failures.append(f"kinds never proven red: {sorted(missing)}")

    if failures:
        print("\nMUTATION PROOF FAILED:")
        print("\n".join(f"  - {f}" for f in failures))
        return 1
    print(f"\nall {len(kinds_proven)} detection kinds proven. exit-code contract intact.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

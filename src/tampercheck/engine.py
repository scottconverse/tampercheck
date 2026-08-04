"""Detection engine: runs the pattern table over a unified diff.

Everything fires on lines the change ADDED (or, for test-deleted /
assertion-weakened, on what the change removed). Pre-existing conditions in
the repository are never reported.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import unidiff

from .patterns import (
    ALLOW_RE,
    ASSERTION_RE,
    NOQA_ACK_RE,
    RULES,
    SEVERITY_ORDER,
    TRIVIAL_ASSERTION_RE,
    is_test_file,
    language_of,
)

CI_PATH_HINT = ("/.github/workflows/", "/.gitlab-ci", "/ci/", "azure-pipelines")


@dataclass
class Finding:
    kind: str
    severity: str
    path: str
    line: int | None       # target-file line number; None for file-level findings
    evidence: str
    rationale: str
    allowed: bool = False  # suppressed by an inline `tampercheck: allow` marker
    reason: str = ""       # the justification text, when allowed

    def to_dict(self) -> dict:
        return asdict(self)


def _compact(text: str) -> str:
    value = " ".join(text.strip().split())
    return value if len(value) <= 200 else value[:197] + "..."


def _is_ci_file(path: str) -> bool:
    p = "/" + path.replace("\\", "/").lower()
    return any(hint in p for hint in CI_PATH_HINT)


def _scope_matches(rule_scope: str, is_test: bool, is_ci: bool) -> bool:
    if rule_scope == "any":
        return True
    if rule_scope == "test":
        return is_test
    return is_ci  # "ci"


def _allow_marker(lines: list[str]) -> str | None:
    """Return the justification text if any of the lines carries the marker."""
    for text in lines:
        m = ALLOW_RE.search(text)
        if m:
            return m.group("reason").strip() or "(no reason given)"
    return None


def analyze(diff_text: str) -> list[Finding]:
    """Run every detection over one unified diff. Raises on unparseable input."""
    patch = unidiff.PatchSet(diff_text)
    # unidiff silently yields an empty patch for arbitrary text. Unreadable
    # input must be a tool error (exit 2), never a clean result.
    if len(patch) == 0 and diff_text.strip():
        if not any(line.startswith(("diff ", "--- ", "Index: "))
                   for line in diff_text.splitlines()):
            raise ValueError("input does not look like a unified diff")
    findings: list[Finding] = []

    for pfile in patch:
        path = (pfile.source_file if pfile.is_removed_file else pfile.target_file)
        for prefix in ("a/", "b/"):
            if path.startswith(prefix):
                path = path[len(prefix):]
        lang = language_of(path)
        if lang is None:
            continue
        is_test = is_test_file(path)
        is_ci = _is_ci_file(path) or lang == "yaml" and "/workflows/" in "/" + path.replace("\\", "/")

        # 1. test-deleted — file-level, critical. A deleted file has no added
        # lines to carry the allow marker, so the justification may live on any
        # added line elsewhere in the diff, as long as it names the file.
        if pfile.is_removed_file and is_test:
            basename = path.replace("\\", "/").rsplit("/", 1)[-1]
            reason = None
            for other in patch:
                for hunk in other:
                    for line in hunk:
                        if not line.is_added:
                            continue
                        m = ALLOW_RE.search(line.value)
                        if m and basename in m.group("reason"):
                            reason = m.group("reason").strip()
                            break
            findings.append(Finding(
                kind="test-deleted", severity="critical", path=path, line=None,
                evidence="test file deleted",
                rationale="Deleting a test removes its coverage entirely; a "
                          "green run afterwards proves less than it did before. "
                          "To justify a legitimate deletion, add a comment on "
                          "any added line in this diff naming the file: "
                          f"`tampercheck: allow {basename} <reason>` "
                          f"(or run with --allow test-deleted:{basename}).",
                allowed=reason is not None,
                reason=reason or "",
            ))
            continue  # nothing else to scan in a deleted file

    # Per-file, hunk-aware scanning for the line rules and assertion census.
        removed_assertions = 0
        added_assertions = 0

        for hunk in pfile:
            hunk_lines = list(hunk)
            for idx, line in enumerate(hunk_lines):
                if line.is_removed and is_test and lang in ASSERTION_RE:
                    if ASSERTION_RE[lang].search(line.value):
                        removed_assertions += 1
                if not line.is_added:
                    continue
                text = line.value.rstrip("\r\n")

                if is_test and lang in ASSERTION_RE and ASSERTION_RE[lang].search(text):
                    trivial = TRIVIAL_ASSERTION_RE.get(lang)
                    if not (trivial and trivial.search(text)):
                        added_assertions += 1

                for rule in RULES:
                    if lang not in rule.languages:
                        continue
                    if not _scope_matches(rule.scope, is_test, is_ci):
                        continue
                    if not rule.pattern.search(text):
                        continue
                    if rule.followed_by is not None:
                        nxt = next(
                            (l for l in hunk_lines[idx + 1:] if not l.is_removed),
                            None,
                        )
                        if nxt is None or not nxt.is_added or not rule.followed_by.search(nxt.value):
                            continue
                    neighborhood = [
                        l.value for l in hunk_lines[max(0, idx - 2): idx + 3]
                    ]
                    reason = _allow_marker(neighborhood)
                    if reason is None and rule.kind == "swallowed-error":
                        if any(NOQA_ACK_RE.search(t) for t in neighborhood):
                            reason = "lint acknowledgment (noqa/nosec) on the line"
                    findings.append(Finding(
                        kind=rule.kind, severity=rule.severity, path=path,
                        line=line.target_line_no, evidence=_compact(text),
                        rationale=rule.rationale,
                        allowed=reason is not None,
                        reason=reason or "",
                    ))

        # 6. assertion-weakened — the census, per test file. Net loss of one
        # assertion line is refactor noise (corpus: 16 hits, dominated by
        # 1-line deltas in honest rewrites); a net loss of 2+ is reported.
        if is_test and removed_assertions - added_assertions >= 2:
            reason = _allow_marker(
                [l.value for h in pfile for l in h if l.is_added]
            )
            findings.append(Finding(
                kind="assertion-weakened", severity="high", path=path, line=None,
                evidence=f"{removed_assertions} assertion line(s) removed, "
                         f"{added_assertions} substantive assertion line(s) added",
                rationale="The tests still run and still pass; they just check "
                          "less than they did before this change.",
                allowed=reason is not None,
                reason=reason or "",
            ))

    # One finding per (kind, path, line): overlapping patterns collapse.
    unique: dict[tuple, Finding] = {}
    for f in findings:
        unique.setdefault((f.kind, f.path, f.line), f)
    result = list(unique.values())
    result.sort(key=lambda f: (-SEVERITY_ORDER[f.severity], f.path, f.line or 0))
    return result


def worst_severity(findings: list[Finding]) -> str | None:
    live = [f for f in findings if not f.allowed]
    if not live:
        return None
    return max(live, key=lambda f: SEVERITY_ORDER[f.severity]).severity

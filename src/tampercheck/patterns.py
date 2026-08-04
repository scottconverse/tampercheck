"""The declarative detection table.

Every detection is data: a kind, a severity, a file scope, and per-language
regexes over single added lines (plus two special detections handled in the
engine: test-deleted, which is file-level, and assertion-weakened, which
counts lines). Adding a language means adding entries here, not control flow.

Scopes:
    "test"  - fires only in files classified as test files
    "any"   - fires in any recognized source file
    "ci"    - fires only in CI/workflow YAML and shell scripts
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- language classification -------------------------------------------------

EXT_LANG = {
    ".py": "python",
    ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js",
    ".ts": "js", ".tsx": "js", ".mts": "js", ".cts": "js",
    ".rs": "rust",
    ".sh": "shell", ".bash": "shell",
    ".yml": "yaml", ".yaml": "yaml",
}

# Paths that identify a test file, per language family.
_TEST_PATH = re.compile(
    r"(?:^|/)(?:tests?|__tests__|spec|specs)/"      # test directories
    r"|(?:^|/)conftest\.py$"
    r"|(?:^|/)test_[^/]+\.py$|_test\.py$"           # pytest conventions
    r"|\.(?:test|spec)\.[cm]?[jt]sx?$",             # foo.test.ts / foo.spec.js
    re.IGNORECASE,
)


def language_of(path: str) -> str | None:
    p = path.replace("\\", "/").lower()
    for ext, lang in EXT_LANG.items():
        if p.endswith(ext):
            return lang
    return None


def is_test_file(path: str) -> bool:
    p = path.replace("\\", "/")
    if language_of(p) is None:
        return False
    return bool(_TEST_PATH.search(p))


# --- assertion recognition (used by the assertion-weakened counter) ----------

ASSERTION_RE = {
    "python": re.compile(
        r"^\s*(?:assert\s|assert\()|"
        r"\bself\.assert[A-Z]\w*\s*\(|\bself\.fail\w*\s*\(|"
        r"\bpytest\.raises\s*\(|\bpytest\.warns\s*\("
    ),
    "js": re.compile(
        r"\bexpect\s*\(|\bassert\s*\(|\bassert\.\w+\s*\(|"
        r"\.should\b|\bshould\.\w+|\bchai\."
    ),
    "rust": re.compile(r"\bassert(?:_eq|_ne|_matches)?!\s*\("),
}

# Assertions that are always-true and therefore do not count as added coverage.
TRIVIAL_ASSERTION_RE = {
    "python": re.compile(r"^\s*assert\s+(?:True|1)\s*(?:,.*)?(?:#.*)?$"),
    "js": re.compile(
        r"\bassert\.(?:ok|equal|strictEqual)\s*\(\s*(?:true|1)\s*[,)]|"
        r"\bexpect\s*\(\s*true\s*\)\s*\.\s*to(?:Be|Equal|\.be)"
    ),
    "rust": re.compile(r"\bassert!\s*\(\s*true\s*[,)]"),
}


# --- the detection table -----------------------------------------------------

@dataclass(frozen=True)
class Rule:
    kind: str
    severity: str            # "critical" | "high" | "medium"
    scope: str               # "test" | "any" | "ci"
    languages: tuple[str, ...]
    pattern: re.Pattern
    rationale: str
    # Optional second line that must immediately follow as the next added line
    # (for constructs like a bare `except:` followed by `pass`).
    followed_by: re.Pattern | None = field(default=None)


RULES: tuple[Rule, ...] = (
    # 2. test-focused — a focus marker silently excludes every other test.
    Rule(
        kind="test-focused", severity="critical", scope="test",
        languages=("js",),
        pattern=re.compile(
            r"\b(?:describe|context|suite|test|it)\.only\s*\(|"
            r"\bf(?:it|describe)\s*\("
        ),
        rationale="A focused test runs alone: every other test in the file is "
                  "silently excluded while the run still reports green.",
    ),

    # 3. unconditional-success — the check passes regardless of behaviour.
    # Corpus-tuned: `|| true` on cleanup/config/query commands is idiomatic
    # shell (65 hits across 1,331 real commits, all legitimate). It only
    # weakens verification when attached to a test/check runner.
    Rule(
        kind="unconditional-success", severity="critical", scope="any",
        languages=("shell", "yaml"),
        # The lookarounds keep runner names from matching inside paths like
        # civicrecords-pytest-collect.out (a real corpus false positive).
        pattern=re.compile(
            r"(?:(?<![\w/.-])(?:pytest|jest|vitest|mocha|playwright|tox|unittest)(?![\w/.-])|"
            r"\bcargo\s+test\b|\bgo\s+test\b|"
            r"\bnode\s+--test\b|\b(?:npm|pnpm|yarn)\s+(?:run\s+)?test\b|"
            r"\bmake\s+(?:test|check)\b)"
            r"[^#\n]*(?:\|\|\s*true\b|\|\|\s*:\s*$|;\s*exit\s+0\b)"
        ),
        rationale="This forces the test command to report success even when "
                  "it failed, so the check can no longer fail.",
    ),
    Rule(
        kind="unconditional-success", severity="critical", scope="ci",
        languages=("yaml",),
        pattern=re.compile(r"^\s*exit\s+0\s*(?:#.*)?$"),
        rationale="A bare `exit 0` inside a CI step ends the step successfully "
                  "no matter what happened before it.",
    ),
    Rule(
        kind="unconditional-success", severity="critical", scope="test",
        languages=("js",),
        pattern=re.compile(r"\bprocess\.exit\s*\(\s*0\s*\)"),
        rationale="Exiting 0 from inside a test process forces a passing "
                  "result regardless of what the tests observed.",
    ),
    Rule(
        kind="unconditional-success", severity="critical", scope="test",
        languages=("python",),
        pattern=re.compile(r"\bsys\.exit\s*\(\s*0\s*\)|\bos\._exit\s*\(\s*0\s*\)"),
        rationale="Exiting 0 from inside a test process forces a passing "
                  "result regardless of what the tests observed.",
    ),
    Rule(
        kind="unconditional-success", severity="critical", scope="test",
        languages=("python",),
        pattern=re.compile(r"^\s*assert\s+(?:True|1)\s*(?:,.*)?(?:#.*)?$"),
        rationale="`assert True` can never fail; it stands where a real "
                  "assertion should be.",
    ),
    Rule(
        kind="unconditional-success", severity="critical", scope="test",
        languages=("js",),
        pattern=re.compile(
            r"\bassert\.(?:ok|equal|strictEqual)\s*\(\s*(?:true|1)\s*[,)]|"
            r"\bexpect\s*\(\s*true\s*\)\s*\.\s*to"
        ),
        rationale="An always-true assertion can never fail; it stands where a "
                  "real assertion should be.",
    ),
    Rule(
        kind="unconditional-success", severity="critical", scope="test",
        languages=("rust",),
        pattern=re.compile(r"\bassert!\s*\(\s*true\s*[,)]"),
        rationale="`assert!(true)` can never fail; it stands where a real "
                  "assertion should be.",
    ),

    # 4. test-skipped — the test exists but no longer runs.
    Rule(
        kind="test-skipped", severity="high", scope="test",
        languages=("js",),
        # Unconditional forms only: `.skip(` with a literal first argument or
        # no argument. `test.skip(!dockerAvailable(), "...")` is a runtime
        # environment guard (corpus: 24 hits, all legitimate guards).
        pattern=re.compile(
            r"\b(?:describe|context|suite|test|it)\.(?:skip|todo)\s*\(\s*[\"'`)]|"
            r"\bx(?:it|describe|test)\s*\("
        ),
        rationale="A newly skipped test still appears in the suite but no "
                  "longer verifies anything.",
    ),
    Rule(
        kind="test-skipped", severity="high", scope="test",
        languages=("python",),
        # Unconditional skips only. @pytest.mark.skipif(<real condition>) and
        # runtime pytest.skip("...") inside a guard are legitimate environment
        # guards (corpus-tuned); a literal skipif(True, ...) is an
        # unconditional skip in disguise.
        pattern=re.compile(
            r"@pytest\.mark\.skip\b(?!if)|"
            r"@pytest\.mark\.skipif\s*\(\s*True\b|"
            r"@unittest\.skip\b(?!If|Unless)"
        ),
        rationale="A newly skipped test still appears in the suite but no "
                  "longer verifies anything.",
    ),
    Rule(
        kind="test-skipped", severity="high", scope="any",
        languages=("rust",),
        pattern=re.compile(r"#\[ignore\b"),
        rationale="An `#[ignore]`d test compiles but is excluded from "
                  "`cargo test` runs.",
    ),

    # 5. test-filtered — the executed set shrinks; the reported outcome doesn't.
    Rule(
        kind="test-filtered", severity="high", scope="any",
        languages=("shell", "yaml", "js", "python", "rust"),
        pattern=re.compile(
            r"--test-name-pattern\b|"
            r"--grep(?:\s|=)|"
            r"\bpytest\b[^#\n]*\s-k\s*[=\s]|"
            r"\bpytest\b[^#\n]*--deselect\b|"
            r"\bjest\b[^#\n]*(?:\s-t\s|--testNamePattern)|"
            r"\bcargo\s+test\b[^#\n]*\s(?!--)[a-zA-Z_][a-zA-Z0-9_:]*\s*$"
        ),
        rationale="A test-selection filter shrinks the set of tests that "
                  "actually run without changing how the result is reported.",
    ),

    # 7. swallowed-error — failures are caught and discarded.
    Rule(
        kind="swallowed-error", severity="high", scope="any",
        languages=("js",),
        pattern=re.compile(r"\bcatch\s*(?:\([^)]*\))?\s*\{\s*\}"),
        rationale="An empty catch block hides the failure from everything "
                  "downstream, including the test runner.",
    ),
    Rule(
        kind="swallowed-error", severity="high", scope="any",
        languages=("js",),
        pattern=re.compile(r"\bcatch\s*(?:\([^)]*\))?\s*\{\s*$"),
        followed_by=re.compile(r"^\s*\}"),
        rationale="An empty catch block hides the failure from everything "
                  "downstream, including the test runner.",
    ),
    # Broad catches only: swallowing a SPECIFIC expected exception (e.g.
    # `except OSError: pass` in an availability probe) is a deliberate,
    # visible choice (corpus: 21 hits, all probes). Swallowing everything
    # is the tamper smell.
    Rule(
        kind="swallowed-error", severity="high", scope="any",
        languages=("python",),
        pattern=re.compile(
            r"\bexcept\s*(?:\(?\s*(?:Exception|BaseException)\b[^:]*)?:\s*pass\b"
        ),
        rationale="A broad except-pass hides any failure from everything "
                  "downstream, including the test runner.",
    ),
    Rule(
        kind="swallowed-error", severity="high", scope="any",
        languages=("python",),
        pattern=re.compile(
            r"^\s*except\s*(?:\(?\s*(?:Exception|BaseException)\b[^:]*)?:\s*(?:#.*)?$"
        ),
        followed_by=re.compile(r"^\s*pass\s*(?:#.*)?$"),
        rationale="A broad except-pass hides any failure from everything "
                  "downstream, including the test runner.",
    ),
    Rule(
        kind="swallowed-error", severity="high", scope="any",
        languages=("rust",),
        pattern=re.compile(r"\bErr\s*\([^)]*\)\s*=>\s*\{\s*\}"),
        rationale="An empty Err match arm discards the error, hiding the "
                  "failure from everything downstream.",
    ),

    # 8. placeholder — a stub standing where requested behaviour should be.
    Rule(
        kind="placeholder", severity="medium", scope="any",
        languages=("python", "js", "rust", "shell", "yaml"),
        pattern=re.compile(
            r"\b(?:TODO|FIXME|HACK|XXX)\b[:\s]|"
            r"\bnot[ _-]implemented\b|"
            r"\braise\s+NotImplementedError\b|"
            r"\bunimplemented!\s*\(|\btodo!\s*\(",
            re.IGNORECASE,
        ),
        rationale="A newly added placeholder may be standing in for behaviour "
                  "that was supposed to be implemented.",
    ),
)

SEVERITY_ORDER = {"medium": 0, "high": 1, "critical": 2}

# Inline justification marker: suppresses a finding on the same or an adjacent
# line, and travels with the diff where reviewers can see it.
ALLOW_RE = re.compile(r"tampercheck:\s*allow\b\s*(?P<reason>.*)", re.IGNORECASE)

# An existing lint acknowledgment for deliberate broad-except swallowing
# (ruff/bandit S110 try-except-pass, S112 try-except-continue, BLE001 blind
# except) is the same statement in established vocabulary: the author already
# justified this line in the diff itself.
NOQA_ACK_RE = re.compile(r"#\s*noqa[:\s].*\b(?:S110|S112|BLE001)\b|#\s*nosec\b")

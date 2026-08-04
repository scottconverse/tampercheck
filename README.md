# tampercheck

**Did this change weaken the project's own verification?**

`tampercheck` reads a code change (a unified diff) and reports whether that
change made the *checking* weaker than it was before: deleted tests, focused
or skipped tests, forced-success expressions, hollowed-out assertions,
swallowed errors, and placeholders standing where behaviour should be.

It exists because an AI coding agent told to "make the tests pass" has two
options — fix the code, or make the tests stop checking. Deleting the failing
test, adding `.only`, appending `|| true`, weakening an assertion, wrapping
the failure in an empty `catch`: every one of those produces a green run and
an honest-sounding summary. A linter can't see it (it checks the code that
exists, not the test that was removed), and CI reports green because green is
exactly what was engineered. `tampercheck` looks at the diff instead.

It is deliberately provider- and harness-agnostic: it reads a diff, so it does
not care whether Claude, Codex, a colleague, or you wrote the change.

## Install

```sh
uvx tampercheck --version        # zero-install run via uv
pip install tampercheck          # or install normally
```

## Use

```sh
git diff | tampercheck                 # diff on stdin
tampercheck --from main --to HEAD      # runs git itself
tampercheck --pr 123                   # GitHub PR via the gh CLI
tampercheck --json                     # machine-readable output
tampercheck --min-severity critical    # only criticals fail the run
```

**Exit codes** — `0` clean, `1` findings at or above `--min-severity`
(default `high`), `2` the tool itself failed. `2` is never conflated with
`1`: a crashed check must not look like a clean result.

## The eight detections

Every detection fires **only on lines the change added**. Pre-existing
conditions in the repository are never reported.

| # | Kind | Severity | Catches |
|---|---|---|---|
| 1 | `test-deleted` | critical | a test file removed by this change |
| 2 | `test-focused` | critical | a newly added `.only` / `fit` / `fdescribe` — silently excludes every other test |
| 3 | `unconditional-success` | critical | newly added `\|\| true`, bare `exit 0` in CI, `process.exit(0)` / `sys.exit(0)` in tests, `assert(true)` |
| 4 | `test-skipped` | high | newly added `.skip` / `.todo` / `xit` / `@pytest.mark.skip` / `#[ignore]` |
| 5 | `test-filtered` | high | a newly added test-selection filter (`--grep`, `pytest -k`, `jest -t`, `cargo test <name>`) |
| 6 | `assertion-weakened` | high | a test file that removes more executable assertions than it adds |
| 7 | `swallowed-error` | high | a newly introduced empty `catch` / `except: pass` / empty `Err(_) => {}` |
| 8 | `placeholder` | medium | a newly added `TODO` / `FIXME` / `not implemented` / `unimplemented!()` |

Languages: **Python** (pytest, unittest), **JS/TS** (jest, vitest, mocha,
node:test), **Rust**, and **shell / CI YAML**. Detection patterns live in one
declarative table (`src/tampercheck/patterns.py`); adding a language is a data
change, not a code change.

## Justifying a legitimate finding

Sometimes deleting a test is correct. Acknowledge it **in the diff itself**,
on or next to the flagged line:

```python
# tampercheck: allow replacing this suite with test_auth_v2.py in this PR
```

The finding is then reported as `ALLOWED` with your reason and does not fail
the run. The justification travels with the change, visible to whoever
reviews it — unlike an external ignore-file, it cannot drift.

## Measured false-positive rate

Patterns were tuned against **1,331 real historical commits** from three
actively developed repositories (civiccast, civicrecords-ai, civicclerk —
Python, TS, shell, CI YAML; overwhelmingly ordinary human/agent changes):

- commits with any finding: **3.0%**
- commits that would gate at the default `--min-severity high`: **1.4%**

Of that 1.4%, more than half are newly added broad `except Exception:`
swallows in production code — findings the tool is *designed* to raise, not
pattern errors. Genuine false positives measured ≈ **0.7%**, dominated by the
assertion census reacting to honest test refactors (see decisions below).
The first untuned run measured 5.6%; the tightenings that closed the gap are
recorded in `src/tampercheck/patterns.py` next to the patterns they shaped.

## Recorded decisions

- **Implementation language: Python** (≥3.10, one dependency: `unidiff`).
  Matches the primary target stack and ships via PyPI/`uvx` with nothing to
  install; the trade-off given up is a single static binary.
- **`|| true` only fires next to a test/check runner.** On cleanup/config
  commands it is idiomatic shell (65/65 corpus hits were legitimate).
- **Conditional skips are not findings.** `@pytest.mark.skipif(<condition>)`,
  runtime `pytest.skip("...")` guards, and `test.skip(!available(), ...)` are
  environment guards (24/24 corpus hits legitimate). Unconditional forms —
  `@pytest.mark.skip`, `skipif(True, ...)`, `.skip("name"` — still fire.
- **Only broad exception swallows fire.** `except OSError: pass` in an
  availability probe is a deliberate, visible choice; `except:` /
  `except Exception:` + `pass` is the tamper smell. An existing
  `# noqa: S110/S112/BLE001` or `# nosec` on the line counts as an inline
  justification, same as the allow marker.
- **Assertion census keeps the crude line-count** (the corpus said multi-line
  assertions are not the real noise source — honest refactors are), but fires
  only on a net loss of **2+** assertion lines: at net-loss-1 the corpus
  showed pure refactor noise.
- **Justification lives in the diff, not an ignore-file.** An external
  allowlist drifts and is invisible at review time; the inline marker is
  reviewed with the change it excuses.

## What it does NOT catch

Honesty section. `tampercheck` is a deterministic, line-oriented diff check.
It does not run your tests and it does not judge code quality. It will not
catch: a test whose assertion is *subtly* wrong rather than removed; a new
test that passes against the pre-change code and therefore proves nothing
(that requires executing tests against the base commit); mocking a dependency
so broadly the test can't fail; slow architectural degradation that passes
honest tests; or a filter/skip introduced in a file type it doesn't scan.
Multi-line assertions may confuse the assertion census. It reduces the
cheapest forms of verification tampering to zero cost for a reviewer — it
does not replace the reviewer.

## Exit-code contract for CI

```yaml
- name: tampercheck
  run: git diff origin/${{ github.base_ref }}...HEAD | uvx tampercheck
```

See `integrations/` for a ready-made GitHub Actions job (as used by
[deterministic-detector](https://github.com/scottconverse/deterministic-detector))
and the evidence line used by
[dev-rigor-stack-lite](https://github.com/scottconverse/dev-rigor-stack-lite).

## License

Apache-2.0 — Scott Converse.

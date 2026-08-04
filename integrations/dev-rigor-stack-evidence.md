# tampercheck evidence line for dev-rigor-stack-lite

Drop-in wording for the VERIFY / REVIEW / merge-gate skills. It keeps the
skills hook-free and portable while giving them a deterministic receipt to
cite instead of self-reported honesty.

## The evidence line (add to SKILL.md verify/review steps)

> **Verification-integrity receipt.** If `tampercheck` is available on PATH
> (or via `uvx tampercheck`), run it against the unit's diff before claiming
> VERIFY/REVIEW complete:
>
> ```sh
> git diff <base>...HEAD | tampercheck
> ```
>
> Include the command and its verbatim output in the evidence. Exit 0 is the
> receipt that the change did not weaken the project's own verification.
> Exit 1 findings must be either fixed or justified with an inline
> `tampercheck: allow <reason>` marker in the diff — never waved through in
> prose. Exit 2 means the check itself failed and is NOT a pass; rerun or
> report it. If tampercheck is not installed, state that the receipt is
> absent rather than implying it passed.

## Why this placement

The rigor stack asks the agent to be honest; tampercheck covers the case
where that fails. The threat model is the agent that quietly deletes a test,
adds `.only`, appends `|| true`, or hollows an assertion — and then
truthfully reports "tests pass". A deterministic diff check the agent does
not control converts "trust me" into a receipt. Enforcement (required status
checks) still belongs in CI on a machine no agent controls — see
`deterministic-detector-ci-job.yml`.

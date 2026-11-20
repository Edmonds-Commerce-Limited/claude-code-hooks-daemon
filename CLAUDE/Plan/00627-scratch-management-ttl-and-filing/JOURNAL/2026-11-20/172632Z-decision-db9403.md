## 17:26 · decision · — — Phases 1-2 re-review: dry-run-only merge

Re-review of Phases 1-2 by the security reviewer (report untracked/agent-reports/auto/261120-172534-security-reviewer-af307c80cff1912de.md).

Verdict: Phases 1-2 are safe to merge as a dry-run-only increment. DISPOSABLE is not yet safe to act on: no `--apply` may rely on it.

New findings, recorded as DESIGN.md section 13 rows, all OPEN:

- N1: an entry lending objects through `objects/info/alternates` is DISPOSABLE while its borrower is PROTECTED.
- N2: a `--separate-git-dir` git directory whose work tree is outside the root is DISPOSABLE.
- N3: P2 covers user files under a venv's `bin/`, `lib/`, `share/`, and `_is_venv` accepts any `bin/python*` prefix.
- N4: `./` and `//` spellings of a tracked mention do not reference the entry under `--root` as under the default root.
  The reflog/`ORIG_HEAD` row stays open.

Decision: merge Phases 1-2 as dry-run only. Task 3.0 (new) closes N1-N4 and the reflog row test-first, and Tasks 3.8 (wire `--apply`) and 3.9 (adversarial review) depend on it.

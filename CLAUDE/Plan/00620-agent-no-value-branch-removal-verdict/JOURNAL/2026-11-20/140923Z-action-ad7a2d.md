## 14:09 · action · — — Task 2.3 session-start count and docs

Task 2.3 finished: the session-start count of undigested removals.

`BranchSweepHandler._reject_digest_lines()` runs on every SessionStart source, independently of the branch inventory, so an inventory failure does not hide it. It builds the store from `main_checkout(root) / state_dir` and reads the ledger at `root / ledger_path` with `build_digest`. Two separate failure paths:

- no main checkout (not a repository, or bare): silent;
- a damaged ledger, keep record or watermark: one loud "unreadable" line naming the digest command, never a zero.

Nothing undigested prints nothing. It makes no git call per entry and writes nothing (a test pins that the watermark file is never created by the count).

Docs: DESIGN.md section 11 (the digest and the count; listing never advances the watermark; the state gates nothing), the section 10 crash sentence now points at the `STILL PRESENT at its tip` flag, and `docs/guides/CONFIGURATION.md` names the digest beside `branch-reject request`. `regenerate-docs` from this worktree's src changed no tracked file (the CLAUDE.md block lists `branch_sweep` as a one-line advisory), and the generated-doc drift check passes.

Residue, recorded not redesigned: an agent can run `--mark-read`. That hides entries from the digest and from this count only; `approve_removal` never reads the watermark, so it unlocks nothing (`TestDigestGatesNothing`).

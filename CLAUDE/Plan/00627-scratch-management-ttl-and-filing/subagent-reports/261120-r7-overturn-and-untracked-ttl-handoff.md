# Plan 00627: handoff after the R7 overturn and the untracked TTL map

Branch `agent-acff915e4bf3b86e6-0a26f829` (worktree `.claude/worktrees/agent-acff915e4bf3b86e6-0a26f829`), pushed, not merged to main. `origin/main` was merged in first (7027c18db). The head sha is the commit that adds this file; `git log -1` on the branch gives it. Earlier handoffs: [phase1-handoff-3.md](phase1-handoff-3.md).

## Done

- **Plan and design** (142d98735): DESIGN.md section 0 quotes both owner decisions verbatim. R7 is marked overturned. R16 and section 4.1 are new. Section 3.3 (standalone row), 3.3.1, 3.6, 4 and 10 are updated. PLAN.md Goals, Success Criteria, Task 2.1 and the new Tasks 1.8 and 1.9 match.
- **Task 1.8** (fac01ff44): the R7 route is gone from `core/scratch_verdict.py`, and a test pins the new reason. A `.git` marker is still REPOSITORY, "not judged", and never DISPOSABLE, because Phase 1 cannot tell the kinds of repository apart.
- **Task 1.9** (5aa1c3eec):
  - `ScratchConfig.untracked_ttl` and `untracked_default_ttl` replace `ttl_hours` and `sweep.extra_roots`, with `ttl_hours_for(name)`. The config validator drops `ttl_hours <= max_ttl_hours` so that the owner's `scratch: 7d` loads. The clock uses `max(max_lifetime_hours, root TTL)`.
  - `core/untracked_roots.py` `resolve_sweep_root` handles every root. `run_sweep` now takes a `SweepRoot`, so no caller can skip the check.
  - The CLI feeds it `config.reference_repos.roots`.
  - Added release note `017-scratch-sweep-dry-run-and-untracked-ttls.md` and `config-changes/v3.77.0.yaml`.
- **Journal**: `JOURNAL/2026-11-20/153356Z-decision-83b884.md`.

## Choices the coordinator should check

- **Scratch default stays 24h.** The owner typed "I suggest 24 hours" on 19 November. `7d` was given as an example of the config shape, and it loads.
- **The unlisted-directory fallthrough ships as `"*"`.** This narrows the request "any other untracked/ subdirectory gets a configurable default TTL": the key exists, but its default is never.
  - The reason: in self-install mode `untracked/` is the daemon's own runtime directory. Measured here, it holds `venv-*`, `logs`, `worktrees`, `spend-ledger`, `supervise`, `thread-registry` and others.
  - No registry exists to exclude them by.
  - `logs/*.log` already passes P1, so a finite fallthrough would make each of them a sweep root.
- **R6 is kept as briefed** (a related clone with unpushed or dirty work is PROTECTED). The owner's "no special rules for repos" is broader than that.
- **Release-note number 017.** It is the next number used on no ref; two branches already use 016.
- **Config-changes file.** `v3.77.0.yaml` also exists on two other branches, so the merge will be add/add.

## Remaining

- **Phase 2 is not started.** It is unblocked, but this agent passed its context budget.
- **Task 2.1** is where the R7 decision really lands:
  - Standalone must be proved for every marker in an entry. One marker of another kind, or any git failure or timeout, decides the entry, as PROTECTED or STUCK.
  - Classify from the main repository where possible (`git worktree list --porcelain`, `git config --file <nested>/.git/config`).
  - Any git run inside a nested repository needs `GIT_OPTIONAL_LOCKS=0`, `-c core.fsmonitor=false` and hooks disabled. Without them, `git status` rewrites `.git/index`, which breaks the "dry run changes no inode" test and resets the TTL clock.
  - Extend the inode-snapshot test over a real nested repository.
  - Test a mixed entry (standalone plus registered worktree) and a shallow clone of the project with no remote.
  - `tests/support/scratch_tree.py` makes only fake `.git` markers today, not real repositories.
- **Tasks 2.2 to 2.5**, as PLAN.md lists them.
- **Sweeping every finite-TTL directory in one run, and loose files directly under `untracked/`**: Task 6.1.

## Deletion-surface risks for the security review

Nothing deletes yet: the whole branch is a dry run. These are the risks the later `--apply` work will inherit.

1. **Standalone misclassification.** Once Task 2.1 sends standalone repositories down the ordinary ladder, any wrong "standalone" verdict gives a worktree or a related clone the archive-and-remove route. The classification must fail closed.
2. **Root reach.**
   - `--root` accepts any path, including absolute paths. The resolver refuses the project, `untracked/`, any path holding the project, and anything at or inside `repos`, `scratch-archive` or a reference root. It checks both the literal path and the link-resolved path.
   - Any other path is judged with the scratch TTL. That includes `--root tests/support` or a tracked directory. Tracked files are not yet excluded, because Phase 1 runs no git.
   - Before `--apply` exists, it must refuse any root that is not a configured `untracked/` directory, or that holds tracked files.
3. **A finite `untracked_default_ttl` in self-install** turns every daemon store into a sweep root. It ships as `"*"`. A client could set it, and the config-changes entry warns against that.
4. **Git executing inside nested repositories** (Phase 2): their hooks, their config and fsmonitor are untrusted.
5. **No in-flight-operation rule beyond liveness.** The design has only process working directories, background-process records and minimum age. A git `index.lock`, a `rebase-merge/` directory or a `MERGE_HEAD` in a nested repository is not yet a LIVE or STUCK signal. Task 2.1 should treat one as STUCK.
6. **Reference roots come from config.** Removing `untracked/repos` from `reference_repos.roots` does not unprotect it, because `repos` is in `NEVER_SWEPT`. Any other reference root is protected only while it is configured.

## QA state

Targeted QA passed:

- pytest over the scratch, config, CLI and release-manifest tests: 708 and 128 passed.
- ruff, black and `mypy --strict` on every touched file, with `PYTHONPATH=<worktree>/src`.

The full gate has not been run; it is the coordinator's.

# Handoff: fix B landed and recorded; Task 4.3 steps 2-4 left (261121)

Branch `agent-acff915e4bf3b86e6-0a26f829`, pushed. Venv and `untracked/scratch/qa.sh` as in
`261121-task-4.3-step1-fixA-done-handoff.md` (run it as `bash untracked/scratch/qa.sh ...`).

## Done this session

- `38790c3b1`, `5e52df30c` **fix B**: `refuse_foreign_owner` in `core/scratch_archive_pack.py`
  (`Node.uid`/`Node.gid`, default -1 fails closed). Apply refuses a foreign-owned ACTIONABLE
  entry while fingerprinting (`_fingerprint_all` returns `(prints, foreign)`), so no claim
  event and no rename-back (no ctime churn, no event pile-up). Pack, the adopt proof and the
  remover's proof (resume included) check again. Tests: pack (real chown as root, and
  monkeypatched geteuid/getegid), apply (refused, no events; non-actionable keeps its outcome),
  adopt, remove (direct and resume).
- `5f6225df9` DESIGN section 13 rows for fix A and fix B; PLAN.md line under Task 3.9.
- QA: black, ruff, mypy clean; pyright 0 errors on all scratch archive/sweep/birth-time
  sources and tests; 489 archive tests pass as root.
- NOT done: a non-root run. `/workspace/.claude` and the worktree are 0700 root and
  `project_containment` denies a copy under `/tmp`, so uid 65534 cannot reach the code or venv
  without loosening permissions on `.claude`. A human or CI (non-root) run is needed.

## Task 4.3 steps 2-4: design (advisor-reviewed), nothing written yet

Run each real `s-*` directory as its OWN sub-root through the existing `run_sweep` and
`apply_sweep`; never two-level entry names (`check_name` rejects `/`; claim/pack/remove all
take a parent fd plus one name; `original_path` is prefix + name; `_expire` already holds
records of another prefix). Keep `_held_if_session` permanently for the container row.

KEY FACT found: `judge` returns `LIVE "within its TTL"` before any KEPT/PROTECTED/REFERENCED
rung when the entry is not due, so the container's row CANNOT be used to carry protections
down. Container holds must be computed independently of its verdict.

Tests first:

1. Container files are never rows: `.scratch-session.json` (`MANIFEST_NAME`), lock files and a
   session-level `.scratch-keep` go in the sub-root's `skip`.
2. Container holds carry down (overrule every actionable child): a keep marker at `s-x`; a
   tracked reference naming `s-x` itself; a working directory exactly at `s-x`; a dependency
   from another entry (`_entry_of` lands on `s-x`, from `_with_dependencies`' dependents map);
   `.git` at the session root (from the walk's `git_markers`).
3. A not-due container must not block a due child.
4. Claim-time facts: a child's `entry_live`/`referenced` must also consult `s-x` in the parent
   root (OR in the parent answer).
5. CLI restore: check `_scratch_restore` (`daemon/cli.py`) can put a child back into `s-x/`
   from the printed `restore <id>`; test apply then CLI restore BEFORE enabling child apply.
6. Child archive expiry: the sub-root pass runs its own `_expire` even with no children left,
   else step 4's "no live record under it" never becomes true.
7. Open `s-x` relative to the root fd with `O_NOFOLLOW|O_DIRECTORY`, compare (dev, ino) with
   the judged row; never reopen by path.
8. Per-entry TTL: if `scratch new --ttl-hours` records a TTL longer than the root's, use the
   larger, bounded by the lifetime backstop.
9. One level only: an `s-*` child of a session directory is an ordinary entry.
   Plus the earlier list: a session dir that is a repository (keep judging whole), refuse
   removal while a live archive record names a path under it.

Sequence: step 2 (report only) commit; step 3 (apply children) commit; step 4 (empty-and-old
removal: flock as `new_entry`, re-list, unlink manifest, `rmdir`, rewrite manifest if `rmdir`
fails) commit; tick 4.3 only after step 4. `apply_refusal` stays as is.

Until step 3 lands, no child of a session directory is ever archived (step 1 side effect).

## For the security review

Fix A (statx layout, fail-closed paths, `claim_event_covers`); fix B (`refuse_foreign_owner`,
the pre-claim refusal in `_fingerprint_all`); and, when written, 4.3's carry-down rule, the
`s-x` fd handling and the CLI restore path for a child.

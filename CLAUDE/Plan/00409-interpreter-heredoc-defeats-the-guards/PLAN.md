# Plan 00409: interpreter heredoc defeats the guards

**Status**: In Progress
**Created**: 2026-09-14
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

`bash <<'EOF'` executes its body. The quoted delimiter governs only what the
OUTER shell expands on the way in — it does not stop the receiving interpreter
running the bytes. `strip_quoted_heredoc_bodies` blanks the body anyway, so
every guard that judges the stripped text sees an empty command.

This is a REGRESSION published in v3.64.0, not a pre-existing gap, and the
distinction is measured rather than argued. The shipped v3.63.0 module was
recovered with `git show v3.63.0:…/destructive_git.py` and executed side by
side with the installed one (`untracked/scratch/probe_v3630_regression.py`):
v3.63.0 judged the RAW command and DENIED all five destructive spellings below;
v3.64.0 allows every one of them.

| command                                         | v3.63.0 | v3.64.0 |
| ----------------------------------------------- | ------- | ------- |
| `bash <<'EOF'` + `git reset --hard HEAD`        | DENY    | allow   |
| `bash <<'EOF'` + `git checkout -- f.txt`        | DENY    | allow   |
| `bash <<'EOF'` + `git clean -fd`                | DENY    | allow   |
| `bash <<'EOF'` + `git push --force origin main` | DENY    | allow   |
| `bash <<'EOF'` + `git branch -D main`           | DENY    | allow   |
| `cat <<'EOF'` + `git reset --hard HEAD`         | DENY    | allow   |

The last row is the INTENDED change — release note 29 (Plan 00377 N7) set out
to stop prose describing a destructive command being denied, and `cat` really
does treat the body as data. The defect is that the fix keyed on the heredoc's
QUOTING rather than on its RECEIVER, so it exempted the interpreter case too.

The remedy already exists in this codebase and was reached deliberately: Plan
00335 Decision 1 gave `curl_pipe_shell` an ALLOWLIST of data sinks, because
asking "is the receiver dangerous?" makes every name nobody thought of default
to safe — which it did four separate times there. `quoted_heredoc_receivers`
was written for exactly this and says so in its own docstring ("a caller
blanking bodies for a safety decision would otherwise hand out a clean
bypass"). Of the eight consumers that blank heredoc bodies, only
`curl_pipe_shell` consults it.

## Goals

- A heredoc body is blanked only when every receiving word is a recognised
  data sink; an unrecognised receiver withholds the exemption and the body is
  scanned.
- The fix lives in `utils/shell_segmentation` so all eight consumers get it at
  once, rather than one of them growing a private copy.
- The v3.63.0-vs-installed comparison is a permanent test, not a scratch probe.

## Non-Goals

- TAKING the release. A release requires a fresh human `/release`; the v3.64.0
  authorisation was consumed and its state file archived and deleted. This plan
  lands the fix on `main` and leaves the decision with the human.

  It does NOT follow that the release is out of scope, and the distinction is
  deliberate: until a published version carries this fix, every installation is
  running a data-loss guard that `bash <<'EOF'` walks past. So the plan stays
  open on that one criterion rather than closing on "the code is fixed" — a
  completed plan is the wrong place for a live obligation, and an archived one
  is worse. The Active list is where somebody looks.

- Re-litigating release note 29. Blanking a `cat`/`git commit -F -` body stays
  correct and must keep working — those are the regression tests, not the bug.

## Tasks

### Phase 1: Pin the regression

- [x] ✅ **Task 1.1**: Failing tests first, at the `shell_segmentation` level
  and at the handler level for each of the eight consumers that blank bodies:
  `destructive_git`, `daemon_location_guard`, `merge_to_main_approval`,
  `pipe_blocker`, `plan_number_helper`, `bash_flags`, `process_probe`,
  `reference_repo_freshness`. Cover `bash`, `sh`, `/bin/sh`, `sudo -E bash`,
  `python3` and `ssh host` as receivers, and keep `cat`, `tee` and
  `git commit -F -` as the must-stay-exempt cases.

### Phase 2: Fix it where all consumers see it

- [x] ✅ **Task 2.1**: Gate the blanking in `strip_quoted_heredoc_bodies` on the
  data-sink allowlist, promoting `_DATA_SINKS` from `curl_pipe_shell` into
  `utils/shell_segmentation` as the shared source of truth. Leave
  `curl_pipe_shell`'s extra pipe-into-interpreter check where it is — it guards
  a case the allowlist does not, and defence in depth costs nothing here.

- [x] ✅ **Task 2.2**: `pipe_blocker`'s CLAUDE.md guidance states "A heredoc
  whose DELIMITER IS QUOTED is never scanned at all", which this change makes
  untrue. Correct it to the receiver rule and regenerate the guidance block.

### Phase 3: The rest of the review-n12 findings

- [x] ✅ **Task 3.1**: The other `review-n12` findings existed only in
  gitignored `untracked/agent-reports/`, so they were recorded here first to
  stop them being lost. They have since been rehoused into
  [Plan 00408](../00408-handler-hygiene-from-the-release-review/PLAN.md) Phase
  3e (Tasks 3.7–3.10), which is where the review's leftovers belong — this plan
  is one shipped regression, not the review's backlog.

  Each was re-verified against the report before being moved rather than copied
  from a summary, and the two merge-gate bypasses were re-run on the fixed code
  to confirm they are not side effects of this plan's change. One item was
  corrected in the move: the `cd`-evasion list omitted the double-quoted
  spelling `cd .claude/"hooks-daemon"`.

  Not rehoused, because re-reading the report shows it was mine rather than the
  reviewer's: the claim that `git commit -m` alone on a line is swallowed. The
  report says the swallow needs a VALUELESS `-m`, which git itself rejects, and
  classes every message shape git actually accepts as unaffected.

## Success Criteria

- [x] ✅ Running the shipped v3.63.0 `destructive_git` and the fixed one over
  the same table yields no row where v3.63.0 denies and the fix allows, except
  the `cat` row that release note 29 deliberately changed. One flip remains and
  it is that row (`untracked/scratch/probe_v3630_regression.py`).
- [ ] ⬜ Full QA passes, the daemon is restarted, and CI is green.
- [x] ✅ The human is told, in plain terms, that v3.64.0 carries this defect and
  that RELEASING.md's rollback table prescribes a patch release for it.
- [ ] ⬜ **BLOCKED ON HUMAN — a published version carries the fix.** RELEASING.md's
  rollback table prescribes "After push: Create immediate patch release (NEVER
  force-push tags)". Only a human `/release` can start one, so this criterion
  cannot be ticked by an agent and the plan cannot close without it. Everything
  else above is done; this is the whole of what remains.

## Delivery & Milestones

- Found while verifying [Plan 00407](../Completed/00407-niggles-ledger-twelve/PLAN.md)
  N12, by a probe rather than by reading. The `review-n12` sub-agent reported
  the same hole but characterised it as pre-existing and codebase-wide; running
  the shipped v3.63.0 code disproved that. A peer agent's characterisation is a
  hypothesis to verify, which is the same rule this project applies to issue
  text.

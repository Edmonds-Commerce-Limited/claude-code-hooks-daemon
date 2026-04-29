# Plan 00102: Hook Executable-Bit Defense (Multi-Tier Safety Net)

**Status**: In Progress
**Created**: 2026-04-29
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded
**Supersedes**: Plan 00091 (`hook-executable-permissions`) — Phase 1 already shipped at commit 8a3f1ba; Phase 2 (`git_filemode_checker`) folds into Tier 3 below.

## Problem

In some client repos, the executable bit on `.claude/hooks/*` files is silently dropped, which breaks the entire hooks daemon integration with no obvious error. Known triggers:

- Git repos with `core.fileMode=false` lose `100755` on checkout/merge/rebase
- Cross-platform clones (Windows/WSL) round-trip the mode bit
- Tarball / ZIP archive transfers lose Unix permissions
- Some IDE "format on save" or file-rewrite tools recreate files at `0644`
- `cp`/`rsync` without `-p`, certain backup/restore flows

Plan 00091 already covers two of the obvious mitigations (force-commit `100755` via `git update-index --chmod=+x`, and warn on `core.fileMode=false`). It is **Not Started**. Before executing 00091, we want to widen the search and design a defense-in-depth strategy.

The user's seed idea: stop assuming hook scripts are executable — invoke them as `bash /path/to/hook` from `settings.json`. This requires a config update on every client repo but eliminates the failure mode entirely.

## Goal

Brainstorm broadly, triage the ideas, then design a multi-tier defense that combines the strongest options. The output of this plan is a follow-up implementation plan with concrete tasks (which may supersede 00091).

## Brainstorm Phase

Four sub-agents are dispatched in parallel, each from a different angle, writing their report into this folder:

| Agent | Angle                                                                                            | Report file              |
| ----- | ------------------------------------------------------------------------------------------------ | ------------------------ |
| 1     | **Prevention** — keep the bit set in the first place                                             | `REPORT-1-prevention.md` |
| 2     | **Bypass** — make the bit irrelevant (invocation/packaging tricks)                               | `REPORT-2-bypass.md`     |
| 3     | **Detection & self-heal** — notice it's broken and fix it automatically                          | `REPORT-3-detection.md`  |
| 4     | **Cross-ecosystem prior art** — how do husky / pre-commit / lefthook / direnv / mise solve this? | `REPORT-4-prior-art.md`  |

Each report MUST include:

- Summary of the angle
- 3–6 concrete ideas
- For each idea: mechanism, pros, cons, blast radius (one repo vs every client), implementation cost (S/M/L)
- One paragraph at the bottom recommending the agent's top pick

## Triage Phase

After reports land, the main thread will:

1. Read all four reports
2. Pull out the strongest ideas across all reports (deduplicating)
3. Design a layered defense (prevention + bypass + detection)
4. Write `TRIAGE.md` with the chosen strategy and tradeoffs
5. Spawn or update an implementation plan (likely supersedes 00091)

## Notes

- Plan 00091 (`hook-executable-permissions`) covers `git update-index --chmod=+x` + `git_filemode_checker` SessionStart handler. Not yet started. May be folded into the final plan or superseded.
- Recent commit `8a3f1ba` is related: "hook wrappers lose exec bit — stop silencing chmod failures and run set_hook_permissions in self-install mode" — proves the bug is live and ongoing.
- Recent commit `0fbc412` added a shell-script error-hiding auditor for the same class of failure mode.

---

## Implementation (post-triage)

See `TRIAGE.md` for the analysis and rationale. Decisions made:

- Backup strategy: single one-shot `settings.json.bak`, overwrite-protected.
- Tier 4 (`hooks-daemon doctor` CLI): deferred to follow-up release.

### Phase 1 — Tier 1: Switch to `bash <abs-path>` invocation (the actual fix)

- [ ] ⬜ **Task 1.1**: Locate the `command:` emitter in `install.py` (around lines 528–565) — confirm the exact dict-literal format.
- [ ] ⬜ **Task 1.2**: Write failing test in `tests/unit/install/test_settings_emit.py` asserting the emitter produces `bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/<event>` form (RED).
- [ ] ⬜ **Task 1.3**: Update `install.py` emitter to produce the `bash <path>` form (GREEN).
- [ ] ⬜ **Task 1.4**: Update this repo's own dogfood `.claude/settings.json` to match.
- [ ] ⬜ **Task 1.5**: Add acceptance-style integration test that simulates `chmod -x` on `.claude/hooks/*` and verifies hooks still fire end-to-end via the daemon socket.
- [ ] ⬜ **Task 1.6**: Run `./scripts/qa/run_all.sh` — all 10 checks must pass.

### Phase 2 — Tier 2: Auto-migrate existing client `settings.json`

- [ ] ⬜ **Task 2.1**: Read `src/claude_code_hooks_daemon/handlers/session_start/hook_registration_checker.py` to find the audit point where `command:` strings are inspected.
- [ ] ⬜ **Task 2.2**: Add `_LEGACY_COMMAND_PATTERN` constant matching bare-path command values ending in `.claude/hooks/<event-name>` (no leading `bash `, no shell args).
- [ ] ⬜ **Task 2.3**: Add `_NEW_COMMAND_FORMAT` constant for the `bash <path>` shape.
- [ ] ⬜ **Task 2.4**: Write failing tests covering:
  - legacy form detected
  - new form generated correctly
  - one-shot `settings.json.bak` created (overwrite-protected: never overwritten on subsequent migrations)
  - idempotent on second run (no rewrite, no second backup)
  - hand-edited non-daemon command paths left untouched
- [ ] ⬜ **Task 2.5**: Implement migration: rewrite matching entries, write `.bak` if absent, emit `additionalContext` message naming what was migrated.
- [ ] ⬜ **Task 2.6**: Add config option `auto_migrate_settings: true` (default on) for opt-out.
- [ ] ⬜ **Task 2.7**: Run QA, restart daemon, verify RUNNING.

### Phase 3 — Tier 3a: `init.sh` sibling self-heal (belt-and-braces)

- [ ] ⬜ **Task 3.1**: Add throttled (once-per-hour) sibling chmod block near the top of `.claude/init.sh`. Throttle via fingerprint file `.claude/hooks-daemon/untracked/.exec-bit-checked`.
- [ ] ⬜ **Task 3.2**: Confirm shellcheck passes on `init.sh`.
- [ ] ⬜ **Task 3.3**: Confirm shell-script error-hiding auditor (added in commit `0fbc412`) still passes.

### Phase 4 — Tier 3b: `git_filemode_checker` SessionStart handler (folded from Plan 00091 Phase 2)

- [ ] ⬜ **Task 4.1**: Add `HandlerID.GIT_FILEMODE_CHECKER` and `Priority.GIT_FILEMODE_CHECKER = 53`.
- [ ] ⬜ **Task 4.2**: Write failing tests in `tests/unit/handlers/session_start/test_git_filemode_checker.py` (init, matches new-vs-resume, handle filemode=true/false/no-repo/timeout).
- [ ] ⬜ **Task 4.3**: Implement `handlers/session_start/git_filemode_checker.py` following `optimal_config_checker.py` pattern.
- [ ] ⬜ **Task 4.4**: Register in `__init__.py` and `.claude/hooks-daemon.yaml`.
- [ ] ⬜ **Task 4.5**: Update `docs/guides/HANDLER_REFERENCE.md`.

### Phase 5 — Verification & docs

- [ ] ⬜ **Task 5.1**: Restart daemon, verify RUNNING.
- [ ] ⬜ **Task 5.2**: Regenerate docs: `$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-docs`.
- [ ] ⬜ **Task 5.3**: Acceptance-test the full flow: install in a fresh test project, `chmod -x .claude/hooks/*`, verify hooks still fire after auto-migration runs on session start.
- [ ] ⬜ **Task 5.4**: Mark Plan 00091 as Cancelled (superseded), update its README entry.

## Success Criteria

- [ ] After installing or upgrading, hooks fire correctly even if `.claude/hooks/*` are mode 0644.
- [ ] Existing client repos auto-migrate `settings.json` on first session after upgrade with no user action.
- [ ] A `settings.json.bak` is created exactly once per repo and never overwritten.
- [ ] Auto-migration is idempotent (second SessionStart is a no-op).
- [ ] Hand-edited non-daemon command paths in `settings.json` are not touched.
- [ ] `git_filemode_checker` advisory fires once per new session for repos with `core.fileMode=false`.
- [ ] All 10 QA checks pass.
- [ ] Daemon restarts cleanly with new code.
- [ ] Plan 00091 is closed as superseded.

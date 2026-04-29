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

- [x] ✅ **Task 1.1**: Locate the `command:` emitter in `install.py` (around lines 528–565) — confirm the exact dict-literal format.
- [x] ✅ **Task 1.2**: Write failing test in `tests/unit/install/test_installer_hook_paths.py` asserting the emitter produces `bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/<event>` form (RED).
- [x] ✅ **Task 1.3**: Update `install.py` emitter to produce the `bash <path>` form via `_hook_cmd()` helper (GREEN — 2/2 pass).
- [x] ✅ **Task 1.4**: Update this repo's own dogfood `.claude/settings.json` — all 10 hook events now use `bash <path>`; statusLine left untouched (exempt by Claude Code design).
- [x] ✅ **Task 1.5**: Acceptance integration test added at `tests/integration/test_hook_exec_bit_irrelevant.py` — copies real `pre-tool-use` wrapper, drops +x, asserts direct invocation fails AND `bash <path>` does NOT produce Permission denied. 2/2 pass.
- [x] ✅ **Task 1.6**: Run `./scripts/qa/llm_qa.py all` — 11/11 PASSED, coverage 95.0%, daemon RUNNING.

### Phase 2 — Tier 2: Auto-migrate existing client `settings.json`

- [x] ✅ **Task 2.1**: Read `src/claude_code_hooks_daemon/handlers/session_start/hook_registration_checker.py` to find the audit point where `command:` strings are inspected.
- [x] ✅ **Task 2.2**: Added `_LEGACY_PATH_PATTERN` regex in `utils/hook_command_migration.py` matching bare-path commands ending in `.claude/hooks/<event-name>`.
- [x] ✅ **Task 2.3**: Added `_BASH_PREFIX = "bash "` constant; `is_legacy_hook_command()` predicate detects legacy form.
- [x] ✅ **Task 2.4**: 18 tests in `tests/unit/utils/test_hook_command_migration.py` cover legacy detection, rewrite-in-place, one-shot `.bak.pre-bash-migration` overwrite-protected, idempotent second run, custom user paths preserved, missing/malformed-file no-ops, defensive isinstance branches. All pass.
- [x] ✅ **Task 2.5**: `migrate_settings_to_bash_invocation()` rewrites matching entries; `.bak` created only if absent. Handler folds `MigrationResult` into `additionalContext` naming migrated events.
- [x] ✅ **Task 2.6**: Added `auto_migrate_settings: true` (default) under `handlers.session_start.hook_registration_checker.options`. Handler `configure()` reads it.
- [x] ✅ **Task 2.7**: QA 11/11 PASSED, coverage 95.0%, daemon RUNNING.

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

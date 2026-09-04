# Plan 00102: Hook Executable-Bit Defense (Multi-Tier Safety Net)

**Status**: In Progress (Phase 6 — the statusLine and fallback-installer holes in Tier 1; Task 5.3 still awaits the next /release)
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
- [x] ✅ **Task 1.4**: Update this repo's own dogfood `.claude/settings.json` — all 10 hook events use `bash <path>`. This task also left statusLine bare, on a stated "exempt by Claude Code design" rationale that was never true; Phase 6 disproves it and closes the gap.
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

- [x] ✅ **Task 3.1**: Added `_exec_bit_selfheal()` to `.claude/init.sh` after `_get_hostname_suffix()`. Throttle file `$_untracked_dir/.exec-bit-checked` is mtime-checked (Linux `stat -c %Y`, BSD `stat -f %m` fallback) — fresh stamp (< 3600s) short-circuits, stale or missing runs the chmod loop. Loop iterates the explicit known-hooks list so unrelated files (README.md, init.sh sibling) are never touched. Renamed prior `HOOK_SCRIPT_DIR` (init.sh's own dir) to private `_INIT_SCRIPT_DIR` so `HOOK_SCRIPT_DIR` now points at `.claude/hooks/` for the function. Integration tests `tests/integration/test_init_sh_exec_bit_selfheal.py` (5/5 pass) extract the function via curly-brace slicing and assert: chmods all 10 hooks on first call, creates throttle, recent throttle skips, stale throttle re-runs, README.md/init.sh sibling left at 0644.
- [x] ✅ **Task 3.2**: `shellcheck -x .claude/init.sh` exits 0 (zero issues).
- [x] ✅ **Task 3.3**: `scripts/qa/audit_shell.py` reports zero violations — function uses `2>/dev/null` only inside `if mtime=$(...)` guards, never the `2>/dev/null || true` double-suppression pattern.

### Phase 4 — Tier 3b: `git_filemode_checker` SessionStart handler (folded from Plan 00091 Phase 2)

- [x] ✅ **Task 4.1**: `HandlerID.GIT_FILEMODE_CHECKER` and `Priority.GIT_FILEMODE_CHECKER = 53` registered (constants/handlers.py + constants/priority.py).
- [x] ✅ **Task 4.2**: Failing tests added at `tests/unit/handlers/session_start/test_git_filemode_checker.py`.
- [x] ✅ **Task 4.3**: `handlers/session_start/git_filemode_checker.py` implemented following `optimal_config_checker.py` pattern.
- [x] ✅ **Task 4.4**: Registered in `handlers/session_start/__init__.py` and active in `.claude/hooks-daemon.yaml` (priority 53, advisory).
- [x] ✅ **Task 4.5**: `docs/guides/HANDLER_REFERENCE.md` — added detailed entry between `optimal_config_checker` and `suggest_status_line`, plus row in priority summary table.

### Phase 5 — Verification & docs

- [x] ✅ **Task 5.1**: Daemon restart verified RUNNING (PID 71299, socket exists, fingerprint-keyed venv).
- [x] ✅ **Task 5.2**: `generate-docs` regenerated `.claude/HOOKS-DAEMON.md`. New `git_filemode_checker` row visible at priority 53 in the SessionStart table.
- [ ] ⬜ **Task 5.3**: Acceptance-test the full flow at release time — covered by `/release` skill's mandatory acceptance gate.
- [x] ✅ **Task 5.4**: Plan 00091 marked Cancelled (superseded by 00102), moved to `Completed/`, README's Cancelled Plans section updated with cross-reference.

### Phase 6 — Tier 1 was never finished: statusLine and the fallback installer

Tier 1 claims the exec bit is irrelevant. It is not, in two places Phase 1
missed. Task 1.4 recorded the first as deliberate — "statusLine left untouched
(exempt by Claude Code design)" — and that rationale appears nowhere in
`TRIAGE.md` or any of the four brainstorm reports. It was asserted at
implementation time and is false.

**The exemption, disproved three ways.** Claude Code's own documentation says
`statusLine` "runs any shell script you configure", that `type: "command"`
means "run this shell command", and that "because `statusLine` executes a
shell command, Claude Code runs it under the same workspace trust rule as
hooks". Its Windows example uses the exact interpreter-plus-path shape this
tier is about — `powershell -NoProfile -File <path>`. And locally: the
tracked command is `"$CLAUDE_PROJECT_DIR"/.claude/hooks/status-line`, which
names no existing file, so a direct `execve` would fail with ENOENT — yet the
status line renders, so it is reaching a shell. The `chmod +x` advice in those
docs applies to the bare-path form, which is the failure mode this plan
exists to remove.

**The second hole is larger and is not about statusLine.**
`scripts/install_version.sh`'s last-resort fallback writes RELATIVE bare paths
for every hook, not just the status line. Two failures compound: the path
resolves against the process cwd rather than the project, and nothing repairs
it — `_LEGACY_PATH_PATTERN` requires a `$CLAUDE_PROJECT_DIR` prefix so Tier 2
skips these entirely, while `reconcile_settings_hooks` only fills in MISSING
events and never rewrites present ones. A fallback install stays exec-bit
dependent forever. Introduced by `2c417449`, whose subject calls it the "SSoT
bash fallback" — a name describing an intent the content never had.

**Why both survived Phase 1's tests.** `test_settings_hook_paths.py` does
inspect the statusLine command, but asserts only that it contains
`$CLAUDE_PROJECT_DIR` and `.claude/hooks/` — it passes with or without the
`bash ` prefix. The fallback heredoc has no test at all. Separately,
`validate_hook_commands` checks only that a command ENDS WITH
`/.claude/hooks/<key>`, so no validator anywhere detects a bare-path command
for any event.

- [x] ✅ **Task 6.1**: Assert the missing shapes FIRST (RED) — statusLine
  emitted by `install.py`, the tracked `.claude/settings.json`, the
  `install_version.sh` fallback, and the migrator's handling of the top-level
  `statusLine` key. These are the assertions whose absence let both defects
  through, so they are the deliverable as much as the fix is.

- [x] ✅ **Task 6.2**: `install.py` emits statusLine via the same `_hook_cmd`
  helper as every other hook, and the comment asserting the exemption goes.

- [x] ✅ **Task 6.3**: `scripts/install_version.sh`'s fallback emits
  `bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/<key>` for every entry including
  the status line.

- [x] ✅ **Task 6.4**: `suggest_statusline.py` recommends the `bash <path>`
  form. This is the advice a human reads and pastes, so leaving it stale would
  keep reintroducing the defect by hand.

- [x] ✅ **Task 6.5**: The tracked `.claude/settings.json` uses the `bash`
  form for its own statusLine — dogfooding, and the fixture two tests read.

- [x] ✅ **Task 6.6**: `migrate_settings_to_bash_invocation` also migrates the
  top-level `statusLine` key, and matches the relative bare-path shape the
  fallback installer produces. Without both, an already-installed client never
  self-heals.

- [x] ✅ **Task 6.7**: `validate_hook_commands` reports a command that is not
  invoked through `bash`, statusLine included, so a future regression is
  caught by the checker rather than by a client's broken hooks.

## Success Criteria

- [ ] After installing or upgrading, hooks fire correctly even if `.claude/hooks/*` are mode 0644.
- [ ] Existing client repos auto-migrate `settings.json` on first session after upgrade with no user action.
- [ ] A `settings.json.bak` is created exactly once per repo and never overwritten.
- [ ] Auto-migration is idempotent (second SessionStart is a no-op).
- [ ] Hand-edited non-daemon command paths in `settings.json` are not touched.
- [ ] `git_filemode_checker` advisory fires once per new session for repos with `core.fileMode=false`.
- [x] The status line survives its wrapper being mode 0644, on a fresh install and after auto-migration — `test_hook_exec_bit_irrelevant.py` copies the real wrapper, drops `+x`, and asserts direct invocation breaks while `bash <path>` does not.
- [x] Every command the fallback installer writes is absolute and `bash`-invoked, so a fallback install is not a permanently unrepaired one — asserted against the heredoc the script actually ships, which had no test of any kind before.
- [x] A bare-path command is REPORTED by the checker for any event, statusLine included.
- [ ] All 10 QA checks pass.
- [ ] Daemon restarts cleanly with new code.
- [ ] Plan 00091 is closed as superseded.

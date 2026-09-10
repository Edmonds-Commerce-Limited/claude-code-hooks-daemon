# Plan 00368 Task 2.2 — completion report

## Starting state

Dispatched against `worktree-plan-00368a` head `3e76073a` (WIP handoff).
Direct inspection (not the dispatch message's "last seen diagnostics",
which predated the 09:20–09:52 restructure already recorded in the
journal) showed Task 2.2's own code already complete and correct: all
five per-language strategies (`python_strategy.py`, `typescript_strategy.py`,
`go_strategy.py`, `rust_strategy.py`, `php_strategy.py`), the shared
`common.py`/`protocol.py`/`registry.py`, the `LspNoiseCheckerHandler`
orchestrator, every wiring point (`constants/handlers.py`,
`constants/priority.py`, `constants/rule_ids.py`,
`handlers/session_start/__init__.py`, `.claude/hooks-daemon.yaml`(.example)),
`docs/guides/HANDLER_REFERENCE.md`'s five-language mechanism table,
`explain-rule` for both rule IDs, the config-changes manifest, and
release-notes callout 19 all imported cleanly and matched what the
`import`/`pytest`/`explain-rule` checks below confirmed. PLAN.md's Task
2.2 wording and Goals paragraph already read "every supported language",
not "Python alone" — no edit needed there.

## What this session did

1. **Two sequential merges of `origin/main`**, not one — origin/main
   advanced a second time (Plan 00367 archived, Plan 00291 archived,
   Plans 00369/00370 filed) while this review was in progress:
   - First merge: only conflict was the append-only JOURNAL day-file;
     resolved by chronological concatenation (commit `d3c88290`).
   - Second merge: conflicted on `CLAUDE.md` (fully auto-generated;
     resolved by taking origin/main's tracked copy wholesale, then
     `bin/hooks-daemon regenerate-docs` rebuilt it correctly from this
     branch's actual handler set) and on
     `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.64.0.yaml` (add/add;
     resolved by keeping all five `added:` entries — this branch's
     `lsp_noise_checker` plus 00367's four plan-close/merge-approval
     keys — under one list) (commit `5998453b`).
2. **Docs regeneration**: a git hook auto-committed a CLAUDE.md refresh
   right after the second merge's daemon restart (`790af2fc`); a manual
   `bin/hooks-daemon regenerate-docs` afterward caught one remaining
   drift — `.claude/HOOKS-DAEMON.md`'s summary line for
   `lsp_noise_checker` still read the pre-restructure "a Python project's
   pyright config" wording — and fixed it (`f7ed5af6`).
3. **Journal**: added a `12:17` entry recording this session's findings
   and the merge/QA work (`b2be87dc`).

All four commits pushed to `origin/worktree-plan-00368a`.

## QA

Ran `./scripts/qa/llm_qa.py all` three times (600000ms foreground/polled
background, never idle-waited):

- **Run 1** (before any merge, stale daemon): 25/27 — pyright (expected,
  see below) plus 12 acceptance/integration test failures. All 12 passed
  individually on rerun after a daemon restart; root cause was a stale
  daemon socket left from before this session's work, matching the exact
  failure mode the journal's 09:15 entry already documents.
- **Run 2** (after daemon restart, three-to-five sibling worktrees —
  00367, 00368b, 00369, 00370, plus the main checkout — concurrently
  running their own full QA suites and daemon restarts on this shared
  host): 25/27 — pyright plus 2 different, unrelated socket-listener test
  failures. Both passed individually on rerun; a standalone
  `llm_qa.py tests` run came back 0 failed. Non-reproducing, shifting
  failure sets across runs 1 and 2 are themselves evidence of host
  contention, not a defect in this branch.
- **Run 3** (after the second merge, `regenerate-docs`, and a further
  daemon restart): **26/27 clean** — pyright is the sole failure.

**pyright**: 942 errors (1562 files analysed) — up from the 938 recorded
before this session's second merge, because that merge brought in a
handful more pre-existing files from Plans 00367/00291. This is the
documented, expected Phase 3 backlog (PLAN.md Task 3.1, tracked on other
branches: `worktree-plan-00368b`/`00368c`), not something this task
introduces. Verified directly: **zero pyright diagnostics in any file
under `strategies/lsp_noise/` or `handlers/session_start/lsp_noise_checker.py`**,
both before and after the second merge. mypy: clean (`Success: no issues found in 10 source files`) on the same file set.

**Targeted tests**: 387 passed (137 `lsp_noise` strategy/handler tests +
the `test_claude_md_guidance_coverage.py` integration test, rerun after
the second merge to confirm nothing regressed).

**Daemon**: restarted twice (after each merge), confirmed `RUNNING` both
times via `bin/hooks-daemon status`.

## Coverage table (from `docs/guides/HANDLER_REFERENCE.md`)

| Language              | `R-LSP-CONFIG-EXCLUDE` mechanism                                                                                                                                                                                                                            | `R-LSP-SERVER-STALE` process |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------- |
| Python                | `pyrightconfig.json` (or `[tool.pyright]` in `pyproject.toml`) `exclude`                                                                                                                                                                                    | `pyright-langserver`         |
| TypeScript/JavaScript | `tsconfig.json` (or `jsconfig.json`) `exclude`                                                                                                                                                                                                              | `typescript-language-server` |
| Go                    | No exclude list — gopls scopes to `go.mod`'s module boundary; reported only when a non-project tree holds `.go` files inside it                                                                                                                             | `gopls`                      |
| Rust                  | No exclude list, but workspace membership is editable — reported entries go into the root `Cargo.toml`'s `[workspace] exclude`                                                                                                                              | `rust-analyzer`              |
| PHP                   | No project file at all — intelephense takes `files.exclude` only via LSP client settings, which the official `php-lsp` plugin never sets; the fix is a project-scope LSP plugin under `.claude/plugins/*/` that re-registers `.php` with its own `settings` | `intelephense`               |

Every mechanism verified against `anthropics/claude-plugins-official`'s
`.claude-plugin/marketplace.json` (no plugin ships `settings`/
`initializationOptions`) and each tool's own docs — see each strategy's
own docstring and `strategies/lsp_noise/CLAUDE.md` for the sourced
detail.

## Unresolved / flagged for awareness (not this task's scope)

- **Phase 3** (`Task 3.1`/`3.2`, fixing the 942 pre-existing pyright
  errors) is explicitly out of scope for Task 2.2 and is tracked on
  `worktree-plan-00368b`/`worktree-plan-00368c`.
- **`.claude/reports/v2.2.0-to-v2.15.2/ADVISORY.md`**: an earlier journal
  entry (09:09) recorded this as a stray scratch artefact and deleted it;
  it reappeared in the WIP handoff commit and, on investigation this
  session, turned out to be **genuinely tracked on `origin/main`** (a
  real, unrelated config-migration advisory file — confirmed via
  `git ls-tree -r origin/main` and `git show origin/main:<path>`), not
  scratch. Left in place; not this task's file to resolve either way.
- Callout numbering has a gap at 18 in this branch (01–17, then 19) —
  expected: 18 belongs to Plan 00367's Worktree.core.md work, which is on
  a separate branch not yet in this one's ancestry at time of review (a
  later `origin/main` fetch did bring 00367 in; not re-checked for
  callout 18 after that, as it is that plan's artefact, not this one's).

## Key file paths

- `/workspace/untracked/worktrees/worktree-plan-00368a/src/claude_code_hooks_daemon/handlers/session_start/lsp_noise_checker.py`
- `/workspace/untracked/worktrees/worktree-plan-00368a/src/claude_code_hooks_daemon/strategies/lsp_noise/` (protocol.py, common.py, registry.py, python_strategy.py, typescript_strategy.py, go_strategy.py, rust_strategy.py, php_strategy.py)
- `/workspace/untracked/worktrees/worktree-plan-00368a/tests/unit/strategies/lsp_noise/` and `/workspace/untracked/worktrees/worktree-plan-00368a/tests/unit/handlers/session_start/test_lsp_noise_checker.py`
- `/workspace/untracked/worktrees/worktree-plan-00368a/CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.64.0.yaml`
- `/workspace/untracked/worktrees/worktree-plan-00368a/CLAUDE/UPGRADES/UNRELEASED/release-notes/19-lsp-output-is-signal-not-noise.md`
- `/workspace/untracked/worktrees/worktree-plan-00368a/docs/guides/HANDLER_REFERENCE.md`
- `/workspace/untracked/worktrees/worktree-plan-00368a/CLAUDE/Plan/00368-lsp-is-signal-not-noise/PLAN.md`
- `/workspace/untracked/worktrees/worktree-plan-00368a/CLAUDE/Plan/00368-lsp-is-signal-not-noise/JOURNAL/00368-Journal-26-09-10.md`

## Commits (this session, all pushed to `origin/worktree-plan-00368a`)

- `d3c88290` — merge origin/main (journal-only conflict)
- `5998453b` — merge origin/main round 2 (CLAUDE.md + config-changes manifest conflicts)
- `790af2fc` — auto-commit: CLAUDE.md regenerated (git hook, post-restart)
- `f7ed5af6` — regenerate docs: fix stale Python-only wording in `.claude/HOOKS-DAEMON.md`
- `b2be87dc` — journal entry recording this session's work

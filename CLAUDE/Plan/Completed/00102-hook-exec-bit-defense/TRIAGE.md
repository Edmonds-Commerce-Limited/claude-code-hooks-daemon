# Triage: Layered Defense Against Hook Exec-Bit Loss

**Date**: 2026-04-29
**Inputs**: REPORT-1-prevention.md · REPORT-2-bypass.md · REPORT-3-detection.md · REPORT-4-prior-art.md

## Headline finding: cross-report convergence

The **single strongest signal** in the brainstorm is that two agents reached the same conclusion from opposite directions:

- **Agent 2 (bypass, first principles)**: change `settings.json` from `/path/to/hook` to `bash /path/to/hook` — the kernel reads the file as data, exec bit becomes irrelevant.
- **Agent 4 (prior art, empirical)**: husky v9, direnv, and lefthook all migrated *away* from "chmod the tracked file" *toward* "source the tracked file from a regenerated shim". Husky v9's [#1177](https://github.com/typicode/husky/issues/1177) post-mortem documents the same failure mode we're hitting.

Two independent searches arriving at the same answer is the strongest possible signal. The user's seed idea (`bash <path>`) is correct and is the *industry-standard* answer.

## Validation of the user's seed idea (no XY problem)

I checked whether the user might be asking for the wrong thing. They are not:

- The proposed change *eliminates* the failure mode (no exec bit needed → no exec bit can be lost).
- It also kills the chicken-and-egg problem identified by Agent 3: if hooks no longer require +x, no "detect and self-heal" foothold problem exists.
- It is the cheapest possible change: `~5 lines` in `install.py` (the dict literal at lines 528–565), one matching edit to this repo's own `.claude/settings.json`, and `~30 lines` in the existing `hook_registration_checker` SessionStart handler to auto-migrate existing client repos. No new handler needed.
- Cross-platform exposure is unchanged: Claude Code already invokes a bash wrapper directly, so requiring `bash` on PATH is no new requirement.

The user's "this will require config updates in each client project" concern is legitimate but solvable: the existing `hook_registration_checker` handler reads `settings.json` on every SessionStart and is the natural seam for an in-place auto-rewrite with backup. **Existing client repos heal themselves on first session after upgrade with zero user action.**

## Recommended layered defense

Four tiers, ordered by how decisively each one closes the failure mode.

### Tier 1 — Eliminate (the actual fix)

**Switch hook invocation from direct-exec to `bash <abs-path>`.** Exec bit becomes irrelevant for all causes (`core.fileMode=false`, Windows clones, tarballs, IDE rewrites, `cp` without `-p`).

- `install.py:528–565` — rewrite the `command:` strings emitted into `.claude/settings.json`.
- `.claude/settings.json` — match the new form in this repo's own dogfood config.
- Source: Agent 2 idea #1, Agent 4 patterns #2 and #5.

### Tier 2 — Auto-migrate existing clients (zero-touch rollout)

**Extend `hook_registration_checker.py` (SessionStart, priority 51) to rewrite legacy bare-path `command:` entries to the new `bash <path>` form.** One-shot, idempotent, with `settings.json.bak` backup, gated by a config flag for opt-out.

- Match regex: `command:` strings ending in `.claude/hooks/{event-name}` with no leading `bash `.
- Surface a CONTEXT message naming what was migrated and why.
- Source: Agent 2 idea #6.

### Tier 3 — Belt-and-braces (defends the corners Tier 1 can't)

Even with Tier 1 in place, two adjacent failure modes exist:

1. **Misconfiguration awareness** — `core.fileMode=false` is still a smell that breaks other tools. Keep **Plan 00091 Phase 2** (`git_filemode_checker` SessionStart handler) as a non-blocking advisory. Drop Plan 00091 Phase 1 from scope (it became near-irrelevant once we adopt Tier 1 and it's already partially shipped at commit `8a3f1ba`).
2. **`init.sh` sibling self-heal** — `init.sh` is sourced by every hook on every event. Add a once-per-hour throttled block that `chmod u+x`'s any siblings missing the bit. Cheap insurance for repos that revert to direct-exec invocation, or for transitional periods. Source: Agent 3 idea #5.

### Tier 4 — Surfacing & forensics (optional follow-up)

**`hooks-daemon doctor` CLI subcommand.** Walks `.claude/hooks/*`, reports executable-bit, shebang, init.sh resolvability. `--fix` flag re-chmods. Wire into `scripts/debug_info.py` so bug reports auto-include the data. Source: Agent 3 idea #3. Useful for triage of failed installs but not required for the defense itself.

## Ideas explicitly rejected

| Idea                                               | Source             | Why rejected                                                                                                                                                                                               |
| -------------------------------------------------- | ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Refuse install on `core.fileMode=false`            | Agent 1 #2         | Hostile first-install UX. Made unnecessary by Tier 1: with `bash <path>`, `core.fileMode=false` is a warning-worthy smell, not a hard failure.                                                             |
| Daemon-startup re-chmod                            | Agent 3 #2         | Unnecessary once Tier 1 lands. Adds startup latency for a problem that no longer exists.                                                                                                                   |
| Status-line indicator                              | Agent 3 #4         | Won't surface the only case that matters (daemon unreachable because hook wrapper can't fire) and low ROI given Tier 1.                                                                                    |
| Anomaly detector for missing event types           | Agent 3 #6         | Overengineered heuristic. Would have value if Tier 1 wasn't available.                                                                                                                                     |
| Full husky-v9-style shim-outside-tree              | Agent 4 pattern #1 | Architecturally invasive (gitignored generated dir, `core.hooksPath` indirection equivalent). Tier 1 captures most of the benefit at a fraction of the cost. Reserve for v4 if Tier 1 proves insufficient. |
| `sh <path>` for portability                        | Agent 2 #2         | Wrappers and `init.sh` use bash-isms. Would force a full POSIX rewrite for marginal portability gain.                                                                                                      |
| `python -m claude_code_hooks_daemon.hooks.<event>` | Agent 2 #3         | Adds 30–80ms python startup to every event — kills the project's headline 20× perf claim.                                                                                                                  |
| Single launcher binary on PATH                     | Agent 2 #4         | Distribution problem (PyPI wheel can't put a binary on PATH cleanly; \`curl                                                                                                                                |
| Inline command in `settings.json`                  | Agent 2 #5         | Quoting nightmare; every wrapper edit becomes a settings.json migration.                                                                                                                                   |
| Installer-managed `.git/hooks/pre-commit`          | Agent 1 #5         | Conflicts with husky/lefthook/pre-commit users — unacceptable.                                                                                                                                             |
| Wheel-resource extraction with `os.chmod`          | Agent 1 #6         | Breaks self-install dogfooding architecture.                                                                                                                                                               |

## Implementation outline (next plan)

This triage feeds directly into a new implementation plan. Suggested phases:

1. **Tier 1 implementation + unit tests** — change the install.py command-string emitter, update this repo's settings.json, add tests asserting the new form is what gets written. Verify hooks still fire after `chmod -x .claude/hooks/*`.
2. **Tier 2 auto-migration** — extend `hook_registration_checker.py` with detection + rewrite + backup logic. Add unit tests for: legacy form detected, rewrite produced, backup created, no double-migration on second run, idempotent.
3. **Tier 3a (optional)** — `init.sh` sibling self-heal, throttled. Shell-script auditor must pass.
4. **Tier 3b** — proceed with Plan 00091 Phase 2 (`git_filemode_checker`) only. Drop Phase 1 expansion (already shipped) and supersede that plan.
5. **Tier 4 (follow-up)** — `hooks-daemon doctor` CLI subcommand.

**Acceptance test for Tier 1**: in a fresh project, run `chmod -x .claude/hooks/*` then trigger a Claude Code event. With Tier 1 in place, hooks still fire. Without it, they fail with `Permission denied`.

**Supersedes**: Plan 00091 (`hook-executable-permissions`) — Phase 1 partially shipped at `8a3f1ba`; Phase 2 (`git_filemode_checker`) folds into this plan's Tier 3.

## Decisions for the user

Before spinning up the implementation plan, two questions worth confirming:

1. **Backup strategy for auto-migration**: write `settings.json.bak` once, or version the backup (`.bak.0001`)? Recommendation: single one-shot backup, overwrite-protected.
2. **Tier 4 scope**: ship `hooks-daemon doctor` in the same release as Tier 1, or defer to a follow-up release? Recommendation: defer — Tier 1+2 close the bug, Tier 4 is a nicety.

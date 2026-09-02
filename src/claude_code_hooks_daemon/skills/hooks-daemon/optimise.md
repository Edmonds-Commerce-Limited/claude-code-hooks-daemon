# Hooks Daemon Configuration Optimiser (the config-optimisation step)

This is the formalised "enable all relevant handlers and ensure optimal configuration"
step (Plan 00308) — the same step whether run manually, automatically at the end of
`/hooks-daemon upgrade`, or as the closing step of LLM-INSTALL.md/LLM-UPDATE.md.

Analyse the current hooks daemon configuration against the project's profile (languages,
tests, CI, plans) and produce a scored report across five key areas. Also compares the
project's config against `CLAUDE/UPGRADES/config-changes/` manifests to surface
capabilities introduced since the last recorded run, and can apply recommendations
automatically. Every run (report-only or apply) records itself via
`bin/hooks-daemon record-config-optimisation-run`, which silences the
`config_optimisation_reminder` SessionStart advisory until the next upgrade.

## Usage

```claude-code
/hooks-daemon optimise
```

No arguments — the step profiles the project automatically.

**Naming (Plan 00322)**: this used to be a standalone `/optimise` skill. A
top-level command that generic collides with whatever else a project or plugin
calls `optimise`, so it now lives in the daemon's own namespace with `upgrade`,
`health` and `bug-report`. A project that still has `.claude/skills/optimise/`
on disk is holding an orphan from before the move; the installer removes it.

## Running it

**Run this first** — it prints the full instruction set, which you then follow
exactly:

```bash
bash "${CLAUDE_SKILL_DIR:-.claude/skills/hooks-daemon}/scripts/optimise-invoke.sh"
```

The script resolves the project root, the config path and the daemon CLI
wrapper for this install (normal or self-install), then emits the step-by-step
analysis and apply procedure. **The summary below is orientation only — the
script's output is the procedure.** Nothing runs it for you: Claude Code loads
markdown, never a sibling script, so skipping this command means running the
step from the summary alone (Plan 00322).

## What It Checks

The skill analyses five areas, scoring each PASS / WARN / FAIL:

1. **Safety** — Critical blocking handlers (destructive_git, sed_blocker, security_antipattern, etc.)
2. **Stop Quality** — Handlers that prevent poor stopping behaviour (auto_continue_stop, plus the nitpick.hedging_language and nitpick.dismissive_language detectors)
3. **Plan Workflow** — Plan tracking handlers and whether the workflow is actively being used
4. **Code Quality** — TDD, QA suppression, lint-on-edit, LSP enforcement, daemon restart verification
5. **Daemon Settings** — Session-start advisories, version checks, git context injection

## What It Outputs

```
╔══════════════════════════════════════════════════════════════╗
║           Hooks Daemon Configuration Optimiser               ║
╚══════════════════════════════════════════════════════════════╝

Project Profile:
  Languages detected: Python, TypeScript
  Test directory: tests/ ✓
  CI config: .github/workflows/ ✓
  Plan directory: CLAUDE/Plan/ (5 active, 12 completed)

━━━ Area 1: Safety ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PASS (7/7)
...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Overall Score: 28/35 (80%)
Recommendations: ...
```

## Apply Recommendations

After viewing the report, Claude asks whether to apply recommendations:

- **"apply all"** — Enable all recommended handlers and restart daemon
- **"apply 2,3"** — Apply specific recommendations by number
- **"skip"** — View report only, make no changes

## Reference Documentation

**SINGLE SOURCE OF TRUTH:**

- Handler options and values: `.claude/hooks-daemon/docs/guides/HANDLER_REFERENCE.md`
- Configuration format: `.claude/hooks-daemon/docs/guides/CONFIGURATION.md`
- Available handlers: `.claude/HOOKS-DAEMON.md` (project root)

## Version

Introduced in: v2.29.0

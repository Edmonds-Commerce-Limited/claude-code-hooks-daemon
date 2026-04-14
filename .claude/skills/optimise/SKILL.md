---
name: optimise
description: Analyse hooks daemon configuration and recommend improvements across Safety, Stop Quality, Plan Workflow, Code Quality, and Daemon Settings
argument-hint: ""
---

# /optimise - Configuration Optimiser Skill

## Description

Analyse the current hooks daemon configuration against the project's profile (languages,
tests, CI, plans) and produce a scored report across five key areas. Recommends specific
handler changes and can apply them automatically.

## Usage

```bash
# Run full analysis and show scored report
/optimise
```

No arguments — the skill profiles the project automatically.

## What It Checks

The skill analyses five areas, scoring each PASS / WARN / FAIL:

1. **Safety** — Critical blocking handlers (destructive_git, sed_blocker, security_antipattern, etc.)
2. **Stop Quality** — Handlers that prevent poor stopping behaviour (auto_continue_stop, task_completion_checker, hedging/dismissive detectors)
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
- Handler options and values: @docs/guides/HANDLER_REFERENCE.md
- Configuration format: @docs/guides/CONFIGURATION.md
- Available handlers: @.claude/HOOKS-DAEMON.md

## Version

Introduced in: v2.29.0

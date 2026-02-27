# Plan 00072: Bug Report Generator

**Status**: Complete (2026-02-27)
**Created**: 2026-02-27
**Owner**: Claude Opus 4.6

## Context

A user hit the plan file race condition (fixed in v2.16.1 by Plan 00066) but their bug report was a hand-written markdown file in `untracked/` missing critical diagnostic info — no daemon version, no handler config, no logs, no system state. Triage required reading the codebase to cross-reference. A structured bug report generator would have provided all this automatically, making triage trivial.

**Goal**: Add a `bug-report` CLI subcommand and `/hooks-daemon bug-report` skill subcommand that generates a comprehensive, structured markdown report with all diagnostic info needed for triage.

## Completed Work

### Phase 1: CLI Subcommand — `cmd_bug_report()` in cli.py

- [x] Added `cmd_bug_report()` function to `cli.py`
- [x] Registered `bug-report` subparser with `description` (positional) and `--output` arguments
- [x] Report generates all 9 sections: Header, Daemon Version, System Info, Daemon Status, Configuration, Loaded Handlers, Recent Logs, Environment, Bug Description, Health Summary
- [x] Works gracefully when daemon is not running
- [x] Default output to `{untracked_dir}/bug-reports/bug-report-{timestamp}.md`
- [x] `--output` flag overrides output path
- [x] `--output -` prints to stdout
- [x] Uses `Timeout.GIT_CONTEXT` constant (no magic numbers)
- [x] All error handling has explanatory comments (no silent passes)

### Phase 2: Skill Integration

- [x] Added `bug-report` to `SKILL.md` routing (`logs|status|restart|handlers|validate-config|bug-report`)
- [x] Added `bug-report` to skill help text output
- [x] Added troubleshooting section referencing bug-report
- [x] Created `bug-report.md` skill documentation

### Phase 3: TDD Tests

- [x] 18 unit tests in `tests/unit/daemon/test_cli_bug_report.py`
- [x] Tests cover: all sections present, daemon not running, daemon running (mocked), output to file, output to stdout, default path, parent directory creation, missing config

### Verification

- [x] `bug-report "test report"` generates complete report with real data
- [x] 18/18 tests pass
- [x] QA passes (magic_values, format, lint, type_check, security, dependencies all clean)
- [x] Daemon restarts successfully
- [x] Skill routing configured

### Not Updated (Blocked)

- BUG_REPORTING.md — Root-level markdown, blocked by markdown_organization handler. Pre-existing file location.

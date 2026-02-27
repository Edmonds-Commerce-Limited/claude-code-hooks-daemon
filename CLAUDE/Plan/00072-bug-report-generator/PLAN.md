# Plan 00071: Bug Report Generator

## Context

A user hit the plan file race condition (fixed in v2.16.1 by Plan 00066) but their bug report was a hand-written markdown file in `untracked/` missing critical diagnostic info — no daemon version, no handler config, no logs, no system state. Triage required reading the codebase to cross-reference. A structured bug report generator would have provided all this automatically, making triage trivial.

**Goal**: Add a `bug-report` CLI subcommand and `/hooks-daemon bug-report` skill subcommand that generates a comprehensive, structured markdown report with all diagnostic info needed for triage.

## What Exists Today

- `scripts/debug_info.py` — standalone diagnostic script (395 lines), captures system info, daemon status, config, handlers, logs, hook tests. **Not integrated into CLI or skill.** Missing: daemon version, git commit, install mode, daemon mode, env vars, error-specific log filtering.
- `/hooks-daemon` skill (deployed to client projects) — has `health`, `upgrade`, `restart`, `dev-handlers`, `logs` subcommands. No `bug-report`.
- CLI (`cli.py`) — 29 subcommands, standard argparse pattern. No `bug-report`.

## Approach

**Do NOT extend `debug_info.py`** — it's a standalone script with its own path detection logic, runs outside the daemon, and embeds raw Python scripts as strings. Instead, build a proper CLI subcommand that uses the daemon's own infrastructure (ProjectContext, ConfigLoader, HandlerRegistry, version module).

### Phase 1: CLI Subcommand — `cmd_bug_report()` in cli.py

Add `bug-report` subcommand to `cli.py` following the `generate-playbook` pattern:

```
$PYTHON -m claude_code_hooks_daemon.daemon.cli bug-report "plan race condition"
$PYTHON -m claude_code_hooks_daemon.daemon.cli bug-report --output /tmp/report.md "description"
```

**Arguments:**
- `description` (positional, required) — brief description of the bug
- `--output` / `-o` (optional) — output file path. Default: `{daemon_untracked_dir}/bug-reports/bug-report-{timestamp}.md`

**Report sections** (structured markdown):

1. **Header** — Title with description, generation timestamp
2. **Daemon Version** — from `version.__version__`, git commit hash (via `git rev-parse HEAD` in daemon repo), install mode (self-install vs normal)
3. **System Info** — OS, kernel, architecture, Python version, hostname
4. **Daemon Status** — running/stopped, PID, uptime, current mode (default/unattended)
5. **Configuration** — full `hooks-daemon.yaml` contents
6. **Loaded Handlers** — count by event type, list with priorities, any load failures
7. **Recent Logs** — last 100 log lines (filtered for errors/warnings prominently)
8. **Hook Test** — quick echo test to verify hook pipeline works
9. **Environment** — relevant env vars (HOSTNAME, CLAUDE_HOOKS_SOCKET_PATH, etc.)
10. **Bug Description** — user's description repeated for context
11. **Health Summary** — pass/fail checklist

**Output**: Write to file, print path to stdout. If `--output -`, print to stdout.

### Phase 2: Skill Integration

**Files to modify:**
- `src/claude_code_hooks_daemon/skills/hooks-daemon/SKILL.md` — add `bug-report` to Available Commands, Implementation routing, and help text
- `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/daemon-cli.sh` — already forwards unknown commands to CLI, so `bug-report` routing should work via the existing `logs|status|restart|handlers|validate-config` case. Just need to add `bug-report` to that list.

Add a `bug-report.md` skill doc for documentation.

### Phase 3: TDD Tests

**Test file**: `tests/unit/daemon/test_cmd_bug_report.py`

Tests:
- Report contains all required sections (version, system, daemon status, config, handlers, logs, health)
- Description appears in report
- Default output path is `{untracked_dir}/bug-reports/bug-report-{timestamp}.md`
- `--output` flag overrides output path
- `--output -` prints to stdout
- Report is valid markdown
- Missing config handled gracefully
- Missing daemon handled gracefully (report still generates with error info)

### Critical Files

| File | Action |
|------|--------|
| `src/claude_code_hooks_daemon/daemon/cli.py` | Add `cmd_bug_report()` + subparser registration |
| `tests/unit/daemon/test_cmd_bug_report.py` | New test file |
| `src/claude_code_hooks_daemon/skills/hooks-daemon/SKILL.md` | Add bug-report to routing + help |
| `src/claude_code_hooks_daemon/skills/hooks-daemon/bug-report.md` | New skill doc |
| `BUG_REPORTING.md` | Update to reference new CLI command |

### Out of Scope

- Fixing `__init__.py` version inconsistency (separate bug)
- Replacing `scripts/debug_info.py` (still useful as standalone)
- GitHub issue creation automation
- Plan 00071 cleanup (already triaged, will move to Completed separately)

## Verification

1. Run: `$PYTHON -m claude_code_hooks_daemon.daemon.cli bug-report "test report"` — verify report generated
2. Check report contains all sections with real data
3. Run QA: `./scripts/qa/run_all.sh`
4. Restart daemon: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart && $PYTHON -m claude_code_hooks_daemon.daemon.cli status`
5. Verify skill routing: `/hooks-daemon bug-report "test"` would forward correctly

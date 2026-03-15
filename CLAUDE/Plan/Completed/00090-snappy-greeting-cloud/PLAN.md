# Plan 00090: Command Redirection for Blocking Handlers

**Status**: Complete (2026-03-15)
**Created**: 2026-03-15
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Context

Currently, blocking PreToolUse handlers deny a command and tell Claude the corrected version. Claude then has to re-run the corrected command in a separate turn. This wastes a turn every time.

Example (gh_issue_comments handler):
```
Turn 1: Claude runs `gh issue view 26 --json number,title,url`
         → BLOCKED: add --comments
Turn 2: Claude runs `gh issue view 26 --json number,title,url,comments`
         → Success
```

**Command redirection** eliminates the wasted turn: the handler runs the corrected command itself, saves output to a file, and returns the file path + exit code alongside the educational deny message. Claude gets both the lesson and the result in one turn.

## Goals

- Eliminate wasted turns when handlers block and suggest corrected commands
- Still educate Claude about correct command patterns (deny reason preserved)
- Per-handler toggle via `command_redirection` option (default: `true`)
- Output saved to file (not returned to context) to avoid bloating context window
- Safe subprocess execution with timeouts

## Non-Goals

- Redirecting to entirely different tools (e.g. Grep → LSP)
- Auto-allowing the redirected command (still DENY — Claude reads file instead)

## Related Bug: Plan Folder Redirection (Side Mission)

The `markdown_organization` handler creates numbered plan folders (e.g. `00090-name/PLAN.md`)
when a flat file is written to `CLAUDE/Plan/`, but returns `Decision.ALLOW` — so BOTH the
flat file AND the numbered folder are created. This is a bug.

**Root cause**: `markdown_organization._handle_plan_mode_write()` creates the folder as a
side-effect but doesn't BLOCK the original write. It should return `Decision.DENY` since
the correct file already exists.

**Fix**: Change `_handle_plan_mode_write()` to return `Decision.DENY` with reason explaining
the file was redirected to the numbered folder. This is conceptually the same pattern as
command redirection — but for Write tool instead of Bash.

**Cleanup**: Delete stale flat file `CLAUDE/Plan/snappy-greeting-cloud.md` created by this bug.

## Design

### Response Format

When command redirection is active, the handler returns:

```python
HookResult(
    decision=Decision.DENY,
    reason="BLOCKED: gh issue view requires --comments flag\n\n..."  # Educational
    context=[
        "COMMAND REDIRECTED: Corrected command was executed automatically.",
        "Exit code: 0",
        "Output saved to: /workspace/untracked/command-redirection/gh_issue_view_1710489600.txt",
        "Read the output file to get the result.",
    ],
)
```

Claude Code renders `reason` as the block error and `additionalContext` as system-reminder context. Claude sees both — learns the rule AND gets the result.

### Architecture

**Utility module** (not inheritance) — keeps handlers decoupled:

```
src/claude_code_hooks_daemon/core/command_redirection.py
├── CommandRedirectionResult (dataclass: exit_code, output_path, command)
├── execute_and_save(command, output_dir, label, timeout_seconds) → CommandRedirectionResult
└── format_redirection_context(result) → list[str]
```

Handlers call the utility from `handle()` — no base class changes needed.

### Candidate Handlers

| Handler | Corrected Command | Complexity |
|---------|-------------------|------------|
| `gh_issue_comments` | Adds `--comments` flag | Simple — already computes `suggested_command` |
| `npm_command` | Rewrites to `npm run llm:*` | Simple — already computes `suggested` |
| `pipe_blocker` | Removes pipe, redirects to file | Medium — needs to extract base command |

**Phase 1**: `gh_issue_comments` (proof of concept)
**Phase 2**: `npm_command`, `pipe_blocker`

### Security

- Commands are computed by the handler (not from user input) — safe by construction
- Use `subprocess.run()` with list args (no `shell=True`)
- Timeout: 30 seconds default (configurable)
- Output dir: `{daemon_untracked}/command-redirection/` (not `/tmp`)
- File cleanup: Files older than 1 hour auto-cleaned on next execution

### Per-Handler Toggle

Uses existing options pattern:

```yaml
# .claude/hooks-daemon.yaml
handlers:
  pre_tool_use:
    gh_issue_comments:
      enabled: true
      priority: 40
      options:
        command_redirection: true  # default: enabled
```

Handler reads: `getattr(self, "_command_redirection", True)`

When disabled, handler blocks with educational message only (current behaviour).

## Tasks

### Phase 1: Core Infrastructure + TDD

- [ ] **Task 1.1**: Write failing tests for `core/command_redirection.py`
  - Test `execute_and_save()` runs command, captures output, writes file
  - Test exit code capture (success and failure)
  - Test timeout handling
  - Test output directory creation
  - Test `format_redirection_context()` produces correct context lines
  - Test file cleanup of old files
- [ ] **Task 1.2**: Implement `core/command_redirection.py`
  - `CommandRedirectionResult` dataclass
  - `execute_and_save()` function with subprocess + file write
  - `format_redirection_context()` helper
  - `cleanup_old_files()` for files > 1 hour old
- [ ] **Task 1.3**: Add constants
  - `COMMAND_REDIRECTION_DIR` name constant
  - Default timeout constant

### Phase 2: Retrofit gh_issue_comments (Proof of Concept)

- [ ] **Task 2.1**: Write failing tests for redirection in `gh_issue_comments`
  - Test: redirection enabled (default) → command executed, result includes file path
  - Test: redirection disabled → current blocking behaviour preserved
  - Test: command execution failure → graceful fallback to block-only
  - Test: `get_redirected_command()` returns corrected command string
- [ ] **Task 2.2**: Implement redirection in `GhIssueCommentsHandler`
  - Add `get_redirected_command(hook_input) -> str | None` method
  - Update `handle()` to call `execute_and_save()` when enabled
  - Return DENY with educational reason + redirection context
  - Fallback to block-only if execution fails
- [ ] **Task 2.3**: Run QA + daemon restart verification

### Phase 3: Retrofit npm_command + pipe_blocker

- [ ] **Task 3.1**: Write failing tests for `npm_command` redirection
- [ ] **Task 3.2**: Implement redirection in `NpmCommandHandler`
- [ ] **Task 3.3**: Write failing tests for `pipe_blocker` redirection
  - Pipe blocker redirect: strip pipe, run base command, save to file
- [ ] **Task 3.4**: Implement redirection in `PipeBlockerHandler`
- [ ] **Task 3.5**: Run QA + daemon restart verification

### Phase 4: Fix Plan Folder Redirection Bug (Side Mission)

- [ ] **Task 4.1**: Write failing test for `markdown_organization` plan write
  - Test: flat file write to `CLAUDE/Plan/name.md` should be DENIED
  - Test: numbered folder `CLAUDE/Plan/NNNNN-name/PLAN.md` should be created
  - Test: deny reason includes path to the created file
- [ ] **Task 4.2**: Fix `_handle_plan_mode_write()` to return `Decision.DENY`
  - Change return from ALLOW to DENY after creating the numbered folder
  - Include the correct file path in deny reason so Claude knows where to find it
- [ ] **Task 4.3**: Delete stale flat file `CLAUDE/Plan/snappy-greeting-cloud.md`
- [ ] **Task 4.4**: Run QA + daemon restart verification

### Phase 5: Config, Docs, Acceptance Tests

- [ ] **Task 5.1**: Update config files
  - `.claude/hooks-daemon.yaml` — add `command_redirection: true` to relevant handlers
  - `.claude/hooks-daemon.yaml.example` — same
- [ ] **Task 5.2**: Add acceptance tests to retrofitted handlers
- [ ] **Task 5.3**: Update handler reference docs
- [ ] **Task 5.4**: Run full QA + daemon restart + checkpoint commit

## Critical Files

- **New**: `src/claude_code_hooks_daemon/core/command_redirection.py`
- **New**: `tests/unit/core/test_command_redirection.py`
- **Modify**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/gh_issue_comments.py`
- **Modify**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/npm_command.py`
- **Modify**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/pipe_blocker.py`
- **Modify**: `tests/unit/handlers/pre_tool_use/test_gh_issue_comments.py`
- **Modify**: `tests/unit/handlers/pre_tool_use/test_npm_command.py`
- **Modify**: `tests/unit/handlers/pre_tool_use/test_pipe_blocker.py`
- **Modify**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/markdown_organization.py` (plan folder bug fix)
- **Modify**: `tests/unit/handlers/pre_tool_use/test_markdown_organization.py`
- **Delete**: `CLAUDE/Plan/snappy-greeting-cloud.md` (stale flat file from bug)
- **Modify**: `.claude/hooks-daemon.yaml`, `.claude/hooks-daemon.yaml.example`

## Reuse

- **Existing options pattern**: `getattr(self, "_command_redirection", True)` — same as `lsp_enforcement._mode`, `git_stash._mode`
- **Existing util**: `get_bash_command(hook_input)` from `core/utils.py`
- **Existing**: `ProjectContext.daemon_untracked_dir()` for output directory
- **Existing**: `suggested_command` computation in `gh_issue_comments.handle()`

## Verification

1. Unit tests: `pytest tests/unit/core/test_command_redirection.py -v`
2. Handler tests: `pytest tests/unit/handlers/pre_tool_use/test_gh_issue_comments.py -v`
3. Full QA: `./scripts/qa/llm_qa.py all`
4. Daemon restart: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart && status`
5. Live test: Run `gh issue view 1 --repo owner/repo` in Claude Code session, verify:
   - Command is blocked (educational message shown)
   - Output file exists at reported path
   - File contains the actual command output
   - Claude can read the file to get the result

## Success Criteria

- [ ] `gh issue view` without `--comments` is blocked AND result is available in one turn
- [ ] Toggle `command_redirection: false` restores block-only behaviour
- [ ] Subprocess timeout prevents hanging
- [ ] Old output files are cleaned up automatically
- [ ] All QA checks pass, daemon loads successfully

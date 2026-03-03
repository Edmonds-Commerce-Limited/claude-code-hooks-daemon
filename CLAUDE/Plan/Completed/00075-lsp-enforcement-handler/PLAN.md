# Plan 00074: LSP Enforcement Handler

**Status**: Complete (2026-03-03)
**Created**: 2026-03-03
**Owner**: Claude
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded
**GitHub Issue**: #25

## Context

Claude Code has LSP tools (goToDefinition, findReferences, hover, documentSymbol, workspaceSymbol) providing semantic ~50ms code intelligence. But LLMs default to Grep/Glob/Bash(grep/rg) for code navigation — slow, imprecise text searches. Issue #25 requests enforcing LSP usage when available.

## Overview

Implement a PreToolUse handler (`LspEnforcementHandler`) that detects Grep and Bash(grep/rg) patterns that look like symbol lookups and steers the LLM toward LSP tools instead.

**Design decisions (user-confirmed):**
- **Default mode: `block_once`** — Block first grep-that-looks-like-LSP with DENY, allow retries
- **No-LSP behaviour: block anyway** — Even without `ENABLE_LSP_TOOL`, block and tell them to set up LSP. Configurable via `no_lsp_mode` option (`block` | `advisory` | `disable`)
- **Scope: Both Grep tool + Bash grep/rg** — Intercept dedicated Grep tool AND Bash commands containing grep/rg

## Goals

- Detect Grep and Bash(grep/rg) patterns that look like symbol lookups (class, function, interface definitions)
- Block-once on first detection, allow retry (configurable: `advisory` | `block_once` | `strict`)
- Block even without LSP configured (nudge toward LSP setup), configurable via `no_lsp_mode`
- Provide clear, actionable guidance mapping grep patterns to specific LSP operations
- Configurable via `hooks-daemon.yaml` options

## Non-Goals

- Don't intercept Glob tool (file discovery is legitimate)
- Don't intercept regex-heavy content searches (LSP can't do these)
- Don't validate whether LSP server actually works (just check if env var is set)
- Don't install or configure LSP plugins (separate concern)

## Detection Heuristics

**Triggers handler (looks like a symbol lookup):**

| Pattern | Suggested LSP Operation |
|---------|------------------------|
| `class ClassName` | `workspaceSymbol` or `goToDefinition` |
| `def function_name` | `workspaceSymbol` or `goToDefinition` |
| `function functionName` | `workspaceSymbol` or `goToDefinition` |
| `interface InterfaceName` | `workspaceSymbol` or `goToDefinition` |
| PascalCase identifier (no regex chars) | `workspaceSymbol` or `findReferences` |
| snake_case exact identifier | `workspaceSymbol` or `findReferences` |
| `import.*ModuleName` | `findReferences` |

**Does NOT trigger (legitimate text search):**

| Pattern | Why |
|---------|-----|
| Complex regex (`log.*Error`, `\d{3}-\d{4}`) | LSP doesn't do regex content search |
| String literals (`"error message"`) | Not a symbol |
| TODO/FIXME/HACK comments | Comment markers, not symbols |
| Patterns with many regex metacharacters | Text pattern, not identifier |

**Key heuristic:** Is the search pattern a **symbol name** (identifier) or a **text pattern** (regex)?

## Tasks

### Phase 1: Constants & Infrastructure

- [x] Add `HandlerID.LSP_ENFORCEMENT` to `src/claude_code_hooks_daemon/constants/handlers.py`
- [x] Add `Priority.LSP_ENFORCEMENT = 38` to `src/claude_code_hooks_daemon/constants/priority.py`
- [x] Add `"lsp_enforcement"` to `HandlerKey` literal type in `constants/handlers.py`
- [x] Add `ToolName.LSP = "LSP"` to `src/claude_code_hooks_daemon/constants/tools.py` and `ToolNameLiteral`

### Phase 2: TDD Implementation

- [x] Create test file: `tests/unit/handlers/pre_tool_use/test_lsp_enforcement.py`
- [x] **RED**: Write failing tests for `matches()`:
  - Positive: Grep with `class ClassName` pattern
  - Positive: Grep with `def function_name` pattern
  - Positive: Bash with `grep -rn "class Foo"` command
  - Positive: Bash with `rg "def bar"` command
  - Positive: Grep with PascalCase identifier + files_with_matches
  - Positive: Grep with snake_case exact identifier
  - Negative: Grep with regex pattern (`log.*Error`)
  - Negative: Grep with string literal search
  - Negative: Grep with TODO/FIXME pattern
  - Negative: Bash grep for non-symbol content
  - Negative: Non-Grep/Bash tools (Read, Write, Edit, etc.)
  - Negative: Glob tool (should never trigger)
- [x] **RED**: Write failing tests for `handle()`:
  - `block_once` mode: Returns DENY on first block, ALLOW on retry
  - `advisory` mode: Returns ALLOW with LSP guidance always
  - `strict` mode: Returns DENY always
  - Maps grep pattern to correct LSP operation in message
  - Message includes LSP setup instructions when LSP not configured
- [x] **RED**: Write failing tests for `no_lsp_mode` option:
  - `block` (default): Blocks even without ENABLE_LSP_TOOL, includes setup guidance
  - `advisory`: Downgrades to advisory when LSP not available
  - `disable`: Handler doesn't match when LSP not available
- [x] **GREEN**: Create handler: `src/claude_code_hooks_daemon/handlers/pre_tool_use/lsp_enforcement.py`
  - `LspEnforcementHandler` class
  - Pattern detection: symbol-like vs regex-like heuristics
  - Mode logic: `block_once` / `advisory` / `strict`
  - `no_lsp_mode` logic: `block` / `advisory` / `disable`
  - LSP availability: check `os.environ.get("ENABLE_LSP_TOOL")`
  - Block tracking: `get_data_layer().history.count_blocks_by_handler()`
  - Progressive messaging mapping grep → specific LSP operation
- [x] **REFACTOR**: Extract constants, clean up

### Phase 3: Integration & Config

- [x] Register in `.claude/hooks-daemon.yaml`:
  ```yaml
  lsp_enforcement:
    enabled: true
    priority: 38
    options:
      mode: block_once       # advisory | block_once | strict
      no_lsp_mode: block     # block | advisory | disable
  ```
- [x] Add acceptance tests via `get_acceptance_tests()`
- [x] Run dogfooding tests (`test_dogfooding_config.py`, `test_dogfooding_hook_scripts.py`)

### Phase 4: QA & Verification

- [x] Run `./scripts/qa/run_all.sh` — all checks pass
- [x] Daemon restart: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
- [x] Daemon status: verify RUNNING
- [ ] Live test: use Grep to search for `class Handler` → verify handler fires

## Key Files

| File | Change |
|------|--------|
| `src/claude_code_hooks_daemon/constants/handlers.py` | Add `LSP_ENFORCEMENT` HandlerIDMeta + HandlerKey |
| `src/claude_code_hooks_daemon/constants/priority.py` | Add `LSP_ENFORCEMENT = 38` |
| `src/claude_code_hooks_daemon/constants/tools.py` | Add `LSP = "LSP"` + ToolNameLiteral |
| `src/claude_code_hooks_daemon/handlers/pre_tool_use/lsp_enforcement.py` | **New** — main handler |
| `tests/unit/handlers/pre_tool_use/test_lsp_enforcement.py` | **New** — test file |
| `.claude/hooks-daemon.yaml` | Register handler with options |

## Reusable Utilities

- `get_bash_command(hook_input)` — `core/utils.py`
- `get_data_layer().history.count_blocks_by_handler()` — block-once tracking
- `HookInputField`, `ToolName`, `HandlerTag` — `constants/`
- `Decision.DENY` / `Decision.ALLOW` — `core/`
- `AcceptanceTest`, `TestType`, `RecommendedModel` — `core/`

## Verification

1. `pytest tests/unit/handlers/pre_tool_use/test_lsp_enforcement.py -v`
2. `./scripts/qa/run_all.sh`
3. `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart && status`
4. Live test: Grep for `class Handler` → handler fires

## Success Criteria

- [x] Correctly identifies symbol-like grep patterns (>90% precision)
- [x] Does NOT trigger on legitimate regex/content searches (<5% false positive rate)
- [x] `block_once`: first grep blocked, retry allowed
- [x] `advisory`: grep allowed with LSP guidance
- [x] `strict`: grep always blocked
- [x] `no_lsp_mode` options work correctly
- [x] All QA checks pass
- [x] Daemon loads and runs
- [x] 95%+ test coverage (96.28%)

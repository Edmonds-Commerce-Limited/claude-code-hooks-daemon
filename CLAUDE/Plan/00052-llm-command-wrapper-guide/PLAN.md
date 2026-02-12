# Plan 052: LLM Command Wrapper Guide & Handler Integration

**Status**: Not Started
**Created**: 2026-02-12
**Owner**: TBD
**Priority**: Medium
**Estimated Effort**: 3-4 hours

## Overview

The `llm:` prefixed command pattern (minimal stdout, structured JSON to file, JQ-optimizable) currently exists only as inline text in the NPM handler's deny/advisory messages. This pattern is **language-agnostic** and applies to any ecosystem with QA tools that generate verbose stdout (ESLint, pytest, PHPStan, Go vet, RuboCop, etc.).

This plan creates:
1. A comprehensive, language-agnostic guide file shipped with the daemon
2. Updated handler advisory messages that reference the guide instead of inlining advice
3. The guide serves as a detailed prompt that LLMs can read to implement wrappers in any language

## Goals

- Create a detailed guide document explaining the LLM command wrapper pattern
- Make the guide language-agnostic with examples for multiple ecosystems
- Ship the guide as part of the daemon (always available at a known path)
- Update NPM advisory handler to point to the guide file
- Enable any handler (current or future) to reference the same guide
- Include JSON schema conventions, JQ examples, and naming patterns

## Non-Goals

- Implementing actual LLM command wrappers for specific projects
- Auto-generating wrapper scripts
- Creating language-specific guides (one guide covers all languages)
- Changing the blocking/advisory logic of handlers

## Context & Background

### The LLM Command Philosophy

Traditional QA tools (ESLint, pytest, PHPStan, etc.) produce verbose human-readable stdout:
- Coloured output, progress bars, decorative formatting
- Hundreds of lines for large codebases
- Hard to parse programmatically
- Wastes LLM context tokens

LLM-flavoured commands solve this:
- **Minimal stdout**: Pass/fail status, summary counts, file path to detailed output
- **Structured JSON file**: Full machine-readable results in `./var/qa/*.json`
- **JQ-optimizable**: JSON structure designed for common jq queries
- **Schema documented**: JSON schema or example jq commands in the stdout itself

### Example Pattern

**Traditional command:**
```bash
npm run lint
# 500 lines of coloured ESLint output eating context tokens
```

**LLM command:**
```bash
npm run llm:lint
# stdout (3 lines):
# ✅ 45 files checked, 0 errors, 3 warnings
# Details: ./var/qa/eslint-cache.json
# Query: jq '.[] | select(.errorCount > 0)' ./var/qa/eslint-cache.json
```

### Why a Guide File?

1. **Advisory messages are too short** for the full pattern explanation
2. **Multiple handlers** need to reference the same pattern (NPM, ESLint, future PHP/Python handlers)
3. **LLMs can read the guide** when asked to implement wrappers - it serves as a detailed prompt
4. **Single source of truth** - update once, all handlers benefit
5. **Ships with the daemon** - always available at a known filesystem path

## Technical Design

### Guide File Location

```
src/claude_code_hooks_daemon/guides/llm-command-wrappers.md
```

This location:
- Ships with the daemon package (inside src/)
- Accessible via `importlib.resources` or known path
- Can be referenced by handlers via a constant

Alternative considered: `CLAUDE/guides/` - but that's project documentation, not daemon-shipped content. The guide needs to be available in any project that installs the daemon.

### Guide Contents (Outline)

```markdown
# LLM Command Wrappers - Implementation Guide

## Philosophy
- Why LLM-flavoured commands exist
- Token efficiency: 3 lines vs 500 lines
- Parseability: JSON + jq vs regex on coloured text
- Separation: human commands stay, LLM commands added alongside

## The Pattern
### Naming Convention
- npm: `llm:lint`, `llm:test`, `llm:typecheck`
- Makefile: `llm-lint`, `llm-test`, `llm-typecheck`
- Composer: `llm:analyse`, `llm:test`
- General: prefix with `llm:` or `llm-` depending on ecosystem

### Stdout Contract (3-5 lines max)
Line 1: Status emoji + summary (pass/fail + counts)
Line 2: Detail file path
Line 3: Example jq command for common query
Line 4 (optional): JSON schema location or inline hint

### JSON Output Contract
- Output to: `./var/qa/{tool}-cache.json`
- Structure: Array of result objects (or tool-specific schema)
- Must be valid JSON (no trailing commas, no comments)
- Optimized for jq: flat where possible, arrays for iteration

### Example Stdout
```
✅ 45 files checked, 0 errors, 3 warnings
Details: ./var/qa/eslint-cache.json
Query: jq '.[] | select(.errorCount > 0) | {file: .filePath, errors: .messages}' ./var/qa/eslint-cache.json
```

## Language-Specific Examples

### JavaScript/TypeScript (npm scripts in package.json)
- ESLint: `"llm:lint": "eslint . --format json -o ./var/qa/eslint-cache.json && echo ..."`
- Jest: `"llm:test": "jest --json --outputFile=./var/qa/jest-results.json && echo ..."`
- TypeScript: `"llm:typecheck": "tsc --noEmit 2>&1 | ..."`

### Python (Makefile or pyproject.toml scripts)
- pytest: Output JSON via `--json-report`, summary to stdout
- mypy: Output JSON via custom formatter, summary to stdout
- ruff: `ruff check --output-format json > ./var/qa/ruff-cache.json`

### PHP (Composer scripts)
- PHPStan: `"llm:analyse": "phpstan analyse --error-format=json > ./var/qa/phpstan-cache.json && echo ..."`
- PHPUnit: JSON log output + summary
- PHP-CS-Fixer: `--format=json` output

### Go
- go vet / golangci-lint: JSON output modes
- go test: `-json` flag for structured output

### Ruby
- RuboCop: `--format json` flag

## Common jq Patterns
- Filter errors only: `jq '.[] | select(.severity == "error")'`
- Count by file: `jq 'group_by(.file) | map({file: .[0].file, count: length})'`
- Extract messages: `jq '.[].messages[] | .message'`

## Directory Convention
```
./var/qa/
  eslint-cache.json
  jest-results.json
  mypy-cache.json
  phpstan-cache.json
  ruff-cache.json
```
- `var/` is gitignored (ephemeral build artifacts)
- `qa/` subdirectory keeps QA tools separate from other var data
- `-cache` suffix indicates regeneratable data
```

### Handler Integration

Update the NPM advisory handler to reference the guide:

```python
# In advisory message when llm: commands don't exist
guide_path = _get_guide_path()  # Resolves to installed location
context = (
    f"Consider creating llm: prefixed npm commands for better LLM integration.\n"
    f"Guide: {guide_path}\n"
    f"Read the guide for the full pattern: minimal stdout, JSON to ./var/qa/, jq queries."
)
```

### Utility for Guide Path Resolution

```python
# src/claude_code_hooks_daemon/utils/guides.py
def get_llm_command_guide_path() -> str:
    """Return filesystem path to the LLM command wrapper guide."""
    # Use importlib.resources or __file__-relative path
```

## Tasks

### Phase 1: Write the Guide

- [ ] **Create guide file**
  - [ ] Create `src/claude_code_hooks_daemon/guides/` directory
  - [ ] Create `__init__.py` for package
  - [ ] Write `llm-command-wrappers.md` with full content
  - [ ] Cover philosophy, pattern, naming, stdout contract, JSON contract
  - [ ] Add examples for: JavaScript, Python, PHP, Go, Ruby
  - [ ] Add common jq patterns section
  - [ ] Add directory convention section

### Phase 2: Guide Path Resolution

- [ ] **Create utility for guide path**
  - [ ] Write tests for `get_llm_command_guide_path()`
  - [ ] Implement using `__file__`-relative path (simplest, works in dev and installed)
  - [ ] Add constant for guide filename

### Phase 3: Update NPM Advisory Handler

- [ ] **Update advisory messages**
  - [ ] Modify NpmCommandHandler advisory to reference guide path
  - [ ] Modify ValidateEslintOnWriteHandler advisory to reference guide path
  - [ ] Keep inline summary but add "Full guide: {path}" line
  - [ ] Update tests for new message format

### Phase 4: QA & Verification

- [ ] **Run full QA suite**: `./scripts/qa/run_all.sh`
- [ ] **Restart daemon**: verify loads successfully
- [ ] **Live testing**: verify advisory shows guide path
- [ ] **Verify guide is readable**: confirm file exists at resolved path

## Dependencies

- Plan 049 (Complete) - NPM advisory mode must exist first

## Technical Decisions

### Decision 1: Guide Location - Inside src/ Package

**Context**: Where should the guide file live?

**Options Considered**:
1. **`CLAUDE/guides/`** - Project documentation directory
2. **`src/claude_code_hooks_daemon/guides/`** - Inside the Python package
3. **`docs/guides/`** - Human documentation directory
4. **`.claude/hooks-daemon/guides/`** - Install directory

**Decision**: Option 2 - Inside the Python package

**Rationale**:
- Ships with the daemon in any installation (not just this repo)
- Accessible via `__file__`-relative path or `importlib.resources`
- Part of the codebase, version-controlled
- Can be referenced by handlers without knowing install location
- `CLAUDE/` is for project-specific docs, not daemon-shipped content

### Decision 2: Guide Format - Markdown

**Context**: What format for the guide?

**Decision**: Markdown (`.md`)

**Rationale**:
- LLMs parse markdown natively
- Readable by humans too
- Code blocks render nicely
- No special tooling needed to read
- Consistent with project documentation style

### Decision 3: Reference by Path, Not Inline

**Context**: Should handlers inline the guide content or reference it?

**Decision**: Reference by filesystem path

**Rationale**:
- Guide may be 200+ lines - too long to inline in advisory context
- Path reference is 1 line, LLM can Read the file if interested
- Guide updates don't require handler changes
- Multiple handlers can reference the same guide
- LLMs are excellent at following "read this file" instructions

## Success Criteria

- [ ] Guide file exists and covers 5+ language ecosystems
- [ ] Guide explains the full pattern (philosophy, stdout contract, JSON contract, jq)
- [ ] Guide is accessible via utility function from any handler
- [ ] NPM advisory handler references guide path
- [ ] Full QA suite passes
- [ ] Daemon loads successfully
- [ ] Guide is readable and useful when an LLM reads it

## Future Phase: Standalone Wrapper Repository

**Status**: Deferred (separate project, tackle after daemon guide is done)

### Concept

A standalone GitHub repo of ready-made LLM command wrapper scripts - one per tool. Users grab individual scripts via raw URL rather than cloning the whole repo.

```
llm-command-wrappers/
  eslint/
    llm-lint.sh          # The wrapper script
    schema.json          # JSON output schema
    README.md            # Usage + example jq queries
  pytest/
    llm-test.sh
    schema.json
    README.md
  phpstan/
    llm-analyse.sh
    schema.json
    README.md
  ruff/
    llm-lint.sh
    ...
```

**Usage**: `curl -O https://raw.githubusercontent.com/.../eslint/llm-lint.sh`

### Implementation Language Considerations

JSON generation in bash is fragile. Wrapper scripts need a real language. Options:

| Language | Availability Assumption | Pros | Cons |
|----------|------------------------|------|------|
| **Node.js** | Claude Code users always have it | Native JSON, cross-platform | Not available in non-Node projects without Claude Code |
| **Python 3.11+** | Hooks daemon requires it | Native JSON, always available if daemon installed | Version fragmentation on some systems |
| **The tool's own language** | By definition available | Natural fit, no extra dependency | Different language per wrapper, inconsistent |

**Recommended approach**: Each wrapper checks what's available:
1. If it's a language-specific tool (e.g., pytest), use that language (Python)
2. If Node is available (Claude Code context), use Node for the JSON bits
3. Fallback: Python 3.11+ (daemon dependency guarantees it)

### Per-Tool Considerations

For each tool, check:
1. **Does it have native JSON output?** (e.g., `eslint --format json`, `pytest --json-report`, `ruff --output-format json`)
   - If yes: wrapper is thin (just redirects JSON to file + summarises)
   - If no: wrapper must parse text output and generate JSON (needs real language)
2. **What's the output structure?** Define a schema per tool
3. **What are the common jq queries?** Document per tool
4. **Version compatibility** - which tool versions support JSON output?

### Repo Structure

Each tool directory is self-contained:
- `llm-{action}.sh` - Entry point (thin shell that delegates to language-specific logic)
- `schema.json` - JSON Schema for the output format
- `README.md` - Usage, jq examples, version requirements
- Optional: `llm-{action}.py` or `llm-{action}.js` for the heavy lifting

### Action Items (When We Get To This)

- [ ] Create GitHub repo `llm-command-wrappers`
- [ ] Define the wrapper contract (stdout format, JSON contract, exit codes)
- [ ] Audit popular tools for native JSON output support
- [ ] Implement first batch: ESLint, pytest, ruff, mypy, PHPStan
- [ ] Update daemon guide (Plan 052 Phase 1) to reference the repo
- [ ] Update NPM advisory handler to link to specific wrapper scripts

## Notes & Updates

### 2026-02-12
- Plan created based on user insight: the llm: command pattern is language-agnostic
- Key idea: ship a detailed guide as a prompt file that LLMs can read to implement wrappers
- Guide lives in the daemon package so it's available everywhere the daemon is installed
- Handlers reference the guide by path instead of inlining verbose advice
- Added future phase: standalone repo of ready-made wrapper scripts (grab individually via raw URL)
- Language choice: use the tool's own language where possible, Node for Claude Code context, Python 3.11+ as fallback
- Each tool needs audit for native JSON output support before writing wrapper

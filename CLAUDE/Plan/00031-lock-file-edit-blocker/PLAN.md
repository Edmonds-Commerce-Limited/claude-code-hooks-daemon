# Plan 00031: Lock File Edit Blocker Handler

**Status**: Not Started
**Created**: 2026-02-06
**Owner**: To be assigned
**Type**: Handler Implementation
**Event Type**: PreToolUse
**Priority**: 10 (Safety - critical protection)
**GitHub Issue**: #19

## Overview

Lock files from package managers should NEVER be directly edited. They must only be modified through the proper package manager commands. Direct editing can lead to inconsistent dependency resolution, broken package installations, hash/checksum mismatches, version conflicts, and build failures.

This plan implements a PreToolUse handler that blocks direct editing of lock files across all major language ecosystems (PHP, JavaScript, Python, Ruby, Rust, Go, .NET, Swift). The handler will intercept Write and Edit tool calls targeting lock files and block them with clear educational messages about proper package manager usage.

This is a safety-critical handler that prevents data corruption and protects build integrity, similar to the existing DestructiveGitHandler and SedBlockerHandler.

## Goals

- Block direct editing of all major package manager lock files
- Intercept Write and Edit tools when targeting lock file paths
- Provide clear error messages explaining why editing is blocked
- Educate users about proper package manager commands
- Maintain 95%+ test coverage with comprehensive TDD approach
- Support all major language ecosystems (14+ lock file types)

## Non-Goals

- Block read operations on lock files (reading is safe)
- Block package manager commands themselves (these are correct way to update)
- Validate lock file contents (only prevent direct edits)
- Track lock file versions or changes
- Handle language-specific configuration files (only lock files)

## Context & Background

Lock files are generated artifacts that capture exact dependency versions and checksums. They ensure reproducible builds across environments. Direct editing breaks these guarantees because:

1. **Hash mismatches**: Manually edited entries won't match package checksums
2. **Dependency resolution**: Lock files represent solved dependency graphs
3. **Version conflicts**: Manual edits can create impossible version constraints
4. **Build failures**: Corrupted lock files cause CI/CD failures

This handler follows the same safety pattern as:
- `DestructiveGitHandler` (priority 10, terminal=true)
- `SedBlockerHandler` (priority 10, terminal=true)

**Related Handlers**: Both handlers block operations that can cause irreversible data corruption.

## Debug Analysis

**Before implementation**, capture event flow using debug script:

```bash
./scripts/debug_hooks.sh start "Testing lock file write/edit scenarios"
# Test scenarios:
# 1. Edit package-lock.json with Edit tool
# 2. Write to composer.lock with Write tool
# 3. Edit Cargo.lock
# 4. Write to poetry.lock
./scripts/debug_hooks.sh stop
```

**Expected Event Analysis**:
- **Event Type**: PreToolUse
- **Tool Names**: Write, Edit
- **Key hook_input fields**:
  - `tool_name`: "Write" or "Edit"
  - `tool_input.file_path`: Path to lock file
  - `tool_input.content`: New file content (for Write)
  - `tool_input.edits`: Edit operations (for Edit)

**Trigger Pattern**:
- Match when `file_path` ends with any protected lock file name
- Both absolute and relative paths must be handled
- Case-insensitive matching (some systems use different cases)

## Lock File Specifications

### Protected Lock Files (14 types across 8 ecosystems)

**PHP/Composer:**
- `composer.lock` - Composer dependency lock file

**JavaScript/Node:**
- `package-lock.json` - npm lock file
- `yarn.lock` - Yarn lock file
- `pnpm-lock.yaml` - pnpm lock file
- `bun.lockb` - Bun binary lock file

**Python:**
- `poetry.lock` - Poetry lock file
- `Pipfile.lock` - Pipenv lock file
- `pdm.lock` - PDM lock file

**Ruby:**
- `Gemfile.lock` - Bundler lock file

**Rust:**
- `Cargo.lock` - Cargo lock file

**Go:**
- `go.sum` - Go modules checksum file

**.NET:**
- `packages.lock.json` - NuGet lock file
- `project.assets.json` - MSBuild assets file

**Swift:**
- `Package.resolved` - Swift Package Manager resolved file

### Proper Usage Commands

- PHP: `composer install`, `composer update`
- npm: `npm install`, `npm update`
- Yarn: `yarn install`, `yarn upgrade`
- pnpm: `pnpm install`, `pnpm update`
- Bun: `bun install`, `bun update`
- Poetry: `poetry install`, `poetry update`
- Pipenv: `pipenv install`, `pipenv update`
- PDM: `pdm install`, `pdm update`
- Bundler: `bundle install`, `bundle update`
- Cargo: `cargo update`
- Go: `go get`, `go mod tidy`
- NuGet: `dotnet restore`
- Swift: `swift package update`

## Tasks

### Phase 1: Debug & Design
- [ ] ⬜ Run debug script for lock file scenarios
- [ ] ⬜ Analyze captured events and document findings
- [ ] ⬜ Design handler matching logic with pattern list
- [ ] ⬜ Determine handler configuration (priority, tags, terminal)

### Phase 2: TDD Implementation
- [ ] ⬜ RED: Write failing initialization tests
- [ ] ⬜ RED: Write failing matches() tests (positive and negative)
- [ ] ⬜ RED: Write failing handle() tests
- [ ] ⬜ RED: Write failing edge case tests
- [ ] ⬜ GREEN: Implement handler to pass all tests
- [ ] ⬜ REFACTOR: Clean up code and verify coverage
- [ ] ⬜ Verify 95%+ test coverage maintained

### Phase 3: Integration & Testing
- [ ] ⬜ Add integration test to response validation suite
- [ ] ⬜ Register handler in `.claude/hooks-daemon.yaml`
- [ ] ⬜ **CRITICAL**: Restart daemon and verify successful load
- [ ] ⬜ Run dogfooding tests to verify config completeness
- [ ] ⬜ Run full QA suite: `./scripts/qa/run_all.sh`
- [ ] ⬜ Add acceptance tests to PLAYBOOK.md
- [ ] ⬜ Live testing in Claude Code session
- [ ] ⬜ Update documentation (handler count in CLAUDE.md)

## Success Criteria

- [ ] Handler correctly blocks Write/Edit on all 14 lock file types
- [ ] Handler allows Read operations (doesn't match)
- [ ] Handler allows package manager commands (Bash not intercepted)
- [ ] Error messages include specific package manager guidance
- [ ] All unit tests passing with 95%+ coverage
- [ ] Integration tests passing
- [ ] Daemon restarts successfully with handler loaded
- [ ] Full QA suite passes (all 7 checks)
- [ ] Acceptance tests pass in live Claude Code
- [ ] No false positives (non-lock files allowed)
- [ ] No false negatives (all lock files blocked)

## Dependencies

- **GitHub Issue**: #19
- **Related Handlers**: DestructiveGitHandler, SedBlockerHandler
- **Depends on**: None (standalone handler)
- **Blocks**: None

## Technical Decisions

### Decision 1: Priority Level = 10 (Safety)
**Context**: Need to determine execution priority for lock file blocker.

**Decision**: Priority 10 (safety category)

**Rationale**: Lock file corruption is a safety issue preventing builds and destroying reproducibility. Aligns with destructive_git (10) and sed_blocker (10) which also prevent data corruption. Safety handlers run early to prevent irreversible damage.

**Date**: 2026-02-06

### Decision 2: Terminal = true
**Context**: Should handler stop dispatch chain or allow other handlers to run?

**Decision**: terminal=true

**Rationale**: Once we detect lock file editing, we must block it completely. No scenario where accumulating additional context is valuable. Matches DestructiveGitHandler and SedBlockerHandler patterns.

**Date**: 2026-02-06

### Decision 3: Case-Insensitive Matching
**Context**: Should lock file matching be case-sensitive?

**Decision**: Case-insensitive matching

**Rationale**: Some filesystems and tools may create lock files with different casing (e.g., "Cargo.LOCK"). Performance impact is negligible (simple string comparison), and false negatives would be catastrophic.

**Date**: 2026-02-06

### Decision 4: Intercept Write + Edit Only
**Context**: Which Claude Code tools should trigger the handler?

**Decision**: Write and Edit tools only

**Rationale**: Lock files should never be modified by Write or Edit tools. Bash tool is excluded because package manager commands run through Bash and must be allowed.

**Date**: 2026-02-06

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| False positives block legitimate files | Medium | Low | Strict pattern matching on known lock file names only |
| Missing new lock file formats | Low | Medium | Document how to add new formats; extensible design |
| Package manager commands blocked | High | Low | Only intercept Write/Edit, not Bash tool |
| Handler initialization fails | High | Low | Daemon load verification catches this; fail fast |
| Import errors break daemon | High | Low | TDD + daemon restart verification mandatory |

## Notes & Updates

### 2026-02-06
- Plan created based on GitHub Issue #19
- Following Handler Implementation Plan template from PlanWorkflow.md
- Priority aligned with similar safety handlers (10)
- Terminal=true for complete blocking
- 14 lock file types across 8 ecosystems identified

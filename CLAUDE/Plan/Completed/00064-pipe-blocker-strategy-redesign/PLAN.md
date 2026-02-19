# Plan 00064: Redesign PipeBlockerHandler with Three-Tier Language-Aware Strategy Pattern

**Status**: Complete (2026-02-19)
**Created**: 2026-02-19
**Owner**: TBD
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

The current `PipeBlockerHandler` is over-eager — it blocks any command piped to tail/head that isn't in a hard-coded whitelist (grep, awk, jq, etc.). This produces noisy blocks for cheap commands like `git tag | tail` and provides no useful guidance for project-specific customization.

The fix introduces a three-tier decision system backed by a new `pipe_blocker` strategy domain:
1. **Whitelist** (never block) — cheap/filtering commands, regex-based, project-extensible
2. **Blacklist** (always block, language-aware) — expensive test runners, build tools, QA tools
3. **Unknown** (block with config instructions) — anything not in either list

This establishes a fourth Strategy Pattern archetype for **command-name-based matching**, distinct from the existing file-extension-based archetypes (lint, tdd, qa_suppression).

## Goals

- Replace over-eager whitelist-only logic with three-tier whitelist/blacklist/unknown system
- Add language-aware blacklists (pytest, npm test, cargo build, etc.) using Strategy Pattern
- Provide actionable config instructions when blocking unknown commands
- Establish new archetype: command-name-keyed strategies (vs file-extension-keyed)
- Integrate with `daemon.languages` config for project-level language filtering

## Non-Goals

- No changes to pipe detection logic (the `| tail/head` regex)
- No changes to handler priority or event type
- Not extracting ALL piping logic — only tail/head truncation prevention

## Context & Background

### Three-Tier Decision Flow

```
Source command segment (full text before pipe to tail/head)
        │
        ▼
┌─────────────────────────────┐
│  1. Matches whitelist?      │ → ALLOW  (grep, awk, jq, git tag, ls, etc.)
└─────────────────────────────┘
        │ No
        ▼
┌─────────────────────────────┐
│  2. Matches blacklist?      │ → DENY: "expensive command, use temp file"
│     (language-aware)        │
└─────────────────────────────┘
        │ No
        ▼
┌─────────────────────────────┐
│  3. Unknown command         │ → DENY: "unrecognized, add to config"
└─────────────────────────────┘
```

### Key Architectural Difference from Existing Archetypes

Existing archetypes map **file extensions → strategies**.
Pipe blocker maps **language names → blacklist regex patterns**, merged into a flat pattern list. The handler matches against the **full source command segment** (not just first word), enabling multi-word patterns like `^npm\s+test\b` or `^go\s+build\b`.

### Language Filtering Behaviour

| `daemon.languages` config | Active blacklists |
|--------------------------|-------------------|
| `null` (not set) | ALL language strategies + Universal |
| `["Python"]` | Python + Universal only |
| `["Python", "Go"]` | Python + Go + Universal only |

Universal strategy is **always active** (never filtered out by language filter).

## Tasks

### Phase 1: Strategy Infrastructure (TDD)

- [ ] **Task 1.1**: Create `strategies/pipe_blocker/` directory structure
  - [ ] Write failing tests for `common.py` (whitelist constants, `matches_whitelist()` helper)
  - [ ] Implement `common.py` with `UNIVERSAL_WHITELIST_PATTERNS` and helper
  - [ ] Write failing tests for `protocol.py` (structural typing check)
  - [ ] Implement `protocol.py` with `PipeBlockerStrategy` Protocol
  - [ ] Write failing tests for `registry.py` (register, get_blacklist_patterns, filter_by_languages)
  - [ ] Implement `registry.py` with `PipeBlockerStrategyRegistry`
  - [ ] Create `__init__.py` exporting public API
  - [ ] Run: `pytest tests/unit/strategies/pipe_blocker/` (must pass)

### Phase 2: Language Strategies (TDD — one strategy at a time)

- [ ] **Task 2.1**: Implement `universal_strategy.py` (make, cmake, docker build, kubectl, terraform, helm, ansible-playbook)
- [ ] **Task 2.2**: Implement `python_strategy.py` (pytest, mypy, ruff check, black, bandit, coverage, tox, pylint, flake8)
- [ ] **Task 2.3**: Implement `javascript_strategy.py` (npm test/run/build/audit, jest, vitest, eslint, tsc, webpack, vite build, yarn test/build)
- [ ] **Task 2.4**: Implement `shell_strategy.py` (shellcheck)
- [ ] **Task 2.5**: Implement `go_strategy.py` (go test, go build, go vet)
- [ ] **Task 2.6**: Implement `rust_strategy.py` (cargo test/build/check/clippy)
- [ ] **Task 2.7**: Implement `java_strategy.py` (mvn, gradle, ./gradlew, javac)
- [ ] **Task 2.8**: Implement `ruby_strategy.py` (rspec, rubocop, rake, bundle exec)

Each strategy task follows TDD: write failing test → implement → register in `registry.py` → verify tests pass.

### Phase 3: Handler Redesign (TDD)

- [ ] **Task 3.1**: Write failing tests for new three-tier handler logic
  - Whitelist matches → ALLOW
  - Blacklist matches → DENY with "expensive command" message
  - Unknown → DENY with "add to config" message
  - Language filtering via `_apply_language_filter()`
  - `extra_whitelist` / `extra_blacklist` config options work
- [ ] **Task 3.2**: Implement handler redesign
  - Replace `_extract_source_command()` → `_extract_source_segment()` (returns full segment for multi-word matching)
  - Add `_matches_whitelist()` and `_matches_blacklist()` using regex compilation
  - Add `_apply_language_filter()` (identical pattern to `LintOnEditHandler`)
  - Replace three-verbosity messages with two-type messages (blacklisted vs unknown)
  - Add `_languages: list[str] | None` and `_languages_applied: bool` attrs
  - Remove old `allowed_pipe_sources` option; add `extra_whitelist` / `extra_blacklist`
- [ ] **Task 3.3**: Update `get_acceptance_tests()` — add tests for blacklisted and unknown paths

### Phase 4: Update Existing Tests

- [ ] **Task 4.1**: Update `tests/unit/handlers/test_pipe_blocker.py` for three-tier expectations
  - `ls` is now whitelisted (no longer blocks)
  - `find` is now unknown (different block message)
  - `pytest` is now blacklisted (different block message)
  - Progressive verbosity tests → remove (replaced by type-based messages)
- [ ] **Task 4.2**: Update `tests/unit/handlers/pre_tool_use/test_pipe_blocker_bug.py`
  - `ls | tail` → now ALLOW (whitelisted), update test expectation
  - `find | tail` → still DENY but as unknown (update message pattern assertion)
- [ ] **Task 4.3**: Update/expand `tests/integration/test_pipe_blocker_integration.py`
  - Add blacklist path test (e.g., `pytest | tail`)
  - Add unknown path test (e.g., `my_script.sh | tail`)
- [ ] **Task 4.4**: Update `src/claude_code_hooks_daemon/strategies/__init__.py` to export pipe_blocker

### Phase 5: Config + Docs Update

- [ ] **Task 5.1**: Update `.claude/hooks-daemon.yaml` pipe_blocker section with `extra_whitelist`/`extra_blacklist` comments
- [ ] **Task 5.2**: Create `strategies/pipe_blocker/CLAUDE.md` archetype documentation

### Phase 6: QA + Daemon Verification

- [ ] **Task 6.1**: Run full QA suite: `./scripts/qa/run_all.sh` (all 8 checks must pass)
- [ ] **Task 6.2**: Daemon restart verification:
  ```bash
  $PYTHON -m claude_code_hooks_daemon.daemon.cli restart
  $PYTHON -m claude_code_hooks_daemon.daemon.cli status  # Expected: RUNNING
  ```
- [ ] **Task 6.3**: Checkpoint commit

## Technical Decisions

### Decision 1: Command-Name-Keyed Registry (not extension-keyed)
**Context**: Existing registries map file extensions to strategies. Pipe blocker operates on Bash commands, not files.
**Decision**: Registry keyed by `language_name` string. `get_blacklist_patterns()` merges all active strategies' patterns into a flat tuple for efficient matching.

### Decision 2: Full Segment Matching (not first-word matching)
**Context**: Current handler extracts only the first word (`git` from `git tag -l`). This prevents multi-word patterns.
**Decision**: `_extract_source_segment()` returns the full trimmed command segment before the pipe, enabling patterns like `^git\s+tag\b`, `^npm\s+test\b`, `^go\s+build\b`.

### Decision 3: Whitelist is Universal (not language-stratified)
**Context**: Whitelist commands (grep, ls, git tag) are safe regardless of project language.
**Decision**: `UNIVERSAL_WHITELIST_PATTERNS` in `common.py` — not in strategies. Language-specific whitelist additions go via `extra_whitelist` in project config.

### Decision 4: Universal Strategy Always Active
**Context**: Docker, make, cmake, terraform are expensive regardless of project language.
**Decision**: `filter_by_languages()` always keeps `"Universal"` in `_strategies` dict. All other strategies are removed if not in active language list.

### Decision 5: Remove Progressive Verbosity
**Context**: Progressive verbosity (terse/standard/verbose based on block count) was complex and less useful than knowing WHY a command is blocked.
**Decision**: Replace with two message types: "blacklisted" (known expensive) with specific tool explanation, and "unknown" (not in either list) with config instructions.

## New Files

```
src/claude_code_hooks_daemon/strategies/pipe_blocker/
├── __init__.py
├── CLAUDE.md              # Archetype documentation
├── protocol.py            # PipeBlockerStrategy Protocol
├── common.py              # UNIVERSAL_WHITELIST_PATTERNS, matches_whitelist()
├── registry.py            # PipeBlockerStrategyRegistry
├── universal_strategy.py  # make/cmake/docker/kubectl/terraform
├── python_strategy.py     # pytest/mypy/ruff/black/bandit/tox
├── javascript_strategy.py # npm/jest/eslint/tsc/webpack
├── shell_strategy.py      # shellcheck
├── go_strategy.py         # go test/build/vet
├── rust_strategy.py       # cargo test/build/check/clippy
├── java_strategy.py       # mvn/gradle/javac
└── ruby_strategy.py       # rspec/rubocop/rake

tests/unit/strategies/pipe_blocker/
├── __init__.py
├── test_common.py
├── test_registry.py
├── test_universal_strategy.py
├── test_python_strategy.py
├── test_javascript_strategy.py
├── test_shell_strategy.py
├── test_go_strategy.py
├── test_rust_strategy.py
├── test_java_strategy.py
└── test_ruby_strategy.py
```

## Modified Files

| File | Change |
|------|--------|
| `src/.../handlers/pre_tool_use/pipe_blocker.py` | Full redesign |
| `src/.../strategies/__init__.py` | Add pipe_blocker exports |
| `tests/unit/handlers/test_pipe_blocker.py` | Three-tier test updates |
| `tests/unit/handlers/pre_tool_use/test_pipe_blocker_bug.py` | ls→allowed, find→unknown |
| `tests/integration/test_pipe_blocker_integration.py` | Add blacklist + unknown paths |
| `.claude/hooks-daemon.yaml` | Add extra_whitelist/extra_blacklist comments |

## Success Criteria

- [ ] All new strategy tests pass
- [ ] Handler tests pass with three-tier logic verified
- [ ] `ls | tail` → ALLOW (whitelisted)
- [ ] `pytest | tail` → DENY with "expensive test runner" message
- [ ] `my_script.sh | tail` → DENY with "add to config" message
- [ ] `daemon.languages: ["Python"]` → only Python + Universal blacklists active
- [ ] `extra_whitelist`/`extra_blacklist` config options work
- [ ] All 8 QA checks pass
- [ ] Daemon restarts successfully

## Notes & Updates

### 2026-02-19
- Plan created based on user requirement to fix over-eager pipe blocking
- Established as fourth strategy archetype: command-name-keyed (vs file-extension-keyed)

# Plans Index

This directory contains implementation plans for the Claude Code Hooks Daemon project. Plans follow the workflow defined in `/workspace/CLAUDE/PlanWorkflow.md`.

## Active Plans

- [00012: Eliminate ALL Magic Strings and Magic Numbers (COMPREHENSIVE)](00012-eliminate-magic-strings/PLAN.md) - 🟡 In Progress
  - Create COMPREHENSIVE constants system (12 modules: HandlerID, EventID, Priority, Timeout, Paths, **Tags**, **ToolName**, **ConfigKey**, **Protocol**, **Validation**, **Formatting**)
  - Centralize naming conversion utilities (eliminate _to_snake_case duplication)
  - Build custom QA rules FIRST to catch ALL magic values (8 rules) before migration
  - Migrate all 54 handlers to use constants (tags, tool names, priorities, timeouts)
  - Eliminate magic strings in config system, protocol fields, validation limits
  - **CRITICAL FINDINGS**: Original plan missed 40% of issues (tags: 67 files, tool names: 31 files, config keys, protocol fields)
  - **QA SYSTEM COMPLETE**: Found 320 violations (179 tags, 51 handler names, 41 tool names, 39 priorities, 7 timeouts, 3 config keys)
  - **CHECKPOINT (e1f1118)**: Phase 1-2 complete (6/12 constants modules + QA system)
  - See COMPREHENSIVE_FINDINGS.md for complete analysis
  - **Priority**: CRITICAL
  - **Owner**: Claude
  - **Progress**: ~25% complete (checkpoint committed, 320 violations documented)

- [00014: Eliminate CWD, Implement Calculated Constants](00014-eliminate-cwd-calculated-constants/PLAN.md) - 🟡 Not Started
  - Eliminate all dynamic `Path.cwd()` / `os.getcwd()` calls from handler and core code
  - Create `ProjectContext` dataclass calculated once at daemon launch (project root, git repo name, git toplevel)
  - Update 10+ handlers to use calculated constants instead of CWD
  - FAIL FAST on missing project root or uninitialized context
  - **Priority**: High (reliability issue, FAIL FAST violation)
  - **Owner**: To be assigned

- [003: Claude Code Planning Mode → Project Workflow Integration](003-planning-mode-project-integration/PLAN.md) - 🟡 Not Started
  - Intercept planning mode writes and redirect to project structure
  - Auto-number plans with 5-digit padding (00001, 00002, etc.)
  - Inject workflow guidance from PlanWorkflow.md
  - Fix critical test coverage gaps in markdown_organization handler
  - Add integration tests for config-based handler loading
  - **Priority**: High
  - **Owner**: AI Agent

- [00025: Programmatic Acceptance Testing System](00025-programmatic-acceptance-tests/PLAN.md) - 🟡 Not Started
  - Create AcceptanceTest dataclass for type-safe test definitions
  - Extend Handler base class with get_acceptance_tests() method (optional, backward compatible)
  - Implement playbook generator CLI command (outputs to stdout, ephemeral)
  - Migrate all 54 built-in handlers to define programmatic tests
  - Support custom plugin handlers automatically
  - Eliminate duplication between handler code and manual playbook
  - **Priority**: High (testing infrastructure)
  - **GitHub Issue**: #18
  - **Owner**: To be assigned

- [00024: Plugin System Fix](00024-plugin-system-fix/PLAN.md) - 🟡 Not Started
  - Fix configuration format mismatch between models.py and loader.py
  - Integrate plugin loading into DaemonController (currently only in standalone scripts)
  - Soften shared options validation (warn instead of error)
  - Add daemon integration tests for plugin loading
  - Document plugin development guide
  - **Priority**: High (broken functionality)
  - **GitHub Issue**: #17
  - **Owner**: To be assigned

- [00023: LLM Upgrade Experience Improvements](00023-llm-upgrade-experience/PLAN.md) - 🟡 Not Started
  - Create location detection and self-locating upgrade script
  - Improve LLM-UPDATE.md with clear copy-paste instructions
  - Soften error messages during upgrade to avoid investigation loops
  - Prevent nested .claude conflicts in development
  - **Priority**: High (developer experience)
  - **GitHub Issue**: #16
  - **Owner**: To be assigned

- [00020: Configuration Validation at Daemon Startup](00020-config-validation-startup/PLAN.md) - 🟡 Not Started
  - Implement config validation at daemon startup with graceful fail-open
  - Add degraded mode for invalid configurations
  - Standardize error handling across all code paths
  - **Priority**: HIGH (safety)
  - **GitHub Issue**: #13
  - **Owner**: To be assigned

- [00022: System Package Safety Handlers](00022-system-package-safety-handlers/PLAN.md) - 🟡 Not Started
  - Block dangerous package management patterns (--break-system-packages, sudo pip, curl|bash)
  - Add 5 safety handlers with proper priorities
  - **Priority**: Medium (safety)
  - **GitHub Issue**: #11
  - **Owner**: To be assigned

- [00021: Language-Specific Hook Handlers](00021-language-specific-handlers/PLAN.md) - 🟡 Not Started
  - Implement LanguageConfig-based architecture for multi-language support
  - Refactor QA suppression and TDD handlers to eliminate DRY violations
  - **Priority**: Medium (architecture)
  - **GitHub Issue**: #12
  - **Owner**: To be assigned

- [00019: Orchestrator-Only Mode](00019-orchestrator-only-mode/PLAN.md) - 🟡 Not Started
  - Create optional handler to enforce orchestration-only pattern
  - Block work tools, allow only Task delegation
  - **Priority**: Medium (feature)
  - **GitHub Issue**: #14
  - **Owner**: To be assigned

## Completed Plans

- [00018: Fix Container/Host Environment Switching](Completed/00018-container-host-environment-switching/PLAN-v2.md) - 🟢 Complete (2026-01-30)
  - Decoupled hook hot path from venv Python (bash path computation, system python3 socket client)
  - Added jq-based error emission with event-specific formatting
  - Added venv health validation with fail-fast and `repair` CLI command
  - Zero new runtime dependencies
  - **Completed**: 2026-01-30 (GitHub Issue #15)

- [00011: Handler Dependency System](00011-floofy-growing-moth/PLAN.md) - 🟢 Complete (2026-01-29)
  - Implemented handler options inheritance via shares_options_with attribute
  - Added config validation to enforce parent-child dependencies (FAIL FAST)
  - Eliminated config duplication between markdown_organization and plan_number_helper
  - Removed YAML anchors, replaced hasattr() hack with generic options inheritance
  - Two-pass registry algorithm for proper options merging
  - **Completed**: 2026-01-29 in ~2 hours

- [00010: CLI and Server Coverage Improvement to 98%](Completed/00010-cli-server-coverage-improvement/PLAN.md) - 🟢 Complete (2026-01-29)
  - Improved cli.py coverage from 74.31% to 99.63%
  - Improved server.py coverage from 88.83% to 96.95%
  - Overall project coverage improved from 93.72% to 97.04%
  - Added 62 new tests covering fork logic, exception paths, async operations
  - **Completed**: 2026-01-29 in ~3 hours (Opus agent execution)

- [002: Fix Silent Handler Failures](Completed/002-fix-silent-handler-failures/PLAN.md) - 🟢 Complete
  - Fix broken handlers (BashErrorDetector, AutoApproveReads, Notification)
  - Add input schema validation (toggleable)
  - Add sanity checks for required fields

- [001: Test Fixture Validation Against Real Claude Code Events](Completed/001-test-fixture-validation/PLAN.md) - 🟢 Complete (2026-01-27)
  - Validated all test fixtures against real daemon logs
  - Identified critical handler failures
  - Implemented HOOKS_DAEMON_LOG_LEVEL env var
  - Generated verification reports
  - **Completed**: 2026-01-27 in ~1 hour (parallel execution)

## Blocked Plans

- None

## Cancelled Plans

- None

---

## Plan Statistics

- **Total Plans**: 15
- **Active**: 10
- **Completed**: 5
- **Success Rate**: 100% (5/5 completed successfully)

## Quick Links

- [PlanWorkflow.md](../PlanWorkflow.md) - Planning workflow and templates
- [HANDLER_DEVELOPMENT.md](../HANDLER_DEVELOPMENT.md) - Handler development guide
- [DEBUGGING_HOOKS.md](../DEBUGGING_HOOKS.md) - How to capture real events

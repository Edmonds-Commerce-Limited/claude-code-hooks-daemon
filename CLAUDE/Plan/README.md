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
  - See COMPREHENSIVE_FINDINGS.md for complete analysis
  - **Priority**: CRITICAL
  - **Owner**: Claude
  - **Estimated**: 38-56 hours (revised from 12-16 after comprehensive analysis)

- [003: Claude Code Planning Mode → Project Workflow Integration](003-planning-mode-project-integration/PLAN.md) - 🟡 Not Started
  - Intercept planning mode writes and redirect to project structure
  - Auto-number plans with 5-digit padding (00001, 00002, etc.)
  - Inject workflow guidance from PlanWorkflow.md
  - Fix critical test coverage gaps in markdown_organization handler
  - Add integration tests for config-based handler loading
  - **Priority**: High
  - **Owner**: AI Agent
  - **Estimated**: 6-8 hours

## Completed Plans

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

- **Total Plans**: 6
- **Active**: 2
- **Completed**: 4
- **Success Rate**: 100% (4/4 completed successfully)

## Quick Links

- [PlanWorkflow.md](../PlanWorkflow.md) - Planning workflow and templates
- [HANDLER_DEVELOPMENT.md](../HANDLER_DEVELOPMENT.md) - Handler development guide
- [DEBUGGING_HOOKS.md](../DEBUGGING_HOOKS.md) - How to capture real events

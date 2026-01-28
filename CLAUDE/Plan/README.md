# Plans Index

This directory contains implementation plans for the Claude Code Hooks Daemon project. Plans follow the workflow defined in `/workspace/CLAUDE/PlanWorkflow.md`.

## Active Plans

- [003: Claude Code Planning Mode → Project Workflow Integration](003-planning-mode-project-integration/PLAN.md) - 🟡 Not Started
  - Intercept planning mode writes and redirect to project structure
  - Auto-number plans with 5-digit padding (00001, 00002, etc.)
  - Inject workflow guidance from PlanWorkflow.md
  - Fix critical test coverage gaps in markdown_organization handler
  - Add integration tests for config-based handler loading
  - **Priority**: High
  - **Owner**: AI Agent
  - **Estimated**: 6-8 hours

- [002: Fix Silent Handler Failures](002-fix-silent-handler-failures/PLAN.md) - 🟡 In Progress
  - Fix broken handlers (BashErrorDetector, AutoApproveReads, Notification)
  - Add input schema validation (toggleable)
  - Add sanity checks for required fields
  - **Priority**: Critical
  - **Owner**: TBD
  - **Estimated**: 8-12 hours

## Completed Plans

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

- **Total Plans**: 3
- **Active**: 2
- **Completed**: 1
- **Success Rate**: 100% (1/1 completed successfully)

## Quick Links

- [PlanWorkflow.md](../PlanWorkflow.md) - Planning workflow and templates
- [HANDLER_DEVELOPMENT.md](../HANDLER_DEVELOPMENT.md) - Handler development guide
- [DEBUGGING_HOOKS.md](../DEBUGGING_HOOKS.md) - How to capture real events

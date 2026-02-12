# Plans Index

This directory contains implementation plans for the Claude Code Hooks Daemon project. Plans follow the workflow defined in `/workspace/CLAUDE/PlanWorkflow.md`.

## Active Plans

- [00032: Sub-Agent Orchestration for Context Preservation](00032-subagent-orchestration-context-preservation/PLAN.md) - Not Started
  - Create specialized sub-agents for workflow gates and orchestration
  - **Priority**: High (context management)

- [00034: Model-Aware Agent Team Advisor](00034-model-aware-agent-team-advisor/PLAN.md) - Not Started
  - Update Plan 00032 with model-aware agent team advisor handler

- [00035: StatusLine Data Cache + Model-Aware Advisor](00035-statusline-data-cache-model-advisor/PLAN.md) - Not Started
  - StatusLine data cache for model-awareness in PreToolUse events

- [00038: Library Handler Over-fitting](00038-library-handler-over-fitting/PLAN.md) - Not Started
  - Address handlers that over-fit to project-specific assumptions

- [00041: Project-Level Handlers First-Class DX](00041-project-handlers-first-class-dx/PLAN.md) - In Progress
  - First-class developer experience for project-level handlers

- [00044: Acceptance Testing Skill](00044-acceptance-testing-skill/PLAN.md) - Not Started
  - Acceptance testing skill and agent

- [00045: Proper Language Strategy](00045-proper-language-strategy/PLAN.md) - Proposed
  - Proper language strategy pattern implementation

- [00048: Repository Cruft Cleanup](00048-repo-cruft-cleanup/PLAN.md) - Not Started
  - Delete spurious files, stale worktrees (~700MB), empty/duplicate plans, config backups
  - Rename auto-named plan folders to descriptive names

- [00049: NPM Handler - LLM Command Detection & Advisory Mode](00049-npm-handler-llm-detection/PLAN.md) - Not Started
  - Convert NPM handlers from hard blocking to smart advisory based on llm: command detection
  - Detect package.json scripts, only enforce when llm: commands exist, otherwise advise
  - **Priority**: Medium (UX improvement for projects without llm: wrappers)

- [00050: Display Config Key in Handler Block/Deny Output](00050-handler-config-key-in-errors/PLAN.md) - Not Started
  - Append fully-qualified config path (e.g., `handlers.pre_tool_use.destructive_git`) to every DENY/ASK message
  - PHPStan-inspired: users can instantly see which config key to disable
  - Implemented at FrontController level (zero handler modifications)
  - **Priority**: Medium (UX improvement for handler discoverability)

## Completed Plans

- [00047: User Feedback Resolution (v2.10.0)](Completed/00047-user-feedback-resolution/PLAN.md) - Complete
  - Fixed ghost stats_cache_reader handler in default config (caused DEGRADED MODE)
  - Deduplicated all handler priorities in yaml.example (18+ duplicates resolved)
  - Auto-create .claude/.gitignore, non-fatal installer exit, UV_LINK_MODE=copy
  - Socket path discovery file for init.sh/Python fallback path agreement
  - Documentation consistency fixes in LLM-INSTALL.md and LLM-UPDATE.md

- [00037: Daemon Data Layer](Completed/00037-daemon-data-layer/PLAN.md) - Complete
  - Persistent state and transcript access for daemon data layer

- [00046: Upgrade System Overhaul](Completed/00046-upgrade-system-overhaul/PLAN.md) - Complete (2026-02-11)
  - Fixed Layer 1 checkout ordering, dropped legacy fallback, Python 3.11+ version detection
  - AF_UNIX socket path length validation with XDG_RUNTIME_DIR fallback chain
  - Config validation UX with user-friendly Pydantic error formatting
  - Updated LLM-UPDATE.md documentation

- [00043: Robust Upgrade Detection & Repair](Completed/00043-robust-upgrade-detection/PLAN.md) - 🟢 Complete (2026-02-10)
  - Added fallback detection signal (`.claude/hooks-daemon/.git`) for broken installs missing config
  - Updated both `project_detection.sh` and `upgrade.sh` with multi-signal detection
  - `NEEDS_CONFIG_REPAIR` flag set when config missing, Layer 2 auto-repairs during upgrade
  - **Completed**: 2026-02-10

- [00034: Library/Plugin Separation and QA Sub-Agent Integration](Completed/00034-library-plugin-separation-qa/PLAN.md) - Complete (2026-02-10)
  - Moved dogfooding_reminder from library to plugin system
  - Created CLAUDE/QA.md documenting complete QA pipeline
  - Updated run_all.sh with sub-agent QA reminder
  - Plugin accidentally deleted by 3642c29, restored from git history
  - **Completed**: 2026-02-10

- [00041: DRY Install/Upgrade Architecture Refactoring](Completed/00041-dry-install-upgrade-architecture/PLAN.md) - 🟢 Complete (2026-02-10)
  - Eliminated ~800 lines of duplication between install.sh, install.py, and upgrade.sh
  - Two-layer architecture: Layer 1 (curl-fetched stable) + Layer 2 (version-specific modular)
  - Config preservation engine: Python diff/merge/validate with 82 tests
  - 14 composable bash modules in scripts/install/
  - install.sh: 307→116 lines, upgrade.sh: 612→134 lines
  - **Completed**: 2026-02-10

- [00042: Fix Auto-Continue Stop Handler Bug](Completed/00042-auto-continue-stop-bug/PLAN.md) - 🟢 Complete (2026-02-10)
  - Fixed camelCase `stopHookActive` field not detected (infinite loop risk)
  - Added diagnostic logging throughout `matches()` for future debugging
  - 7 new integration tests covering full DaemonController flow
  - **Completed**: 2026-02-10

- [00039: Handler Config Key Consistency](Completed/00039-handler-config-key-consistency/PLAN.md) - 🟢 Complete (2026-02-10)
  - Fixed design flaw where HandlerID constants were ignored by registry
  - Made HandlerID constants actual SSOT for config keys (eliminated auto-generation)
  - Fixed 5 mismatches: python/php/go QA suppressions, suggest_statusline, session_cleanup
  - Added validation with audit script (0 mismatches found post-fix)
  - Bonus: Eliminated ALL duplicate priority warnings in daemon logs
  - **Completed**: 2026-02-10

- [00033: Status Line Enhancements (PowerShell Port)](Completed/00033-statusline-enhancements/PLAN.md) - 🟡 Complete with reduced scope (2026-02-09)
  - Scope reduced: OAuth tokens blocked from third-party API use since Jan 2026
  - API-based features (progress bars, usage tracking, reset times) all cancelled
  - Delivered: ThinkingModeHandler with thinking On/Off + effortLevel display
  - **Completed**: 2026-02-09

- [00040: Playbook Generator Plugin Support](Completed/00040-playbook-generator-plugin-support/PLAN.md) - 🟢 Complete (2026-02-09)
  - Added plugin handler support to acceptance test playbook generator
  - Modified cli.py to load plugins via PluginLoader and pass to PlaybookGenerator
  - Updated PlaybookGenerator to iterate both library and plugin handlers, sorted by priority
  - Fixed plugin loader to handle Handler suffix (tries ClassName and ClassNameHandler)
  - Fixed plugin config format for dogfooding plugin
  - Verified: 68 handlers in playbook (67 library + 1 dogfooding plugin)
  - **Completed**: 2026-02-09

- [00039: Progressive Verbosity & Data Layer Handler Enhancements](Completed/00039-progressive-verbosity-data-layer/PLAN.md) - 🟢 Complete (2026-02-09)
  - Implemented count_blocks_by_handler() in HandlerHistory
  - Added progressive verbosity to PipeBlocker, SedBlocker, DestructiveGit (3 tiers each)
  - Added block count display in DaemonStats status line
  - Saves tokens by being terse on first block, verbose only when needed
  - All 5 phases complete with full 3-layer QA verification
  - **Completed**: 2026-02-09

- [00021: Language-Specific Handlers](Completed/00021-language-specific-handlers/PLAN.md) - 🟢 Complete (2026-02-06)
  - Refactored Python, Go, PHP QA suppression handlers to use LanguageConfig
  - Eliminated ~18 lines of hardcoded pattern duplication
  - Created single source of truth for language-specific patterns
  - All handlers now uniform structure (128 lines each)
  - 4-Gate verification: All gates passed (Gate 4 veto overridden)
  - **Completed**: 2026-02-06 (GitHub Issue #12)

- [003: Planning Mode Integration](Completed/003-planning-mode-project-integration/PLAN.md) - 🟢 Complete (2026-02-06)
  - Implemented planning mode write interception in markdown_organization handler
  - Auto-calculates plan numbers, creates folders, writes PLAN.md to project structure
  - Config integration with track_plans_in_project and plan_workflow_docs options
  - 28 comprehensive tests covering planning mode detection and integration
  - **Completed**: 2026-02-06 (all 8 phases implemented)

- [00031: Lock File Edit Blocker Handler](Completed/00031-lock-file-edit-blocker/PLAN.md) - 🟢 Complete (2026-02-06)
  - Implemented PreToolUse handler to block direct editing of package manager lock files
  - 225-line handler, 564-line test suite with 45 tests
  - Protects 14 lock file types across 8 ecosystems (npm, pip, composer, cargo, etc.)
  - Priority 10 safety handler with educational error messages
  - **Completed**: 2026-02-06 (GitHub Issue #19)

- [00030: Agent Team Workflow Documentation](Completed/00030-agent-team-documentation/PLAN.md) - 🟢 Complete (2026-02-06)
  - Created comprehensive CLAUDE/AgentTeam.md (752 lines)
  - Documented worktree isolation, daemon management, and merge protocol
  - Captured lessons from Wave 1 parallel execution POC
  - Cross-referenced Worktree.md throughout for complete workflow
  - **Completed**: 2026-02-06

- [00029: Fix Markdown Handler to Allow Memory Writes](Completed/00029-fix-markdown-handler-memory/PLAN.md) - 🟢 Complete (2026-02-06)
  - Fixed markdown_organization handler blocking Claude Code auto memory
  - Scoped enforcement to project-relative paths only
  - Allows writes to `/root/.claude/projects/` (outside project root)
  - Added comprehensive tests for path scoping logic
  - **Completed**: 2026-02-06

- [00028: Daemon CLI Explicit Paths for Worktree Isolation](Completed/00028-daemon-cli-explicit-paths/PLAN.md) - 🟢 Complete (2026-02-06)
  - Added --pid-file and --socket CLI flags to all daemon commands
  - Fixes worktree daemon cross-kill issue with explicit path overrides
  - Maintains backward compatibility (flags are optional)
  - Enables safe multi-daemon worktree workflows
  - **Completed**: 2026-02-06

- [00025: Programmatic Acceptance Testing System](Completed/00025-programmatic-acceptance-tests/PLAN.md) - 🟢 Complete (2026-02-06)
  - Created AcceptanceTest dataclass with validation
  - Made Handler.get_acceptance_tests() REQUIRED (@abstractmethod)
  - Implemented playbook generator with plugin discovery
  - Migrated ALL 63 handlers to programmatic tests
  - CLI command outputs to STDOUT (ephemeral playbooks)
  - Full plugin support with automatic discovery
  - Replaced manual PLAYBOOK.md with GENERATING.md
  - **Completed**: 2026-02-06 (GitHub Issue #18)

- [00027: Plan Completion Move Advisor](Completed/00027-plan-completion-move-advisor/PLAN.md) - 🟢 Complete (2026-02-06)
  - Added PreToolUse handler to detect plan completion markers
  - Advisory reminder for git mv to Completed/ folder
  - Reminds about README.md updates and plan statistics
  - **Completed**: 2026-02-06

- [00023: LLM Upgrade Experience Improvements](Completed/00023-llm-upgrade-experience/PLAN.md) - 🟢 Complete (2026-02-06)
  - Created location detection and self-locating upgrade script
  - Improved LLM-UPDATE.md with clear copy-paste instructions
  - Softened error messages during upgrade to avoid investigation loops
  - **Completed**: 2026-02-06 (GitHub Issue #16)

- [00020: Configuration Validation at Daemon Startup](Completed/00020-config-validation-startup/PLAN.md) - 🟢 Complete (2026-02-06)
  - Implemented config validation at daemon startup with graceful fail-open
  - Added degraded mode for invalid configurations
  - Standardized error handling across all code paths
  - **Completed**: 2026-02-06 (GitHub Issue #13)

- [00019: Orchestrator-Only Mode](Completed/00019-orchestrator-only-mode/PLAN.md) - 🟢 Complete (2026-02-06)
  - Created optional handler to enforce orchestration-only pattern
  - Blocks work tools, allows only Task delegation
  - Configurable read-only Bash prefix allowlist
  - **Completed**: 2026-02-06 (GitHub Issue #14)

- [00016: Comprehensive Handler Integration Tests](Completed/00016-comprehensive-handler-integration-tests/PLAN.md) - 🟢 Complete (2026-02-06)
  - Achieved 100% handler coverage in integration tests
  - Used parametrized tests for multiple scenarios per handler
  - Catches initialization failures and silent handler failures
  - Added 2,270 lines across 10 test files
  - **Completed**: 2026-02-06

- [00014: Eliminate CWD, Implement Calculated Constants](Completed/00014-eliminate-cwd-calculated-constants/PLAN.md) - 🟢 Complete (2026-02-06)
  - Created ProjectContext singleton with all project constants calculated once at daemon startup
  - Eliminated all `Path.cwd()` calls from handler and core code (only CLI discovery remains, acceptable)
  - `get_workspace_root()` falls back to ProjectContext instead of CWD
  - FAIL FAST on uninitialized context (RuntimeError)
  - Comprehensive tests for singleton lifecycle, git URL parsing, mode detection
  - **Completed**: 2026-02-06

- [00008: Fail-Fast Error Hiding Audit](Completed/00008-fail-fast-error-hiding-audit/PLAN.md) - 🟢 Complete (2026-02-05)
  - Fixed all 22 error hiding violations across 13 files
  - Created unified daemon.strict_mode for all fail-fast behavior
  - Replaced bare except blocks with specific exception types
  - Added comprehensive logging and fail-fast paths
  - **Completed**: 2026-02-05

- [00007: Handler Naming Convention Fix](Completed/00007-handler-naming-convention-fix/PLAN.md) - 🟢 Complete (2026-02-04)
  - Fixed handler naming convention conflict (config keys without _handler suffix)
  - Superseded and completed by Plan 00012 (comprehensive constants system)
  - All handlers now use HandlerID constants with correct naming
  - **Completed**: 2026-02-04 (via Plan 00012)

- [00017: Acceptance Testing Playbook](Completed/00017-acceptance-testing-playbook/PLAN.md) - 🟢 Complete (2026-01-30)
  - Created CLAUDE/AcceptanceTests/ directory structure
  - Evolved to programmatic acceptance testing approach (Plan 00025)
  - Initial manual playbook concept archived, replaced by dynamic generation
  - **Completed**: 2026-01-30

- [00013: Pipe Blocker Handler](Completed/00013-pipe-blocker-handler/PLAN.md) - 🟢 Complete (2026-01-29)
  - Implemented handler to block dangerous pipe operations (expensive commands piped to tail/head)
  - 70 comprehensive tests with 100% pass rate
  - Whitelist support for safe commands (grep, awk, jq, sed, etc.)
  - Clear error messages with temp file suggestions
  - **Completed**: 2026-01-29

- [00009: Status Line Handlers Enhancement](Completed/00009-abundant-puzzling-cray/PLAN.md) - 🟢 Complete (2026-02-05)
  - Fixed schema validation for null context_window fields
  - Implemented account_display and usage_tracking handlers
  - Added stats_cache_reader utility for ~/.claude/stats-cache.json
  - 73 tests passing with excellent coverage
  - **Completed**: 2026-02-05

- [00006: Daemon-Based Status Line System](Completed/00006-eager-popping-nebula/PLAN.md) - 🟢 Complete (2026-02-04)
  - Implemented STATUS_LINE event type and bash hook entry point
  - Created 6 status line handlers (git_repo_name, account_display, model_context, usage_tracking, git_branch, daemon_stats)
  - Added SessionStart suggestion handler
  - Full integration with special response formatting
  - **Completed**: 2026-02-04

- [00004: Final Workspace Test](Completed/00004-final-workspace-test/PLAN.md) - 🟢 Complete (2026-02-05)
  - Verified daemon.strict_mode implementation and testing
  - Confirmed single unified fail-fast configuration
  - Feature deployed and enabled in dogfooding configuration
  - **Completed**: 2026-02-05

- [00012: Eliminate ALL Magic Strings and Magic Numbers](Completed/00012-eliminate-magic-strings/PLAN.md) - 🟢 Complete (2026-02-04)
  - Created comprehensive constants system (12 modules: HandlerID, EventID, Priority, Timeout, Paths, Tags, ToolName, ConfigKey, Protocol, Validation, Formatting)
  - Built custom QA checker with AST-based magic value detection (8 rules)
  - Fixed 320 violations across entire codebase (179 tags, 51 handler names, 41 tool names, 39 priorities, 7 timeouts, 3 config keys)
  - Migrated all 54 handlers to use constants (zero magic strings/numbers remaining)
  - Centralized naming conversion utilities (eliminated _to_snake_case duplication)
  - Integrated QA checker into CI/CD pipeline (runs first, fail fast)
  - **Completed**: 2026-02-04

- [00024: Plugin System Fix](Completed/00024-plugin-system-fix/PLAN.md) - 🟢 Complete (2026-02-04)
  - Fixed configuration format mismatch (PluginsConfig model is source of truth)
  - Integrated plugin loading into DaemonController lifecycle (THE CORE FIX)
  - Made duplicate priorities deterministic (sort by priority, then name)
  - Added helpful error messages for validation failures
  - Added acceptance test validation for plugin handlers
  - Updated all documentation with event_type requirement
  - **Completed**: 2026-02-04 (GitHub Issue #17)

- [00018: Fix Container/Host Environment Switching](Completed/00018-container-host-environment-switching/PLAN-v2.md) - 🟢 Complete (2026-01-30)
  - Decoupled hook hot path from venv Python (bash path computation, system python3 socket client)
  - Added jq-based error emission with event-specific formatting
  - Added venv health validation with fail-fast and `repair` CLI command
  - Zero new runtime dependencies
  - **Completed**: 2026-01-30 (GitHub Issue #15)

- [00011: Handler Dependency System](Completed/00011-handler-dependency-system/PLAN.md) - 🟢 Complete (2026-01-29)
  - Implemented handler options inheritance via shares_options_with attribute
  - Added config validation to enforce parent-child dependencies (FAIL FAST)
  - Eliminated config duplication between markdown_organization and plan_number_helper
  - Removed YAML anchors, replaced hasattr() hack with generic options inheritance
  - Two-pass registry algorithm for proper options merging
  - **Completed**: 2026-01-29

- [00010: CLI and Server Coverage Improvement to 98%](Completed/00010-cli-server-coverage-improvement/PLAN.md) - 🟢 Complete (2026-01-29)
  - Improved cli.py coverage from 74.31% to 99.63%
  - Improved server.py coverage from 88.83% to 96.95%
  - Overall project coverage improved from 93.72% to 97.04%
  - Added 62 new tests covering fork logic, exception paths, async operations
  - **Completed**: 2026-01-29 (Opus agent execution)

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

- **Total Plans Created**: 50
- **Completed**: 39 (1 with reduced scope)
- **Active**: 10 (1 in progress, 7 not started, 1 proposed, 1 cleanup)
- **Cancelled/Abandoned**: 1 (00036 - empty draft, deleted)

## Quick Links

- [PlanWorkflow.md](../PlanWorkflow.md) - Planning workflow and templates
- [HANDLER_DEVELOPMENT.md](../HANDLER_DEVELOPMENT.md) - Handler development guide
- [DEBUGGING_HOOKS.md](../DEBUGGING_HOOKS.md) - How to capture real events

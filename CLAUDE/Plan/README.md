# Plans Index

This directory contains implementation plans for the Claude Code Hooks Daemon project. Plans follow the workflow defined in `/workspace/CLAUDE/PlanWorkflow.md`.

## Active Plans

- [00063: FAIL FAST - Plugin Handler Bug & Error Hiding Audit](00063-fail-fast-plugin-handler-audit/PLAN.md) - In Progress
  - **Phase 1 DONE**: Plugin handler suffix bug fixed, warning converted to crash (daemon fails on unregistered handler)
  - **Phase 2 PENDING**: Comprehensive audit for ALL error hiding patterns in codebase (audit script, fix violations)
  - **Priority**: High

- [00032: Sub-Agent Orchestration for Context Preservation](00032-subagent-orchestration-context-preservation/PLAN.md) - On Hold
  - Waiting for upstream Claude Code delegate mode fix (cascades to teammates, breaking agent teams)
  - Blocked by: GitHub issues #23447, #25037 (delegate mode cascade bug)
  - Also watching: #14859 (agent hierarchy in hook events), #7881 (subagent identification)
  - Research document: see RESEARCH file in plan folder

- [00034: Model-Aware Agent Team Advisor](00034-model-aware-agent-team-advisor/PLAN.md) - On Hold
  - Depends on Plan 00032 orchestration infrastructure
  - Will reassess when delegate mode is fixed upstream

- [00035: StatusLine Data Cache + Model-Aware Advisor](00035-statusline-data-cache-model-advisor/PLAN.md) - On Hold
  - Depends on Plan 00032 orchestration infrastructure
  - SessionState cache still viable when upstream unblocks


## Completed Plans

- [00095: /optimise Skill for Config Analysis](Completed/00095-config-optimise-skill/PLAN.md) - Complete
  - New `/optimise` skill analyzing hooks-daemon config across 5 domains: Safety, Stop Quality, Plan Workflow, Code Quality, Daemon Settings
  - Generates prioritised recommendations with enable/disable commands for each finding
  - Bash-driven invoke.sh iterating handler domains and scoring against active config

- [00094: Stop Explainer & Auto-Continue](Completed/00094-claude-code-introspection-debug-agent/PLAN.md) - Complete
  - `auto_continue_stop` redesigned: `matches()` always fires (except `stop_hook_active=True`), routing in `handle()`
  - 4 branches: STOPPING BECAUSE → ALLOW; confirmation question → DENY+auto-continue; QA failure → DENY+fix; default → DENY+explain-or-continue
  - Stop event JSONL logger (`_log_stop_event()`); camelCase `stopHookActive` field support
  - Full TDD with regression tests; 8/8 QA; daemon verified live

- [00093: Fresh-Clone Install Guidance](Completed/00093-fresh-clone-install-guidance/PLAN.md) - Complete
  - Distinguish "daemon not installed" from "daemon not running" in init.sh
  - Fresh clones now see "read CLAUDE/LLM-INSTALL.md" instead of wrong "run restart" advice
  - New `_is_daemon_installed()` helper + `_HOOKS_DAEMON_NOT_INSTALLED` flag, 2 new tests

- [00092: CI Environment Graceful Degradation](Completed/00092-ci-environment-graceful-degradation/PLAN.md) - Complete
  - Config-based `ci_enabled` setting for daemon-unavailable behaviour
  - Default: fail open with one-time noise + state file; `ci_enabled: true`: fail closed with STOP message
  - Fixes broken Claude Code triage in GitHub Actions for projects with hooks daemon installed

- [00090: Command Redirection for Blocking Handlers](Completed/00090-snappy-greeting-cloud/PLAN.md) - Complete
  - Core command_redirection utility module with execute_and_save(), format_redirection_context(), cleanup_old_files()
  - Retrofitted gh_issue_comments, npm_command, pipe_blocker handlers with per-handler toggle
  - Fixed markdown_organization plan folder bug (ALLOW→DENY to prevent duplicate flat files)
  - Config, docs, and acceptance test infrastructure updated

- [00088: Hooks Daemon Install Bugs](Completed/00088-hooks-daemon-install-bugs/PLAN.md) - Complete
  - Fixed 6 install bugs: git remote prereq check, daemon error surfacing, version SSOT, effort level default, plan workflow bootstrap, handler profiles
  - New installer Steps 14-15: PLAN_WORKFLOW=yes and HANDLER_PROFILE=recommended|strict env vars

- [00084: Fix Inplace-Edit Blocker xargs Bypass](Completed/00084-fix-inplace-edit-blocker-xargs-bypass/PLAN.md) - Complete
  - Fixed `grep | xargs sed -i` bypassing the blocker via overly broad grep safety check
  - Clarified handler intent: block destructive file modification, allow read-only pipelines

- [00083: Fix validate_plan_number Hardcoded Plan Directory](Completed/00083-fix-validate-plan-number-hardcoded-dir/PLAN.md) - Complete
  - Fixed handler hardcoding `CLAUDE/Plan` instead of using configurable `track_plans_in_project`
  - Added `shares_options_with="markdown_organization"` for config inheritance

- [00082: Pseudo-Events & Nitpick Handler](Completed/00082-pseudo-events-nitpick-handler/PLAN.md) - Complete
  - Pseudo-event infrastructure: synthetic events triggered by real events with frequency control
  - Nitpick pseudo-event with dismissive/hedging language handlers reusing Stop handler patterns
  - PseudoEventDispatcher with setup functions, handler chains, and result merging
  - Integrated into DaemonController lifecycle (initialise + process_event)

- [00080: Generated HOOKS-DAEMON.md + Version Cache Flush](Completed/00080-generate-hooks-daemon-docs/PLAN.md) - Complete
  - `generate-docs` CLI command producing `.claude/HOOKS-DAEMON.md` from live config + handler metadata
  - Version cache flush fix in upgrade script + stale cache defense in daemon_stats
  - Installer integration (Step 13) and CLAUDE.md update to reference generated docs

- [00079: DismissiveLanguageDetectorHandler](Completed/00079-dismissive-language-detector-handler/PLAN.md) - Complete
  - Stop event advisory handler detecting dismissive language (pre-existing issue, out of scope, not our problem, defer/ignore)
  - Follows hedging_language_detector pattern, 57 unit tests, priority 58 (advisory range)

- [00078: Integrate SecurityAntipatternHandler](Completed/00078-integrate-security-antipattern-handler/PLAN.md) - Complete
  - Blocks Write/Edit of files containing hardcoded secrets (AWS, Stripe, GitHub tokens) and injection patterns (PHP eval/exec, JS innerHTML/eval)
  - Strategy Pattern: SecurityStrategy Protocol with per-language strategies (Secrets, PHP, JavaScript) and registry
  - 60 handler tests + ~40 strategy tests, OWASP A02/A03 coverage

- [00076: TDD Collocated Test Support](Completed/00076-tdd-collocated-test-support/PLAN.md) - Complete
  - Added `test_locations` config option with 3 styles: separate, collocated, __tests__/ subdir
  - Fixes false blocking of Go, React/Vitest/Jest, Dart collocated test conventions
  - Handler-only change (zero strategy modifications), 27 new tests

- [00075: LSP Enforcement Handler](Completed/00075-lsp-enforcement-handler/PLAN.md) - Complete
  - PreToolUse handler detecting Grep/Bash(grep/rg) symbol lookups, steers toward LSP tools
  - Configurable modes: block_once (default), advisory, strict; no_lsp_mode: block/advisory/disable
  - 59 unit tests, 96.28% coverage, 3 acceptance tests, all QA passing

- [00072: Bug Report Generator](Completed/00072-bug-report-generator/PLAN.md) - Complete
  - Added `bug-report` CLI subcommand generating structured markdown reports with full diagnostics
  - Skill integration via `/hooks-daemon bug-report` routing
  - 18 TDD unit tests, all QA checks passing

- [00070: Fix NoneType Priority Comparison Crash](Completed/00070-none-priority-crash/PLAN.md) - Complete
  - Fixed daemon crash when handler has `priority: null` in config (TypeError during chain sort)
  - Multi-layer defence: chain sort fallback, registry skip, project loader validation, Priority.DEFAULT constant
  - 4 regression tests, TDD implementation

- [00069: Restart Mode Preservation Advisory](Completed/00069-restart-mode-advisory/PLAN.md) - Complete
  - Prints advisory when daemon restarts with non-default mode active (e.g. unattended)
  - Shows lost mode and exact restore command; no output for default mode
  - 11 new tests, TDD implementation

- [00068: Daemon Modes System](Completed/00068-daemon-modes-system/PLAN.md) - Complete
  - Runtime-mutable daemon modes with "unattended" mode that blocks all Stop events unconditionally
  - ModeManager + ModeInterceptor pre-dispatch pattern, Controller/Server/CLI integration, /mode skill
  - 6 phases: constants, interceptor, controller, IPC, CLI, skill + config

- [00067: Fix Upgrade Early-Exit Skips Skill/Slash-Command Deployment](Completed/00067-fix-upgrade-early-exit-skips-deployments/PLAN.md) - Complete
  - Replaced minimal early-exit (daemon restart only) with full idempotent deployment sequence
  - Now re-deploys hook scripts, settings.json, .gitignore, slash commands, and skills when already at target version
  - Fixes projects on v2.16.0 that couldn't get skills deployed (added in Plan 00061) via re-running upgrade

- [00058: Fix PHP QA Suppression Pattern Gaps](Completed/00058-php-qa-suppression-pattern-gaps/PLAN.md) - Complete
  - Added 8 missing PHP suppression patterns (@phpstan-ignore, phpcs:disable/enable/ignoreFile, @codingStandards*)
  - All patterns now blocked via strategy pattern; acceptance tests verified

- [00045: Proper Language Strategy](Completed/00045-proper-language-strategy/PLAN.md) - Complete
  - Unified three inconsistent language-aware systems into ONE canonical strategy pattern
  - Single `qa_suppression.py` handler with 11 language strategies (Python, Go, PHP, JS, Rust, Java, C#, Kotlin, Ruby, Swift, Dart)
  - Removed old individual QA suppression handlers; TDD handler updated to use `_project_languages`
  - Backward-compat config mapping in registry; old handlers fully deprecated and removed

- [00038: Library Handler Over-fitting](Completed/00038-library-handler-over-fitting/PLAN.md) - Cancelled
  - Superseded by Plan 00045 which resolved the core issue via unified language strategy pattern

- [00065: Version-Aware Config Migration Advisory System](Completed/00065-version-aware-config-migration/PLAN.md) - Complete
  - Machine-readable YAML manifests per version tracking all config changes (19 manifests v2.2.0→v2.15.2)
  - New `check-config-migrations` CLI command: compares user config against version range, reports new options
  - Integration tests against real manifests (31 tests) + unit TDD suite
  - LLM-UPDATE.md updated with Method 4 for version-specific advisory step

- [00066: Fix Plan File Race Condition](Completed/00066-plan-file-race-condition/PLAN.md) - Complete
  - Fixed TOCTOU race: `handle_planning_mode_write()` returned `ALLOW` after writing the redirect stub, causing Claude's Write tool to detect file modification and loop infinitely
  - Fix: return `DENY` (content already saved; block the Write tool from overwriting the stub)
  - Acceptance tested: single write attempt, DENY + "PLAN SAVED SUCCESSFULLY", content saved correctly

- [00064: PipeBlocker Strategy Pattern Redesign](Completed/00064-pipe-blocker-strategy-redesign/PLAN.md) - Complete
  - Replaced over-eager whitelist-only logic with three-tier whitelist/blacklist/unknown system
  - Added pipe_blocker strategy domain: 8 language strategies (Universal, Python, JS, Shell, Go, Rust, Java, Ruby)
  - Differentiated messages: blacklisted → "expensive command"; unknown → "unrecognized, add to extra_whitelist"
  - Full TDD coverage, QA suite green, daemon verified running

- [00062: Breaking Changes Lifecycle](Completed/00062-breaking-changes-lifecycle/PLAN.md) - Complete
  - Fixed systemic breaking changes documentation gap causing unknown handler errors during upgrades
  - Created historical upgrade guides for v2.10 through v2.13
  - Automated breaking changes detection in release process with upgrade guide template generation
  - Implemented smart upgrade validation with pre-flight checks and guide reading enforcement
  - Updated release notes format with BREAKING CHANGES sections
  - Total: 5842+ lines, 25 files created, 27 tests added, 7 phases completed

- [00061: Hooks Daemon User-Facing Skill](Completed/00061-hooks-daemon-user-skill/PLAN.md) - Complete
  - Deployed `/hooks-daemon` skill to user projects with 4 subcommands (upgrade, health, dev-handlers, logs)
  - Fixed v2.13.0 breaking change: enhanced error messages for plugin handler abstract method violations
  - Single skill with bash routing to wrapper scripts deployed during install/upgrade
  - Enhanced error formatter detects abstract method violations and provides version-aware guidance

- [00060: Release Blocker Handler](Completed/00060-release-blocker-handler/PLAN.md) - Complete
  - PROJECT HANDLER that blocks session ending during releases until acceptance tests complete
  - Detects release context by checking git status for modified version files
  - Priority 12 with terminal behaviour and infinite loop prevention
  - Addresses AI acceptance test avoidance behaviour from v2.13.0 release

- [00059: Fix MarkdownOrganizationHandler Completed/ Folder](Completed/00059-fix-markdown-handler-completed-folder/PLAN.md) - Complete
  - Fixed handler to allow edits to CLAUDE/Plan/Completed/, Cancelled/, Archive/ folders
  - Added _PLAN_SUBDIRECTORIES constant for known subdirectories
  - Comprehensive test coverage with backward compatibility verified
  - Updated documentation in 5 affected plans (00048-00052)

- [00057: Single Daemon Process Enforcement](Completed/00057-single-daemon-process-enforcement/PLAN.md) - Complete
  - System-wide daemon process enforcement with automatic container detection
  - 40 new tests added, 95.1% coverage maintained, 0 regressions

- [00056: Fix DaemonLocationGuardHandler Whitelisting](Completed/00056-fix-daemon-location-guard-whitelisting/PLAN.md) - Complete
  - Removed incorrect official upgrade command whitelisting pattern
  - Updated guidance with correct upgrade process using curl and bash upgrade script
  - Test count reduced from 15 to 14 tests, acceptance tests from 2 to 1
  - All QA checks pass, daemon loads successfully

- [00054: Lint-on-Edit Handler with Strategy Pattern](Completed/00054-lint-on-edit-strategy-pattern/PLAN.md) - Complete
  - Language-aware lint validation handler using Strategy Pattern (9 languages)
  - Shell/bash support added (default: bash -n, extended: shellcheck)
  - Per-language default and extended lint commands with config overrides
  - Full TDD, 145 tests (119 strategy + 26 handler), QA passing, daemon verified

- [00041: Project-Level Handlers First-Class DX](Completed/00041-project-handlers-first-class-dx/PLAN.md) - Complete
  - First-class project-level handler system: auto-discovery, CLI scaffolding/validation/testing, examples, docs
  - All 5 phases complete: core infrastructure, CLI DX, documentation, dogfooding, release prep

- [00048: Repository Cruft Cleanup](Completed/00048-repo-cruft-cleanup/PLAN.md) - Complete
  - Spurious files deleted, empty plans removed, auto-named folders renamed

- [00053: LLM QA Wrapper Script](Completed/00053-llm-qa-wrappers/PLAN.md) - Complete
  - Unified `scripts/qa/llm_qa.py` producing ~16 lines vs 200+ from run_all.sh
  - Fixed run_type_check.sh ANSI color codes breaking JSON error parsing
  - Fixed Handler missing _project_languages in __slots__/type annotation

- [00052: LLM Command Wrapper Guide & Handler Integration](Completed/00052-llm-command-wrapper-guide/PLAN.md) - Complete
  - Language-agnostic guide shipped with daemon, utility for path resolution, handler advisory references guide

- [00051: Critical Thinking Advisory Handler](Completed/00051-critical-thinking-advisory/PLAN.md) - Complete
  - UserPromptSubmit handler with multi-gate filter (length + random + cooldown)

- [00050: Display Config Key in Handler Block/Deny Output](Completed/00050-handler-config-key-in-errors/PLAN.md) - Complete
  - Append fully-qualified config path to every DENY/ASK message (PHPStan-inspired UX)
  - Implemented at FrontController/EventRouter level (zero handler modifications)

- [00049: NPM Handler - LLM Command Detection & Advisory Mode](Completed/00049-npm-handler-llm-detection/PLAN.md) - Complete
  - Convert NPM handlers from hard blocking to smart advisory based on llm: command detection
  - Created shared utils/npm.py detection utility, updated both handlers

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

## Blocked / On Hold Plans

- **00032, 00034, 00035** - On hold pending upstream Claude Code delegate mode fix (GitHub #23447, #25037)

## Cancelled Plans

- [00087: Post-Clear Auto-Execute](Cancelled/00087-post-clear-auto-execute/PLAN.md) - Cancelled
  - Hooks cannot solve `/clear <text>` auto-execution — client-side `local-command-caveat` and no auto-submit
  - Prototype handler remains enabled (marginal value), but core goal impossible via hooks

- [00044: Acceptance Testing Skill](Completed/00044-acceptance-testing-skill/PLAN.md) - Cancelled
  - Sub-agent acceptance testing retired in v2.10.0; main-thread testing is the standard

---

## Plan Statistics

- **Total Plans Created**: 91
- **Completed**: 77 (1 with reduced scope)
- **Active**: 1 (in progress)
- **On Hold**: 3 (blocked by upstream Claude Code delegate mode fix)
- **Cancelled/Abandoned**: 4 (00036 - empty draft deleted, 00044 - approach retired, 00038 - superseded by 00045, 00087 - client-side limitation)

## Quick Links

- [PlanWorkflow.md](../PlanWorkflow.md) - Planning workflow and templates
- [HANDLER_DEVELOPMENT.md](../HANDLER_DEVELOPMENT.md) - Handler development guide
- [DEBUGGING_HOOKS.md](../DEBUGGING_HOOKS.md) - How to capture real events

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.16.0] - 2026-02-22

### Added

- **Version-aware config migration advisory system**: New PostToolUse handler (`version_aware_config_migration`) that detects when the daemon version in the active session differs from the installed daemon version and advises the user to run the config migration tool. Prevents users from running stale configurations after upgrades.
- **`blocking_mode` option for SedBlockerHandler**: SedBlockerHandler now supports a `blocking_mode` configuration option (`block` or `warn`) allowing teams to choose between hard-blocking dangerous sed patterns or issuing an advisory warning. Full docs and acceptance test included.
- **`/configure` skill**: New `/configure` skill enabling structured configuration of the daemon through a guided workflow. Provides a SSOT-aligned approach to setting daemon options.
- **Coverage tests to reach 95.1% threshold**: Additional unit tests added to bring overall test coverage from below threshold to 95.1%, satisfying the mandatory 95% coverage gate.

### Fixed

- **Plan file race condition in planning mode redirect**: `plan_completion_advisor` handler now correctly returns `DENY` after redirecting to planning mode, preventing the hook from falling through to allow when it should be blocking.
- **PipeBlocker false positives on grep alternation patterns**: `pipe_blocker` handler no longer triggers false positives on grep commands using alternation patterns (e.g. `grep "foo\|bar"`). Whitelist expanded to cover common safe pipe-including patterns.

## [2.15.2] - 2026-02-21

### Added

- **Config header restart reminder in generated hooks-daemon.yaml**: New installations now receive a restart-reminder header comment at the top of the generated `.claude/hooks-daemon.yaml` config file, showing the exact daemon restart command. Reduces friction when users edit their config and forget to restart the daemon.
- **`/hooks-daemon restart` subcommand documentation**: Added restart as a first-class documented subcommand in `skills/hooks-daemon/SKILL.md`, with a dedicated `skills/hooks-daemon/restart.md` reference doc covering syntax, examples, and when to use it.
- **Post-installation and post-update CLAUDE.md instructions**: `CLAUDE/LLM-INSTALL.md` and `CLAUDE/LLM-UPDATE.md` now include a "Post-Installation: Update Project CLAUDE.md" and "Post-Update: Update Project CLAUDE.md" section instructing LLM agents to add a `### Hooks Daemon` section to project CLAUDE.md files after installation or upgrade.
- **Check Config Header guidance in install/update docs**: `CLAUDE/LLM-INSTALL.md` and `CLAUDE/LLM-UPDATE.md` include a "Also: Check Config Header" subsection instructing agents to verify the restart-reminder header is present in `hooks-daemon.yaml` and add it if missing.

## [2.15.1] - 2026-02-20

### Added

- **Status line section in README**: New documentation section describing the status line hook, its format, and the colon-separator convention with upgrade indicator.
- **Error hiding audit exclusions file** (`scripts/qa/error_hiding_exclusions.json`): Formal exclusion list documenting 75 intentional fail-open patterns (plugin discovery, container detection, JSONL parsing loops, daemon infrastructure) with documented reasons. Distinguishes intentional error handling from genuine error hiding.

### Changed

- **README rewritten to lead with developer experience value proposition**: README restructured to open with concrete developer pain points and benefits rather than technical implementation details.
- **Error hiding audit integrated into QA pipeline**: The error-hiding audit check is now a formal step in the QA pipeline, ensuring all future code changes are validated against error-hiding patterns automatically. Includes deduplication logic and exclusion file support.
- **Status line section uses colon separators and upgrade indicator**: Status line hook output format updated to use consistent colon separators and includes an upgrade indicator when a newer daemon version is available.

### Fixed

- **Silent error hiding in monitoring handlers**: Four monitoring handlers (`notification_logger`, `transcript_archiver`, `cleanup_handler`, `subagent_completion_logger`) silently swallowed `OSError` exceptions with bare `pass`. Fixed to log at `WARNING` level so failures are visible in daemon logs without disrupting operation.
- **Silent error hiding in hook dispatchers**: All 10 hook entry points (`hooks/*.py`) silently continued past `RuntimeError` when instantiating handlers that require `ProjectContext`. Fixed to log handler name and error at `WARNING` level.
- **enforce-llm-qa priority collision** (15 to 41): `enforce_llm_qa` handler priority corrected from 15 (which collided with `error_hiding_blocker` at priority 13 in the safety range) to 41 (workflow range). Improves pipe blocker snippet in documentation.
- **Status line example replaced with actual output**: Replaced an invented/illustrative status line example in documentation with the real output produced by the daemon.

## [2.15.0] - 2026-02-19

### Added

- **ErrorHidingBlockerHandler** (PreToolUse:Write, priority 13): New safety handler that blocks error-hiding patterns before files are written to disk. Uses Strategy Pattern with 5 language strategies (Shell, Python, JavaScript/TypeScript, Go, Java). Detects patterns including `|| true`, `|| :`, `set +e`, `except: pass`, empty catch blocks, swallowed exceptions, and other silent failure constructs that mask bugs. Implements Plan 00063 Phase 3.
- **PipeBlockerHandler Strategy Pattern redesign** (Plan 00064): PipeBlocker refactored from monolithic implementation to Strategy Pattern architecture. 8 language strategies shipped: Shell, Python, JavaScript/TypeScript, Go, Java, Ruby, Rust, and Universal. Registry-based design allows adding new strategies without modifying handler logic.
- **Shellcheck QA integration** (check 8): Added `shellcheck -x` as QA pipeline check #8. All shell scripts must pass shellcheck with zero errors and zero warnings. `.shellcheckrc` configuration file added with `source-path=SCRIPTDIR` for proper source-following.
- **Color-coded git branch in status line**: Branch name in the status line now renders green for the default branch, orange for non-default branches, and grey when the branch is unknown.
- **Code review gate in release process** (Step 7.5): New blocking gate added to RELEASING.md requiring review of the code diff (`git diff LAST_TAG..HEAD -- src/`) before proceeding to acceptance testing. Ensures bugs and anti-patterns are caught before release.
- **Acceptance test scoping by bump type**: MAJOR and MINOR releases require the full acceptance test suite. PATCH releases with handler changes require targeted tests for changed handlers only. PATCH releases with no handler changes may skip acceptance testing with documented rationale in release notes.
- **`recommended_model` and `requires_main_thread` fields on `AcceptanceTest`**: New metadata fields on the `AcceptanceTest` dataclass allow test definitions to declare which model is recommended for execution and whether the test must run in the main Claude Code thread (not a sub-agent).
- **`RecommendedModel` enum**: Type-safe enum for specifying recommended model in acceptance test metadata (`OPUS`, `SONNET`, `HAIKU`).

### Fixed

- **Shellcheck warnings across all shell scripts**: Resolved all shellcheck warnings including SC2034 (unused variables), SC2155 (declare and assign separately), SC2120/SC2119 (function argument handling), and SC1091 (source file following). All scripts now pass `shellcheck -x` with zero issues.
- **ESLint PATH in validate_eslint_on_write**: Prepend `node_modules/.bin` to PATH in the subprocess call so locally-installed ESLint binaries are found without requiring global installation.
- **health-check.sh wrong command name**: Fixed health-check.sh using the incorrect `config-validate` command; updated to the correct `validate-config` command name.
- **Dockerfile GPG key dearmoring for Dart SDK**: Fixed Dart SDK apt repository setup in the CCY Dockerfile by properly dearmoring the GPG key before adding it to the apt trusted keyring.
- **CCY Dockerfile tracking**: Fixed `.gitignore` rule that prevented the CCY Dockerfile from being tracked by git; removed the blanket `ccy/` ignore pattern.
- **PipeBlocker acceptance test commands**: Fixed acceptance test commands. Original `echo`-wrapped commands were silently allowed (echo is whitelisted). Final pattern: `false && CMD | tail -N` for blacklisted commands (bash `|` binds tighter than `&&` so `false` short-circuits before CMD runs; `_extract_source_segment` splits on `&&` leaving `CMD` as source → blacklist path exercised, "expensive" message verified). Unknown-command test uses `[[ "CMD | tail" == 0 ]]` no-op (safe string comparison, no execution).

## [2.14.0] - 2026-02-18

### Added

- **NEW: /hooks-daemon User Skill** (Plan 00061, commits bd3eb72, dda0dcc, 7fc9415, d18fb50, 649d6d4, 37a0b52, ab73b82, a6222fe)
  - User-facing skill deployed to `.claude/skills/hooks-daemon/` during installation
  - Single skill with argument-driven routing (manual invocation only)
  - **Subcommands**:
    - `upgrade` - Upgrade daemon to new version (auto-detect, specific version, force reinstall)
    - `health` - Comprehensive health check (status, config, handlers, logs, DEGRADED MODE recovery)
    - `dev-handlers` - Scaffold project-level handlers with TDD workflow guidance
    - `logs` - View daemon logs
    - `status` - Check daemon status
    - `restart` - Restart daemon
    - `handlers` - List loaded handlers
  - **Documentation**: 5 markdown files (main skill + upgrade + health + dev-handlers + troubleshooting)
  - **Deployment**: Integrated with install_version.sh (Step 10) and upgrade_version.sh (Step 13)
  - **Skills packaged WITH daemon** and deployed during installation/upgrade
  - Enhanced error messages for plugin handler abstract method violations (v2.13.0 breaking change fix)

- **Breaking Changes Lifecycle Infrastructure** (Plan 00062, commits aac0f3e, d5b002b, 0454d9e, 5205851, c94af3e, d0094ce, 19f65af)
  - **Historical Upgrade Guides**: Created comprehensive guides for v2.10→v2.11, v2.11→v2.12, v2.12→v2.13
  - **Automated Breaking Changes Detection**: RELEASING.md Step 6.5 blocking gate
  - **Smart Upgrade Validation**: Pre-upgrade compatibility checks, config diff analysis, breaking changes warnings
  - **Upgrade Guide Enforcement**: Interactive reading confirmation before proceeding
  - **New Components**:
    - `breaking_changes_detector.py` - Parses CHANGELOG.md for breaking change markers (14 tests)
    - `upgrade_compatibility.py` - Validates user config against target version (13 tests)
    - `config_diff_analyzer.sh` - Compares handler names with fuzzy rename detection
  - **Upgrade Script Integration**: Three safety gates (before/during/after upgrade)
  - **Release Notes Format**: BREAKING CHANGES sections with handler removals/renames
  - Total: 5,842+ lines of code/docs, 25 new files, 27 tests

- **Test Coverage Improvements**: Increased coverage from 94.89% to 95.2% (commits b8eeb89, bb364a7)
  - Core module and handler test coverage improvements
  - Protocol and strategy test coverage enhancements
  - ImportError tests for input_schemas.py (100% coverage)
  - Edge case tests for router.py (100% coverage)
  - Unknown extension tests for tdd_enforcement.py (95.24% coverage)
  - Protocol isinstance tests for TDD, QA Suppression, and Lint strategies
  - Lazy import tests for lint module

- **Release Workflow State Management** (commit 5be1cf0)
  - Release process now uses workflow state files for compaction resilience
  - State tracking for 14 release phases
  - Enables WorkflowStatePreCompactHandler/RestorationHandler integration
  - State files: `./untracked/workflow-state/release/state-release-TIMESTAMP.json`

- **Comprehensive Plan Workflow Documentation** (commit 15e3591)
  - New `docs/PLAN_WORKFLOW.md` (1,600 lines, 41KB)
  - Complete guide to structured planning with numbered folders
  - 10 major sections covering philosophy, setup, customization, examples
  - Documents 5 handlers supporting workflow automation
  - Step-by-step setup instructions for new projects
  - Real-world examples (feature, refactoring, bug fix plans)
  - Project-agnostic design (works with any codebase)

- **Error Hiding Audit Script** (Plan 00063 Phase 2, commit 7eaf65d)
  - AST-based audit tool detecting silent error patterns
  - Detects: silent try/except/pass, silent continue, return None on errors, log-and-continue, bare except
  - Found 93 violations across 27 files (systemic problem documented)

- **Effort Level Signal Bars in Status Line** (commits 6ab6e70, 3fca72c)
  - Added effort level signal bars (▌▌▌) to status line for all models
  - Enhanced display for Claude 4+ models
  - Bars visually indicate current effort level during AI processing

### Changed

- **FAIL FAST Enforcement** (Plan 00063, commits ef650d3, 887f52c)
  - **Project Handlers (TIER 1)**: Always crash on errors (no graceful failure)
    - Changed ProjectHandlerLoader return type from `Handler | None` to `Handler`
    - All errors raise RuntimeError immediately (file not found, import errors, no Handler class, multiple classes, instantiation failure)
    - Updated 8 tests to expect RuntimeError instead of None
    - Moved error fixtures to `project_handlers_error_cases/` directory
  - **Library Handlers (TIER 2)**: Strict mode controlled (handler discovery, optional features)
    - ConfigValidator.get_available_handlers() accepts strict_mode parameter
    - In strict_mode=True: CRASH on handler discovery import errors
    - In strict_mode=False: Log and continue gracefully
  - **New DRY Utility**: `utils/strict_mode.py` with `handle_tier2_error()` and `crash_in_strict_mode()` helpers (7 tests)
  - **Plugin Loading**: Daemon CRASHES if configured handlers can't be loaded (not warns)

- **Documentation Structure** (commit 8c4c88b)
  - Separated Plans from Workflows documentation for clarity
  - **Plans**: Development work tracking (CLAUDE/Plan/, docs/PLAN_SYSTEM.md)
  - **Workflows**: Repeatable processes surviving compaction (docs/WORKFLOWS.md)
  - Clear distinction between optional vs required handlers for each system
  - Renamed `docs/PLAN_WORKFLOW.md` → `docs/PLAN_SYSTEM.md`
  - Created new `docs/WORKFLOWS.md` documenting workflow concept properly

- **MarkdownOrganizationHandler**: Allow edits to `src/claude_code_hooks_daemon/skills/` (commit dda0dcc)
  - Enables writing SKILL.md and supporting docs during skill development
  - Skills are packaged with daemon (not deployed separately)

### Fixed

- **CRITICAL: Plugin Handler Suffix Bug** (Plan 00063 Phase 1, commit ef650d3)
  - Plugin handlers with "Handler" suffix now register correctly
  - Root cause: Asymmetry between PluginLoader.load_handler() (correctly handles suffix) and DaemonController._load_plugins() (only checked base name)
  - **Before**: MyPluginHandler silently skipped with warning, daemon ran unprotected
  - **After**: Daemon checks both ClassName and ClassNameHandler variants, CRASHES if configured handler can't be matched
  - Added test_load_plugin_with_handler_suffix (Handler suffix now works)
  - Added test_daemon_crashes_on_unmatched_plugin_handler (FAIL FAST enforcement)
  - Updated 6 tests expecting old buggy behavior to expect CRASH

- **Documentation Organization** (commits 8c4c88b, 15e3591)
  - Fixed Plans vs Workflows documentation confusion
  - Previously conflated two separate concepts in single location
  - Now properly separated with clear purposes and lifecycles
  - Enhanced task breakdown guidance and completion checklist procedures

- **Test Bug**: Fixed test_plugin_daemon_integration.py assertion matching "NOT RUNNING" (commit 99eeee7)
  - Changed to check for "Daemon: RUNNING" specifically

- **Import Error**: Fixed test_upgrade_compatibility.py import (commit d0094ce)
  - Changed `constants.event` → `constants.events`

- **Effort Level Signal Bars Styling** (commits 95a6b4d, 0b031b1)
  - Fixed bar colours: orange (active) / grey (inactive) matching Claude Code UI
  - Fixed bar character to ▌▌▌ matching Claude Code's actual effort UI

- **Black Formatting**: Applied formatting fixes (commits 04a0125, d0094ce)
  - Fixed test_enforcement.py formatting issues
  - Fixed test_controller.py formatting issues

## [2.13.0] - 2026-02-17

### Added
- **ReleaseBlockerHandler**: New project-specific Stop event handler enforcing acceptance testing gate during releases (Plan 00060, commits 1de40fc, 1796310, 6841e8c)
  - Detects release context by checking for modified version files (pyproject.toml, version.py, README.md, CHANGELOG.md, RELEASES/*.md)
  - Blocks Stop events during releases with clear message referencing RELEASING.md Step 8
  - Prevents infinite loops via stop_hook_active flag, fails safely on git errors
  - Priority 12 (before AutoContinueStop at 15)
  - Addresses AI acceptance test avoidance behavior
  - 22 unit tests + 4 integration tests, all passing

- **Single Daemon Process Enforcement**: New `enforce_single_daemon_process` configuration option (Plan 00057, commits fc43d03, 3b0df03, 17b3420, a491809, c07e2bb, 6c38904, 6b6adca)
  - Prevents multiple daemon instances from running simultaneously
  - In containers: Kills ALL other daemon processes system-wide on startup (SIGTERM → SIGKILL)
  - Outside containers: Only cleans up stale PID files (safe for multi-project environments)
  - Auto-detection: Configuration generation auto-enables in container environments
  - 2-second timeout for graceful shutdown before force kill
  - 40 new tests, 95.1% coverage maintained, 0 regressions

- **Plan Execution Strategy Framework**: Added execution strategy guidance to planning workflow (commit b960f23)
  - Strategy selection matrix (Simple/Medium/Complex/Critical complexity levels)
  - Three strategies: Single-Threaded, Sub-Agent Orchestration, Sub-Agent Teams
  - Model-specific guidance for optimal execution approach
  - New plan header fields: Recommended Executor, Execution Strategy

### Changed
- **Acceptance Testing Methodology**: Made acceptance testing realistic and efficient (commit 7cd9baa)
  - Categorized tests: EXECUTABLE (89 tests, 20-30 min), OBSERVABLE (10 tests, 30 sec), VERIFIED_BY_LOAD (30 tests, 0 min)
  - Updated RELEASING.md Step 8 with realistic categories and time estimates
  - Enhanced playbook generator with category annotations
  - Reduced testing burden from 127+ unrealistic tests to 89 achievable tests
  - Clear expectations about what to test vs skip

- **Plan Execution Guidance**: Clarified model capabilities for plan orchestration (commits 2983fa6, bc10236)
  - **CRITICAL**: Haiku 4.5 CANNOT orchestrate plans (only Opus/Sonnet)
  - Removed soft language and waffling about model capabilities
  - Minimum: Sonnet 4.5 for plan orchestration (hard requirement)
  - Clear guidance on when to use Opus vs Sonnet for plan execution

- **MarkdownOrganizationHandler**: Added support for plan subdirectories (Plan 00059, commits b496d68, 8f1d0df, 38b9d42)
  - Now allows edits to Completed/, Cancelled/, Archive/ subdirectories
  - Added _PLAN_SUBDIRECTORIES constant for validation
  - Fixed validation logic to check subdirectory paths correctly
  - Updated 5 completed plans with proper status and completion dates

### Fixed
- **PHP QA Suppression Pattern Gaps**: Fixed CRITICAL bug allowing developers to bypass quality controls (Plan 00058, commits 6ae79e4, 7252bfe)
  - **SECURITY**: Handler was missing 8 suppression patterns, allowing unblocked suppressions
  - Added @phpstan-ignore, phpcs:disable/enable, phpcs:ignoreFile, @codingStandardsIgnore patterns
  - Added 8 comprehensive TDD regression tests
  - Added 3 acceptance tests for critical patterns
  - All patterns now use string concatenation to avoid self-matching

- **Black Formatting**: Fixed formatting issues in test_enforcement.py (commit 609a2ef)

- **QA Issues**: Fixed magic value violations and type errors after Phase 2 & 3 of Plan 00057 (commit c4270d3)
  - Added Timeout.PROCESS_KILL_WAIT constant (2 seconds)
  - Properly typed psutil optional import with ModuleType annotation

## [2.12.0] - 2026-02-12

### Added
- **LintOnEditHandler with Strategy Pattern**: New PostToolUse:Edit handler providing instant linting feedback for 9 languages (Plan 00054, commits 340d806, b7a7d9f, 8db361d, 9b56161)
  - Strategy-based architecture with Protocol interface for language-specific linting
  - 9 language strategies: Python (ruff), JavaScript/TypeScript (eslint), Ruby (rubocop), PHP (phpcs), Go (golangci-lint), Rust (clippy), Java (checkstyle), C/C++ (clang-tidy), Shell (shellcheck)
  - Registry pattern with config-filtered loading (only active project languages)
  - Each strategy independently TDD-able with its own test file
  - Priority 30 (code quality tier), non-terminal to allow other handlers
  - Comprehensive negative acceptance tests for all 9 strategies
  - Uses `sys.executable` for Python linting instead of hardcoded binary paths (commit 9f94158)

- **WorkingDirectoryHandler**: New SessionStart handler displaying current working directory in orange when it differs from project root (commits fe59c0c, aee79cd)
  - Helps users identify when Claude Code's cwd != project root
  - Orange color (38;2;255;165;0) for visual prominence
  - Priority 58 (workflow tier), non-terminal
  - Only displays when cwd differs from project root (reduces noise)

- **CurrentTimeHandler**: New SessionStart handler displaying current timestamp in status line (commit 4b7f7b6)
  - Shows ISO 8601 timestamp (YYYY-MM-DD HH:MM:SS) at session start
  - Priority 59 (workflow tier), non-terminal
  - Helps users track session timing and context freshness

- **DaemonLocationGuardHandler**: New PreToolUse:Bash handler enforcing daemon directory security (commits 48837e5, 0d91040, cf9c6f1, Plan 00056)
  - Blocks bash commands attempting to run daemon CLI outside `.claude/hooks-daemon/` installation directory
  - Prevents accidental execution from incorrect locations (e.g., workspace root in self-install mode)
  - Whitelisting system for allowed daemon directories via `project_root` config
  - Priority 15 (safety tier), terminal (blocks execution)
  - 100% test coverage with positive/negative cases

### Fixed
- **TDD Handler Multi-Path Detection**: Fixed bug where TDD handler only detected first test directory convention (commits b3cb0ba, 0a743fb, e5adfb5, Plan 00055)
  - Bug: Handler checked if `tests/` OR `test/` existed, but stopped after first match
  - Bug: Projects with both conventions (Python `tests/` + Node `test/`) weren't fully detected
  - Fix: Handler now detects ALL matching test directory conventions
  - Added comprehensive test coverage for single and multi-convention projects

## [2.11.0] - 2026-02-12

### Added
- **LLM-Optimized QA Script**: New `scripts/qa/llm_qa.py` wrapper producing ~16 lines of structured output instead of 200+ verbose lines (Plan 00053, commits da71c17, 5b1f1fa)
  - Unified QA runner supporting individual tools or all checks
  - JSON output with jq hints for drill-down investigation
  - Cross-checks tool exit codes against JSON to catch reporting inaccuracies
  - `--read-only` mode for non-interactive environments
  - Project-level handler enforces usage of LLM script over verbose `run_all.sh` (commit cedb3c0)

- **Per-Handler Documentation Structure**: Handler-specific documentation files in `docs/guides/handlers/` (commit 7763c05)
  - One markdown file per complex handler with full configuration options
  - First extraction: `markdown_organization.md` with monorepo interaction and custom paths
  - `HANDLER_REFERENCE.md` links to per-handler files instead of duplicating content
  - Config templates include doc links for each handler

- **Monorepo Support for Markdown Organization Handler**: Sub-project directory configuration (commits 21c0349, da7d750)
  - New `_monorepo_subproject_patterns` config option for regex patterns matching sub-project directories
  - Sub-projects can have their own `CLAUDE/`, `docs/`, `untracked/`, `RELEASES/`, `eslint-rules/` directories
  - 13 new tests covering monorepo allow/block scenarios
  - Backward compatible with existing single-project configurations

- **Configurable Allowed Markdown Paths**: Custom regex patterns for markdown organization handler (commit 10ed5dd)
  - New `allowed_markdown_paths` config option overrides ALL built-in path checks
  - `CLAUDE.md`, `README.md`, `CHANGELOG.md` remain always-allowed regardless of custom patterns
  - Documented as commented defaults in YAML config for easy customization
  - 19 tests covering interaction with monorepo configuration

- **Critical Thinking Advisory Handler**: New UserPromptSubmit handler to encourage deeper analysis (commits 2c4266d, 4a30b6e, 51e530e)
  - Triggers on complex tasks involving architecture, refactoring, or multi-file changes
  - Advises LLMs to consider edge cases, dependencies, and failure modes before implementation
  - Non-blocking advisory mode with configurable trigger patterns
  - New HandlerID.CRITICAL_THINKING_ADVISORY constant

- **LLM Command Wrapper Guide**: Comprehensive language-agnostic guide for wrapping CLI tools (commits 2c4266d, ca50a3b, 5bc354c, 8dfdcfc)
  - New `guides/` package with `llm-command-wrappers.md` documentation
  - Covers JSON output, error handling, context awareness, and LLM-optimized formatting
  - NPM and ESLint advisory handlers reference guide path
  - Markdown organization handler allows `guides/` directory
  - New `get_llm_command_guide_path()` utility function

- **Config Key Injection in DENY/ASK Responses**: Infrastructure-level feature for user-friendly handler disabling (commits b428e54, fa82460)
  - EventRouter and FrontController inject config paths into all DENY/ASK responses
  - Users see exact config path to disable blocking handler immediately
  - Zero individual handler changes needed (handled at routing layer)
  - Example: "To disable this handler, set `handlers.pre_tool_use.destructive_git.enabled: false`"

- **Force Branch Deletion Blocking**: Extended destructive git handler to catch forced branch deletions (commit f0a03b9)
  - Blocks `git branch -D` and `git branch --delete --force` patterns
  - Added to existing destructive git safety checks

- **Blocking Handler False Positives Documentation**: New CLAUDE.md section explaining intentional string matching behavior (commit 80a2f25)
  - Documents why handlers match patterns in commit messages (enables acceptance testing)
  - Explains false positives are intentional and trivial to work around
  - Provides examples and workarounds for describing fixes without triggering blocks

### Changed
- **MyPy Color Output Disabled**: Fixed false-negative error reporting in type checking (commit da71c17)
  - Bug: ANSI color codes broke mypy error parsing in JSON output
  - Bug: `run_type_check.sh` reported 0 errors when mypy found real errors
  - Fix: Added `--no-color-output` flag to mypy invocation
  - JSON results now accurately reflect actual type checking errors

- **Handler Class Attributes**: Added missing `_project_languages` to `__slots__` and type annotations (commit da71c17)
  - Fix: MyPy `attr-defined` error for handlers using project language detection
  - Ensures strict type safety for handler class attributes

- **Thinking Mode Status Priority**: Moved from priority 25 to 12 for better visibility (commit 990bb1f)
  - Displays next to model name in session start messages
  - More prominent position for critical thinking advisory context

- **NPM Handler LLM Command Detection & Advisory Mode**: NPM handler now detects `llm:` commands in package.json (commits fa82460, c5e2283, baeb7ae)
  - New shared utility `utils/npm.py` with `has_llm_commands_in_package_json()` function
  - **NpmCommandHandler**: DENY when `llm:` commands exist (blocks raw npm), ALLOW with advisory when absent
  - **ValidateEslintOnWriteHandler**: Run ESLint when `llm:` commands exist, skip with advisory when absent
  - Advisory messages reference LLM command wrapper guide for proper usage patterns
  - Encourages teams to use LLM-optimized wrappers instead of raw CLI tools

### Fixed
- **Type Check JSON Accuracy**: Cross-validation prevents false-negative QA reports (commit da71c17)
  - `llm_qa.py` now cross-checks tool exit codes against JSON results
  - Catches cases where JSON reports success but tool exited with error code
  - Prevents silent failures in CI/CD pipelines

- **Deprecated Handler Attribute**: Fixed 6 handlers using deprecated `name=` parameter instead of `handler_id=` (commit f0a03b9)
  - Updated handlers to use HandlerID constants for self-identification
  - Maintains consistency with handler registry architecture from Plan 00039
  - Affected handlers: pip_break_system, sudo_pip, curl_pipe_shell, dangerous_permissions, global_npm_advisor, lock_file_edit_blocker

- **Silent Exception Suppression**: Fixed registry.py silently hiding import errors (commit f0a03b9)
  - Bug: Bare try/except/pass suppressed handler loading failures without logging
  - Fix: Added explicit error logging before suppression
  - Maintains FAIL FAST principle - errors are now visible in daemon logs

### Removed
- **Project-Specific Hangover Handlers**: Cleaned up two handlers that belonged in project-level config (commit 990bb1f)
  - Removed `validate_sitemap` handler (PostToolUse) - project-specific validation
  - Removed `remind_validator` handler (SubagentStop) - project-specific reminder
  - Updated all constants, configs, tests, docs, and install template

## [2.10.1] - 2026-02-11

### Fixed
- **Ghost Handler Cleanup**: Removed non-existent stats_cache_reader handler from config, deduplicated handler priorities (commit adf2ae6)
  - Bug: Config referenced handler that was never implemented
  - Bug: Multiple handlers shared same priority values
  - Fix: Removed ghost handler entry from hooks-daemon.yaml
  - Fix: Adjusted handler priorities to eliminate duplicates

- **Socket Path Discovery Agreement**: Fixed init.sh and Python fallback logic to use same socket path discovery (commit 199dd00)
  - Bug: init.sh bash script and Python installer.py used different socket path logic
  - Bug: Could result in init.sh creating wrong directory structure
  - Fix: Both now use consistent socket path discovery via daemon/paths.py

- **.gitignore Auto-Creation**: Daemon now auto-creates .claude/.gitignore if missing, non-fatal if fails (commit 8285e7c)
  - Bug: Missing .gitignore caused untracked daemon runtime files to appear in git status
  - Bug: UV_LINK_MODE environment variable not set for uv package manager
  - Fix: Auto-create .gitignore on daemon startup (non-fatal if permission denied)
  - Fix: Set UV_LINK_MODE=copy in hooks-daemon.env for uv compatibility

- **Validation False Positive**: Fixed validate_instruction_content handler false positive on documentation paths (commit f7d878c)
  - Bug: Handler incorrectly flagged FILE_LISTINGS instructions in CLAUDE/ documentation paths
  - Bug: Documentation files legitimately contain instruction examples that triggered validation
  - Fix: Exclude CLAUDE/, RELEASES/, and .claude/ paths from FILE_LISTINGS validation

- **Documentation Consistency**: Fixed 10 documentation inconsistencies and broken references (commit 684ad96, dddff9a)
  - Bug: Broken internal documentation links
  - Bug: Inconsistent success criteria descriptions
  - Bug: Incorrect daemon restart command examples
  - Bug: .gitignore auto-creation not documented
  - Fix: Updated all broken references to correct paths
  - Fix: Standardized success criteria wording across docs
  - Fix: Corrected restart command format in all documentation

### Changed
- **Repository Cleanup**: Removed cruft and improved organization (Plan 00048, commit 45a45fc)
  - Deleted spurious `/workspace/=5.9` file (accidental pip output redirect)
  - Removed 4 stale worktrees (~700MB) from completed plans 00021 and 003
  - Deleted empty plan 00036, renamed auto-named plans to descriptive names
  - Moved historical `BUG_FIX_STOP_EVENT_SCHEMA.md` to completed plan directory
  - Cleaned up stale config backup file

## [2.10.0] - 2026-02-11

### Added
- **Python 3.11+ Version Detection**: Bash scripts now validate Python version meets 3.11+ requirement (Plan 00046 Phase 2, commit ae7ac25)
  - `scripts/prerequisites.sh` checks Python version before venv creation
  - `scripts/upgrade.sh` validates Python version during upgrade
  - `scripts/venv.sh` ensures compatible Python interpreter
  - Clear error messages guide users to upgrade Python if version too old
  - Prevents cryptic installation failures from unsupported Python versions

- **Installation Feedback Instructions**: Added feedback file template to LLM-INSTALL.md (commit 6f32b84)
  - Users can provide structured installation feedback
  - Helps identify common installation pain points
  - Template includes environment details, steps taken, and issue description

### Changed
- **Upgrade System Root Cause Fix**: Complete overhaul of upgrade workflow (Plan 00046 Phase 1, commit e3217ab)
  - **checkout-first-then-delegate**: Upgrade script now checks out target version BEFORE delegating to it
  - Eliminates "upgrade to broken version" failure mode where old script delegates to broken new script
  - Dropped legacy fallback mode (upgrade.sh is now single source of truth)
  - **Nested Install Protection**: Detects and prevents nested `.claude/hooks-daemon/hooks-daemon/` installations
  - More robust upgrade path with better error handling

- **Socket Path Length Validation**: AF_UNIX socket path length limits now enforced with fallback mechanism (Plan 00046 Phase 3, commit 98e6d5f, 5126237)
  - **Path Length Check**: Validates socket path ≤ 107 characters (Linux AF_UNIX limit)
  - **Fallback Hierarchy**: XDG_RUNTIME_DIR → /run/user/$(id -u) → /tmp/claude-hooks-{user}
  - Self-install mode path detection improved in `_get_untracked_dir()` (commit 964ae31)
  - Server.py catches OSError during bind and provides actionable error messages
  - Integration tests verify fallback behavior when paths exceed limits

- **Config Validation UX Improvements**: User-friendly Pydantic validation errors (Plan 00046 Phase 4, commit 2d86d5e, e27ea42)
  - **Friendly Error Formatting**: Pydantic errors transformed into readable messages
  - **Fuzzy Field Suggestions**: Suggests correct field names for typos (e.g., "enabeld" → "Did you mean: enabled?")
  - **Duplicate Priority Logging**: Duplicate handler priorities demoted from WARNING to DEBUG
  - Type annotation fixes and magic value elimination in validation_ux module

- **LLM-UPDATE.md Documentation**: Comprehensive upgrade documentation updates (Plan 00046 Phase 5, commit 38853c9)
  - Python 3.11+ requirement clearly documented
  - Socket path troubleshooting section added
  - Feedback template for upgrade issues
  - Common failure modes and solutions documented

### Fixed
- **Upgrade Script Robustness**: Fixed critical upgrade system failure modes (Plan 00046 Phase 1)
  - Bug: Old upgrade script could delegate to broken new version script
  - Bug: Nested installations created `.claude/hooks-daemon/hooks-daemon/` structure
  - Bug: Legacy fallback mode caused confusion and maintenance burden
  - Fix: Checkout target version first, then run its scripts (no more delegation trust issues)
  - Fix: Nested install detection prevents directory structure corruption

- **Socket Path Length Failures**: Fixed daemon startup failures on deep directory paths (Plan 00046 Phase 3)
  - Bug: AF_UNIX sockets limited to ~107 characters, deep project paths caused bind() failures
  - Bug: Cryptic OSError messages didn't explain root cause
  - Fix: Validate path length before bind, fallback to shorter paths (XDG_RUNTIME_DIR, /run/user, /tmp)
  - Fix: Catch OSError in server.py with actionable error message

- **Config Validation Errors**: Fixed confusing Pydantic error messages (Plan 00046 Phase 4)
  - Bug: Raw Pydantic validation errors were cryptic for end users
  - Bug: Typos in field names provided no suggestions
  - Fix: Custom formatter translates Pydantic errors to friendly messages
  - Fix: Fuzzy matching suggests correct field names

### Documentation
- **Plan 00046 Completion**: Six-phase upgrade system overhaul completed (commit 687cbac)
  - Complete implementation plan with root cause analysis
  - Technical decisions documented for all phases
  - Success criteria verified for upgrade reliability
- **Async Agent Warning**: Added critical warning to RELEASING.md about v2.9.0 incident (commit e131232)
  - Documents the importance of waiting for ALL acceptance test agents to complete
  - Prevents premature commits/pushes while tests still running

### Style
- **Black Formatting**: Auto-formatted server.py for line length compliance (commit 86b636e)

## [2.9.0] - 2026-02-11

### Added
- **Strategy Pattern Architecture for Language-Aware Handlers** (Plan 00045, commit 7adbc39)
  - **Unified QA Suppression Handler**: Single `QaSuppressionHandler` replaces 4 per-language handlers (eslint_disable, python/php/go_qa_suppression_blocker)
  - **11 Language Strategies**: Python, JavaScript/TypeScript, PHP, Go, Rust, Java, Ruby, Kotlin, Swift, C#, Dart
  - **Protocol-Based Design**: Structural typing with `QaSuppressionStrategy` and `TddStrategy` protocols
  - **Extension-to-Strategy Registry**: Maps file extensions to language strategies with config-filtered loading
  - **Project Languages Config**: New `project_languages` config option to filter strategies by active languages
  - **TDD Strategy Refactoring**: TddEnforcementHandler now uses strategy registry for language-specific test detection
  - **Strategy Pattern QA Checker**: New `scripts/qa/run_strategy_pattern_check.sh` enforces pattern compliance
  - **Comprehensive Strategy Tests**: 5285 total tests (up from 4813), 95%+ coverage maintained
  - **New Strategies Module**: `src/claude_code_hooks_daemon/strategies/` with QA suppression and TDD strategies
  - **Strategy Documentation**: Complete TDD strategy documentation in `strategies/tdd/CLAUDE.md`

- **Automated Acceptance Testing Skill**: `/acceptance-test` skill for parallel handler validation (Plan 00044, commit 95e2286)
  - AcceptanceTestRunnerAgent: Haiku-based parallel test execution across batches
  - PlaybookGenerator: Converts handler definitions to structured JSON test playbooks
  - CLI integration: `generate-playbook` command for ephemeral test generation
  - Parallel batch execution: Groups tests (3-5 per batch) and runs concurrently
  - Structured JSON results: Pass/fail/skip/error counts for automated release gates
  - Reduces acceptance testing time from 30+ minutes to 4-6 minutes
  - Integration with release workflow as mandatory blocking gate (Step 8)

### Changed
- **Handler Architecture**: Transition from duplicated per-language handlers to strategy pattern
  - 4 handlers deleted (eslint_disable, python/php/go_qa_suppression_blocker)
  - 1 new unified handler added (qa_suppression)
  - Net reduction: 3 handlers, massive code deduplication
  - Language support expanded from 4 to 11 languages through strategies
- **Plugin Loader Enhancement**: Plugin paths now resolve relative to `workspace_root` instead of CWD
  - Fixes plugin loading issues when daemon started from different directories
  - More robust plugin discovery for project-level handlers
- **Config Schema**: Added `project_languages` field to daemon config for strategy filtering
- **Test Organization**: Strategy tests organized by module (qa_suppression/, tdd/)

### Fixed
- **Hook Path Robustness**: Hook paths now use `$CLAUDE_PROJECT_DIR` to handle CWD changes in Bash commands (commit cc2bd1b)
  - Bug: Relative paths like `.claude/hooks/pre-tool-use` broke when Bash tool changed CWD
  - Fix: Updated installer to generate `"$CLAUDE_PROJECT_DIR"/.claude/hooks/*` patterns
  - Tests: Added unit tests for installer hook path generation and integration tests for settings validation
  - All hooks now robust against CWD changes during command execution

### Removed
- **Deprecated Handlers**: Replaced by unified strategy-based handlers
  - `eslint_disable` - Replaced by QaSuppressionHandler with JavaScript strategy
  - `python_qa_suppression_blocker` - Replaced by QaSuppressionHandler with Python strategy
  - `php_qa_suppression_blocker` - Replaced by QaSuppressionHandler with PHP strategy
  - `go_qa_suppression_blocker` - Replaced by QaSuppressionHandler with Go strategy
- **language_config.py**: Deleted in favor of strategy implementations with direct pattern definitions

## [2.8.0] - 2026-02-10

### Added
- **Project-Level Handlers**: First-class support for per-project custom handlers (Plan 00041, PR #21)
  - New `.claude/project_handlers/` directory structure for event-specific handlers
  - Automatic loading and registration of project handlers alongside library handlers
  - Priority-based execution with project handlers integrated into handler chains
  - Full test coverage (96.33% overall project coverage)
- **Project Handler CLI Commands**: Developer experience tools for scaffolding and managing project handlers
  - `scaffold-project-handler` - Generate handler templates with proper structure
  - `list-project-handlers` - Discover and validate project handlers
  - `validate-project-handler` - Lint and test individual handlers
- **Project Handler Documentation**: Comprehensive guides for creating custom handlers
  - `CLAUDE/PROJECT_HANDLERS.md` - Complete project handler development guide
  - `examples/project-handlers/` - Handler templates and examples for all event types
- **Optimal Config Checker Handler**: SessionStart handler that validates daemon configuration (bce7fb4)
  - Checks for missing/redundant handlers
  - Suggests priority optimizations
  - Validates configuration structure
- **Hedging Language Detector Handler**: Stop hook handler that identifies uncertain language patterns (62669a7)
  - Detects hedging phrases ("maybe", "possibly", "I think")
  - Advisory handler for improving code quality communication
- **Upgrade Detection Improvements**: Robust detection for broken installations (Plan 00043)
  - Detects missing venv, broken symlinks, corrupted config
  - Handles partial upgrades and installation failures
  - Improved error messages and recovery guidance

### Changed
- **Library/Plugin Separation**: Clear architectural boundaries (Plan 00034)
  - Library handlers in `src/claude_code_hooks_daemon/handlers/`
  - Project handlers in `.claude/project_handlers/{event_type}/`
  - Plugins in `.claude/hooks-daemon/plugins/`
  - Improved modularity and maintainability
- **PHP QA CI Integration**: Enhanced handlers for PHP quality checks (PR #20)
  - PHPCS handler improvements
  - PHPStan handler enhancements
  - PHP-CS-Fixer integration
- **Documentation Improvements**: Pre-release documentation drive
  - Updated README.md with clearer project overview
  - Enhanced CLAUDE.md with project handler documentation
  - Added four new user guides in `docs/guides/` (getting started, configuration, handler reference, troubleshooting)
  - Improved code examples throughout

### Fixed
- **Project Handler Config Passing**: Critical bug where project_handlers_config wasn't passed to daemon start (28c90e2)
- **Handler Template Keys**: Use snake_case keys in scaffolded templates for consistency (a200687)
- **Nested Installation Detection**: Prevent false positives when working on hooks-daemon repo itself (075450a)
- **Dogfooding Reminder Plugin**: Restore plugin accidentally deleted in Plan 00034 (27827bd)
- **Post-Merge QA Fixes**: Resolved all QA issues from PR #20 merge (f360f87)
- **Install/Update Instructions**: Use curl-to-file pattern for more reliable downloads (2941f18)

## [2.7.0] - 2026-02-10

### Added
- **Config Preservation Engine**: Complete config migration system with differ, merger, validator, and CLI (Plan 00041)
  - `config_differ.sh` - Detects changes between old and new default configs
  - `config_merger.sh` - Merges user customizations with new defaults
  - `config_validator.sh` - Validates merged config integrity
  - `config_cli.sh` - User-facing commands for config operations
  - 82 comprehensive tests for config preservation
- **Modular Bash Install Library**: 14 reusable modules in `scripts/install/` for DRY install/upgrade architecture (Plan 00041)
  - Core modules: `common.sh`, `logging.sh`, `validation.sh`, `backup.sh`
  - Config modules: `config_differ.sh`, `config_merger.sh`, `config_validator.sh`, `config_cli.sh`
  - Install modules: `git_operations.sh`, `venv_setup.sh`, `python_setup.sh`, `hook_scripts.sh`
  - Upgrade modules: `upgrade_checks.sh`, `rollback.sh`
- **Layer 2 Orchestrators**: Simplified install/upgrade entry points that delegate to modular library (Plan 00041)
  - `install_version.sh` - Install orchestrator (116 lines, down from 307)
  - `upgrade_version.sh` - Upgrade orchestrator (134 lines, down from 612)
- **VersionCheckHandler**: SessionStart handler that displays current daemon version at session start
- **Example Config File**: `.claude/hooks-daemon.yaml.example` with comprehensive handler documentation
- **Dynamic Example Config Validation**: Test ensures all library handlers are present in example config

### Changed
- **Handler Registry Architecture**: HandlerID constants as single source of truth for config keys (Plan 00039)
  - All handlers now use `HandlerID.HANDLER_NAME` for self-identification
  - Config keys automatically derived from handler IDs
  - Eliminates config key inconsistencies and typos
- **Status Line Enhancement**: Emoticon-based context display with color-coded quarter circle icons
  - Context usage now shows with colored emoticons matching percentage scheme
  - More intuitive visual feedback for context consumption
- **Install Architecture**: Layer 1 (modular library) + Layer 2 (orchestrators) separation (Plan 00041)
  - `install.sh` simplified from 307 to 116 lines (delegates to `install_version.sh`)
  - `upgrade.sh` simplified from 612 to 134 lines (delegates to `upgrade_version.sh`)
  - All logic now in reusable, testable Bash modules
- **Release Workflow Documentation**: Added mandatory QA and acceptance testing gates to release process
  - QA verification gate after Opus review (all checks must pass)
  - Acceptance testing gate after QA (all tests must pass)
  - FAIL-FAST cycle for test failures

### Fixed
- **auto_continue_stop Handler**: Fixed camelCase `stopHookActive` field detection (Plan 00042)
  - Handler now correctly detects stop_hook_active and stopHookActive
  - Added comprehensive logging for field detection
- **Upgrade Script Critical Fixes**: 8 critical fixes in upgrade process (Plan 00041)
  - Fixed heredoc to prevent variable expansion in config
  - Fixed hook script permissions (now executable after upgrade)
  - Fixed timestamped config backups to prevent overwriting
  - Fixed validation to skip when already on target version
  - Fixed silent config validation error swallowing
  - Fixed Python version detection and restart messaging
  - Fixed config delegation to project agent
  - Fixed hook script redeployment

## [2.6.1] - 2026-02-09

### Changed
- **Architecture Documentation**: Added comprehensive documentation clarifying daemon vs agent hooks separation
  - Documented when to use daemon handlers (deterministic, fast) vs native agent hooks (complex reasoning)
  - Added "When NOT to Write a Handler" section to HANDLER_DEVELOPMENT.md
  - Updated README.md with architectural principle explanations
  - Enhanced ARCHITECTURE.md with daemon/agent hooks distinction
- **Release Workflow Documentation**: Added critical warnings to prevent manual release operations
  - Added CRITICAL section to CLAUDE.md emphasizing mandatory /release skill usage
  - Documents why manual git tag/push operations are forbidden
  - Clarifies pre-release validation, version consistency, and Opus review workflow

### Fixed
- **Upgrade Instructions Security**: Fixed v2.6.0 upgrade instructions to use fetch-review-run pattern instead of curl pipe bash
  - Removes security risk of piping curl output directly to shell
  - Aligns with project's own curl_pipe_shell blocker handler
  - Updated CHANGELOG.md and upgrade documentation

## [2.6.0] - 2026-02-09

### Added
- **Client Installation Safety Validator**: Comprehensive validation system for client project installations that prevents configuration issues
  - Pre-install validation ensures no stale configs or runtime files
  - Post-install validation verifies correct daemon directory structure
  - Lazy-load imports to avoid dependency issues during installation
  - Prevents handler_status.py path confusion in client projects
- **/hooks-daemon-update Slash Command**: Auto-deployed during install/upgrade to provide guided LLM assistance for daemon updates
  - Always fetches latest upgrade instructions from GitHub
  - Works for all versions including pre-v2.5.0 installations
  - Ensures upgrade process uses current best practices

### Changed
- **Upgrade Documentation**: Standardized upgrade process to fetch-review-run pattern (avoids curl pipe shell pattern blocked by our own security handlers)
- **Complete Dogfooding Configuration**: Enabled all handlers in daemon's own config for comprehensive self-testing
  - Enabled strict_mode at daemon level for FAIL FAST behavior
  - Activated all safety handlers (curl_pipe_shell, pipe_blocker, dangerous_permissions, etc.)
  - Activated all workflow handlers (plan_completion_advisor, task_tdd_advisor, etc.)
  - Activated all session handlers (workflow_state_restoration, remind_prompt_library, etc.)
  - Activated all status handlers (git_repo_name, account_display, thinking_mode, usage_tracking)
- **Hook Script Regeneration**: Updated all hook scripts to match current installer output
  - Fixed config handler name (hello_world_pre_tool_use)
  - Ensures consistency between generated and committed scripts

### Fixed
- **Config Detection Logic**: Fixed handler_status.py to properly distinguish self-install vs client project mode
  - Now reads config file for self_install_mode flag instead of checking directory existence
  - Prevents reading wrong config file in client projects
  - All paths dynamically detected without hardcoded assumptions

## [2.5.0] - 2026-02-09

### Added
- **Lock File Edit Blocker Handler**: Prevents editing package lock files (package-lock.json, yarn.lock, composer.lock, etc.) - Plan 00031
- **5 System Package Safety Handlers**: Block dangerous package management operations (Plan 00022)
  - `pip_break_system` - Blocks pip --break-system-packages flag
  - `sudo_pip` - Blocks sudo pip install commands
  - `curl_pipe_shell` - Blocks curl/wget piped to shell
  - `dangerous_permissions` - Blocks chmod 777 and similar unsafe permissions
  - `global_npm_advisor` - Advises against npm install -g
- **Orchestrator-Only Mode Handler**: Opt-in mode for handlers that only run in orchestrator context (Plan 00019)
- **Plan Completion Move Advisor**: Guides moving completed plans to archive folder (Plan 00027)
- **TDD Advisor Handler**: Enforces test-driven development workflow with task-based guidance
- **Hostname-Based Daemon Isolation**: Multi-environment support with hostname-suffixed runtime files (sockets, PIDs, logs)
- **Worktree CLI Flags**: Added --pid-file and --socket flags for git worktree isolation (Plan 00028)
- **Programmatic Acceptance Testing System**: Ephemeral playbook generation from handler metadata (Plan 00025)
- **Plugin Support in Playbook Generator**: Acceptance tests now include plugin handlers (Plan 00040)
- **Config Validation at Daemon Startup**: Validates configuration before daemon starts (Plan 00020)
- **Comprehensive Handler Integration Tests**: Added integration tests for all handlers (Plan 00016)
- **Deptry Dependency Checking**: Integrated deptry into QA suite for dependency validation
- **LanguageConfig Foundation**: Centralized language-specific configuration for QA suppression handlers (Plan 00021)
- **Agent Team Workflow Documentation**: Multi-role verification structure with honesty checker (Plan 00030)
- **Worktree Automation Scripts**: Parallel plan execution with git worktree support
- **Code Lifecycle Documentation**: Complete Definition of Done checklists for features, bugs, and general changes

### Changed
- **Plugin System Architecture**: Complete overhaul with event_type field and daemon integration (Plan 00024)
- **QA Suppression Handlers**: Refactored to use centralized LanguageConfig data layer (Plan 00021)
- **Strict Mode Behavior**: Unified daemon.strict_mode for all fail-fast behavior across handlers
- **Acceptance Testing**: Migrated all 59+ handlers to programmatic acceptance tests with empty array rejection
- **Magic Value Elimination**: Removed all magic strings and numbers, replaced with constants (Plan 00012)
- **Plan Workflow**: Enhanced planning system with completion checklists and archive automation
- **Status Line Display**: Added effort level display and thinking toggle logic for Opus 4.6 extended thinking
- **Markdown Handler**: Allow writes outside project root for cross-project documentation (Plan 00029)
- **LLM Upgrade Experience**: Improved upgrade documentation and verification (Plan 00023)
- **Plugin Loader**: Handle Handler suffix correctly in class name detection
- **Duplicate Handler Priorities**: Made deterministic with warning logs for conflicts

### Fixed
- **HOTFIX: Decision Import**: Fixed wrong import path in 5 new handlers (constants.decision vs core.Decision)
- **Sed Blocker False Positive**: Fixed blocking of legitimate gh CLI commands
- **Plugin Schema Validation**: Fixed plugins config integration test validation
- **PreCompact Hook Schema**: Fixed systemMessage format validation
- **Daemon Path Isolation**: Fixed worktree isolation with proper path handling (Plan 00028)
- **Handler Instantiation Test**: Fixed test suite for dynamic handler loading
- **Markdown Plan Number Validation**: Corrected plan number detection in markdown files
- **Type Hints**: Fixed MyPy violations in 5 system package safety handlers
- **Magic Value Violations**: Eliminated remaining magic values in test_models.py and paths.py
- **Import Errors**: Removed non-existent qa_suppression_base import references
- **Plan Status Accuracy**: Corrected multiple plan completion statuses after audit
- **Test Failures**: Resolved hostname isolation test failures and fixture updates

### Security
- Maintained ZERO security violations across entire codebase
- All new handlers follow security best practices (no shell=True, proper subprocess usage)

### Documentation
- Added comprehensive Code Lifecycle guides (Features.md, Bugs.md, General.md)
- Enhanced PlanWorkflow.md with completion checklist and atomic commit guidance
- Added Agent Team workflow with multi-role verification
- Updated handler development guide with acceptance testing requirements
- Documented worktree workflow and parallel plan execution

## [2.4.0] - 2026-02-01

### Added
- **Security Standards Documentation**: Comprehensive security standards section in CLAUDE.md with ZERO TOLERANCE policy
- **Acceptance Testing Playbook**: Complete acceptance testing infrastructure with 15+ critical handler tests (Plan 00017)
- **Handler Status Report**: Post-install/upgrade verification script for handler discovery
- **Installation Safety**: Pre-installation check to prevent accidental reinstalls
- **Plan Lifecycle System**: Plan archival system with hard links and lifecycle documentation
- **ProjectContext Architecture**: Singleton module for project path management eliminating CWD dependencies (Plan 00014)
- **Repo Name in Status Line**: Repository name and model color coding in status line display
- **Planning Workflow Guidance**: Adoption guidance in install/upgrade documentation
- **Triple-Layer Safety**: Enhanced acceptance testing with FAIL-FAST cycle documentation
- **Implementation Plans**: Added plans for GitHub issues 11-15
- **Comprehensive Hooks Documentation**: Integration smoke tests and hook system documentation

### Changed
- **Release Process**: Established single source of truth in CLAUDE/development/RELEASING.md
- **Documentation Links**: Use @ syntax for doc links to force reading by LLMs
- **Upgrade Documentation**: Clarified daemon restart vs Claude Code restart procedures
- **Acceptance Testing**: Improved playbook clarity and practicality with detailed test cases
- **Installation Detection**: Nested installation detection now allows .claude dir inside hooks-daemon
- **Status Line Format**: Updated after protocol format change

### Fixed
- **SECURITY: File Path Handling**: Fixed init.sh to use secure daemon untracked directory instead of /tmp (B108)
- **SECURITY: Subprocess Security**: Fixed all security violations with TDD approach (B602, B603, B607, B404)
- **SECURITY: Dangerous Git Commands**: Added handler to block dangerous commands preventing data loss
- **Critical Protocol Bug**: Fixed handlers not blocking commands due to protocol format issue
- **TDD Enforcement**: Handle directories with 'test' in name correctly
- **Sed Blocker**: Detect sed patterns in echo commands
- **Version Inconsistency**: Fixed version mismatch and updated install.py status format
- **Plan Number Helper**: Block broken plan discovery commands
- **ProjectContext Initialization**: Initialize before config validation to prevent errors
- **Git Repo Name**: Parse from remote URL instead of directory name
- **Import Errors**: Fixed git_repo_name handler import issues
- **QA Failures**: Resolved all QA issues to prepare for release
- **Test Paths**: Achieved ZERO security violations with proper nosec documentation

### Security
- **B108 Violations**: Eliminated /tmp usage in favor of secure daemon untracked directory
- **B602/B603/B607/B404**: Fixed all subprocess security issues with comprehensive TDD approach
- **Dangerous Git Commands**: Blocked commands that can cause data loss
- Complete security audit achieving ZERO violations across entire codebase (Plan 00018)


## [2.3.0] - 2026-01-29

### Added
- Daemon-based status line with 20x faster rendering performance
- Handler for GitHub issue comments (`gh_issue_comments`) with full test coverage
- Auto-continue Stop handler for workflow automation
- Pipe blocker handler to prevent risky shell command patterns
- Account display and usage tracking in status line
- Log level environment variable override (`HOOKS_DAEMON_LOG_LEVEL`)
- Comprehensive input validation system at front controller layer (Plan 002)
- Planning workflow system with formal documentation and templates
- Handler ID migration system with QA enforcement (Plan 00012)
- Dogfooding test to ensure all production handlers enabled in strict mode
- Plan archive system for completed work (CLAUDE/Plan/Completed/)

### Changed
- Handler architecture to use `handler_id` constants (320 violations fixed in Plan 00012)
- Config architecture to use explicit `options` dict instead of extra fields
- Installation hardening to prevent nested installs
- Status line script performance and reliability
- Test coverage increased to 97% (3172 tests passing)
- Documentation improvements for FAIL FAST principle and error handling
- Plan numbering pattern to support 3+ digit formats

### Fixed
- **FAIL FAST**: Comprehensive error hiding audit and remediation (Plan 00008)
- Bash error detection and input validation across all handlers
- QA failures: tests, type errors, and installer synchronization
- Status line rendering bugs and race conditions
- Config validation and test data integrity
- Tool name and timeout violations in handler implementations
- Type annotation cleanup (removed unused `type: ignore` comments)

### Removed
- Usage tracking handler (disabled due to architectural issues)
- Fake UserPromptSubmit auto-continue handler (replaced with real Stop handler)

## [2.2.1] - 2026-01-27

### Fixed
- Fixed git hook executable permissions in repositories with core.fileMode=false
- Enhanced install.py to detect and handle permission tracking settings
- Added auto-update of git index for hook executability
- Added context-specific warnings for tracked vs untracked files

## [2.2.0] - 2026-01-27

### Added
- Custom sub-agents for QA and development workflow automation
- Automated release management system with `/release` skill
- Hook event debugging tool (`scripts/debug_hooks.sh`) for handler development
- Self-install mode support to CLI and configuration system
- Debug infrastructure for troubleshooting hook flows
- `.gitignore` requirement validation in installer
- Automatic config file backup during installation

### Changed
- Release system orchestration to avoid nested agent spawning
- Installer now displays `.gitignore` template with mandatory instructions
- Documentation improvements for README config completeness and plugin events

### Fixed
- Critical QA failures achieving 95% test coverage requirement
- Stop event schema validation failure
- Critical hook response formatting bug with JSON schema validation
- 4 upstream installation and CLI bugs
- DRY violation in error response handling
- Release skill registration (SKILL.md frontmatter)
- README documentation issues with config examples

## [1.0.0-alpha] - 2025-01-15

### Added
- Initial daemon implementation with Unix socket IPC
- Front controller pattern for handler dispatch
- Multi-project support via socket namespacing
- 14+ pre_tool_use handlers for safety, code quality, and workflow
- Handlers for all 10 Claude Code hook events
- YAML/JSON configuration system
- Plugin system for custom handlers
- Comprehensive test suite (95%+ coverage)
- QA tooling (ruff, mypy, black, bandit)
- Installation automation via install.py

### Performance
- Sub-millisecond response times after daemon warmup
- 20x faster than process spawn approach
- Lazy startup with auto-shutdown on idle

### Documentation
- README.md with installation and usage guide
- DAEMON.md with architecture details
- CLAUDE/ARCHITECTURE.md with design documentation
- CLAUDE/HANDLER_DEVELOPMENT.md with handler creation guide

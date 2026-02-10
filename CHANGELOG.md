# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

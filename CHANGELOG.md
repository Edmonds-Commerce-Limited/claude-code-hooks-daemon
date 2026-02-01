# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Comprehensive code review and issue fixes
- DaemonController for multi-event dispatch
- Python 3.8 compatibility fixes
- LICENSE file (MIT)
- CHANGELOG.md
- CONTRIBUTING.md

### Fixed
- CRIT-001: FrontController CLI constructor mismatch - daemon now starts correctly
- CRIT-002: init.sh undefined daemon_pid variable
- CRIT-003: Removed duplicate get_workspace_root() function
- HIGH-001: BritishEnglishHandler now correctly set as non-terminal
- Python 3.8 compatibility: replaced `X | Y` union syntax with `Union[X, Y]`

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

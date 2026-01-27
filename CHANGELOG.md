# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

# CLAUDE Directory - LLM-Optimized Documentation

This directory contains documentation optimized for LLM consumption (Claude, GPT, etc.) rather than human readers.

## Directory Purpose

- **Target Audience**: AI coding assistants
- **Format**: Markdown with high information density
- **Content**: Technical specifications, architecture documentation, development guides

## Files

### Architecture & Design

**ARCHITECTURE.md** - System architecture and design decisions
- Daemon architecture and component overview
- Handler system design
- Configuration system
- Plugin architecture

**HANDLER_DEVELOPMENT.md** - Guide for creating custom handlers
- Handler lifecycle and API
- Priority system
- Testing patterns
- Best practices

**DEBUGGING_HOOKS.md** - Critical tool for introspecting hook event flows
- Debug utility usage (`scripts/debug_hooks.sh`)
- Capturing event sequences for scenarios
- Analyzing logs to surgically decide which events to hook
- From scenario to handler: complete workflow
- Common debugging scenarios (planning mode, git ops, testing, etc.)

### Installation & Setup

**LLM-INSTALL.md** - LLM-optimized installation guide
- Installation workflow for AI assistants
- Troubleshooting common issues
- Verification steps

**LLM-UPDATE.md** - LLM-optimized update guide
- Version detection and upgrade path determination
- References RELEASES/ for version changelogs
- References UPGRADES/ for migration guides
- Config migration and rollback procedures

### Troubleshooting & Support

**BUG_REPORTING.md** (root directory) - Bug reporting and diagnostics
- Debug info script usage (`scripts/debug_info.py`)
- Automated diagnostic report generation
- Common issues and solutions
- Manual bug report template

### Development & Contributing

**development/** - Documentation for daemon repository development
- **RELEASING.md** - Release process using `/release` skill
- **QA.md** - QA pipeline and automation
- For developers working on the daemon codebase itself

## What NOT to Put Here

- ❌ Human-focused guides (use README.md or docs/)
- ❌ API documentation (use docstrings)
- ❌ Configuration examples (use examples/)
- ❌ Internal development tracking

## What TO Put Here

- ✅ Architecture decisions and rationale
- ✅ Design specifications
- ✅ LLM-specific installation/development guides
- ✅ Technical deep-dives for AI context

## Usage by LLMs

When working on this project, LLMs should:
1. Read README.md for overview and installation
2. Check ARCHITECTURE.md for system design
3. **Use DEBUGGING_HOOKS.md to introspect event flows before writing handlers**
4. Reference HANDLER_DEVELOPMENT.md for creating handlers
5. Use LLM-INSTALL.md for installation assistance
6. **Use LLM-UPDATE.md for updating existing installations**
7. Check BUG_REPORTING.md when troubleshooting issues
8. **Use development/RELEASING.md when publishing releases**
9. Read source code docstrings for API details

### Handler Development Workflow

**CRITICAL**: Always debug first, develop second:
1. Identify scenario ("enforce TDD", "block destructive git", etc.)
2. **Use `scripts/debug_hooks.sh` to capture event flow** (DEBUGGING_HOOKS.md)
3. Analyze logs to determine which event type and what data is available
4. Write tests (TDD)
5. Implement handler (HANDLER_DEVELOPMENT.md)
6. Debug again to verify handler intercepts correctly

## Maintenance

- Keep documentation concise and information-dense
- Update when architecture or design patterns change
- Delete outdated docs rather than accumulating them

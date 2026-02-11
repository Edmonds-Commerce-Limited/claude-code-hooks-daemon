# CLAUDE/development/ - Development Process Documentation

## Purpose

This directory contains documentation for **developers working on the hooks daemon repository itself**, NOT for users implementing hooks in their projects.

## Distinction

- **User Documentation**: `/CLAUDE/` root level (ARCHITECTURE.md, HANDLER_DEVELOPMENT.md, LLM-INSTALL.md)
  - How to use the daemon
  - How to create handlers
  - How to install and configure

- **Development Documentation**: `/CLAUDE/development/` (this directory)
  - How to contribute to the daemon codebase
  - Release management process
  - Testing and QA workflows
  - Code review guidelines

## Files in This Directory

- **RELEASING.md** - Complete release process using `/release` skill
- **QA.md** - QA pipeline, automation, and coverage requirements

## When to Use This Directory

Add documentation here when:
- Documenting internal development workflows
- Explaining how to modify the daemon core
- Describing release/deployment processes
- Internal architecture decisions that affect contributors

## When NOT to Use This Directory

Don't put documentation here for:
- User-facing features or APIs → `/CLAUDE/` root
- Handler development → `/CLAUDE/HANDLER_DEVELOPMENT.md`
- Installation guides → `/CLAUDE/LLM-INSTALL.md`
- Bug reporting → `/BUG_REPORTING.md`

## Navigation

- Parent: `/CLAUDE/` - User-facing LLM documentation
- Sibling: `/CLAUDE/UPGRADES/` - Version migration guides
- Related: `/CONTRIBUTING.md` - High-level contribution guidelines

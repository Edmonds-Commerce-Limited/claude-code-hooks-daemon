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

### Installation & Setup

**LLM-INSTALL.md** - LLM-optimized installation guide
- Installation workflow for AI assistants
- Troubleshooting common issues
- Verification steps

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
3. Reference HANDLER_DEVELOPMENT.md for creating handlers
4. Use LLM-INSTALL.md for installation assistance
5. Read source code docstrings for API details

## Maintenance

- Keep documentation concise and information-dense
- Update when architecture or design patterns change
- Delete outdated docs rather than accumulating them

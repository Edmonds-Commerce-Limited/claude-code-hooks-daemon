# Plan 00591: claude md auto commit waits for handler sources

**Status**: In Progress
**Created**: 2026-11-09
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #172

## Overview

On restart the daemon regenerates the CLAUDE.md handler block and
`ClaudeMdInjector._auto_commit_if_dirty` (`core/claude_md_injector.py`) commits
it with `commit --only CLAUDE.md`, judging only CLAUDE.md's own `git status`.
When a project or plugin handler's source file is still untracked or modified,
that commit puts a rule row on the branch that no committed code declares
(reported from a client project: the handler landed eight minutes later).

## Goals

- Before the auto-commit, the source files of the loaded `project_handlers:`
  and `plugins:` handlers are checked with git; if any is untracked or modified,
  CLAUDE.md is left uncommitted and one log line names the file that held it.
- With every such source clean (or none configured), behaviour is unchanged.

## Non-Goals

- Library handlers: their sources ship with the installed daemon.
- Turning the auto-commit off, or changing what the block contains.

## Tasks

### Phase 1: Hold the auto-commit

- [ ] 🔄 **Task 1.1**: RED tests in a temporary git repo (an untracked plugin
  handler holds the commit back; a modified project handler holds it back; all
  clean commits as today; no handlers configured commits as today). GREEN:
  gather the handler source paths the injector already knows of, or from the
  same loaders, and check them with the existing lock-free `run_git`. Release note.

## Success Criteria

- [ ] A restart with an uncommitted plugin handler leaves CLAUDE.md uncommitted, with a log line naming the file.
- [ ] Release-bound consequence recorded as a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Delivery & Milestones

- <!-- delivery commit hash -->

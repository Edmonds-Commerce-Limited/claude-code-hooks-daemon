# Task: Migrate untracked Claude memory into tracked project docs

**Type**: config-migration
**Severity**: critical
**Applies to**: all (the default flipped for everyone who has not set `allow_untracked_claude_memory`)
**Idempotent**: yes

## Why

From v3.24.0 the `markdown_organization.allow_untracked_claude_memory` option
defaults to `false` (Plan 00133). The daemon now **blocks** writes to Claude
auto-memory files (`~/.claude/projects/*/memory/*.md`) — via the Write/Edit
tools and via bash `>`/`>>`/`tee` redirects — and routes durable knowledge into
tracked, reviewed project docs instead. Untracked memory is per-checkout,
un-reviewed, invisible to teammates, and drifts from the repo.

**Reads are still allowed**, so any existing memory can be migrated out before
it becomes stale. Existing memory files are left untouched (inert) — the daemon
never deletes them; removal is your decision after migrating.

## How to detect if this applies to you

This applies to **every** project on the new default unless you have explicitly
set `allow_untracked_claude_memory: true`. To check whether you have existing
untracked memory worth migrating (sample — adapt the path to your home):

```bash
# Claude auto-memory lives under the per-project memory dir
ls -la ~/.claude/projects/*/memory/ 2>/dev/null
```

If that directory is empty or absent, there is nothing to migrate — you can keep
the new default with no further action.

## How to handle

1. **Decide the policy for this project.**

   - Keep the new default (recommended): durable knowledge goes in tracked docs.

   - Opt out (restore old behaviour): set, under `markdown_organization.options`
     in `.claude/hooks-daemon.yaml`:

     ```yaml
     allow_untracked_claude_memory: true
     ```

     Then restart the daemon. If you opt out, the rest of this task does not
     apply.

2. **Migrate existing memory into tracked docs** (progressive disclosure — keep
   ONE source of truth per fact and link to it):

   - **Always-relevant facts** → `CLAUDE.md` (keep it lean; it is resident every
     session).
   - **Path-specific guidance** → `.claude/rules/*.md` with `paths:` glob
     frontmatter (loads on demand when matching files are touched).
   - **Intent-triggered procedures** → a thin skill under `.claude/skills/` that
     points at a single-source-of-truth doc body.
   - **Human-facing reference** → `docs/`.
   - Link between docs with plain markdown links (zero token cost until
     followed); **avoid `@`-imports** (they re-inline eagerly).

   Skip anything already recorded in the repo (changelogs, git history, code) —
   do not copy derivable content. Capture only the genuinely non-derivable
   knowledge. (This repository's own migration is `CLAUDE/development/LESSONS.md`
   — a worked example of the rubric.)

3. **Leave the source memory files in place** until you have confirmed the
   migrated docs are correct and committed. Deletion is your call, not the
   daemon's.

## How to confirm

- The durable knowledge now lives in tracked files that show up under
  `git status` / are committed.

- A test write to memory is blocked, and a read still works (sample):

  ```bash
  # Expect: blocked (deny) for the write, allowed for the read
  echo "x" >> ~/.claude/projects/<slug>/memory/MEMORY.md   # blocked
  cat ~/.claude/projects/<slug>/memory/MEMORY.md           # allowed
  ```

## Rollback / if this goes wrong

- To restore the previous always-allow behaviour, set
  `allow_untracked_claude_memory: true` under `markdown_organization.options` in
  `.claude/hooks-daemon.yaml` and restart the daemon.
- No data is lost by the policy itself — it only blocks *new* writes. Original
  memory files are never modified or deleted by the daemon.

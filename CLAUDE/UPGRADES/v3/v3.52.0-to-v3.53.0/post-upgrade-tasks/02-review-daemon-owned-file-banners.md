# Task: Expect a large, comment-only diff in your committed daemon files

**Type**: notification
**Severity**: optional
**Applies to**: all
**Idempotent**: yes

## Why

The daemon deploys a handful of files into directories your project owns and
commits — they only work if they are committed, so they are deliberately not
git-ignored the way `.claude/hooks-daemon/` is. Until this release none of them
said so, which is how a client repo ended up linting 3,100 lines of upstream
PTY-supervisor source it could neither fix nor silence (Plan 00217).

Each of those files now opens with an ownership banner naming it as
daemon-owned and pointing at the boundary documentation. Because they are
refreshed on every upgrade, this upgrade rewrites all of them at once — around
39 files in a typical install. The change is **comments only**; no behaviour
changed in any of them.

## How to detect if this applies to you

It applies to every install. After upgrading, `git status` will show modified
files under `.claude/hooks/`, plus `.claude/init.sh`,
`.claude/skills/hooks-daemon/scripts/*.sh`, and — if you use them —
`CLAUDE/Plan/mkplan.bash` and `.claude/ccy/claude-supervise.py`.

Sample:

```bash
git diff --stat -- .claude/hooks .claude/init.sh .claude/skills CLAUDE/Plan/mkplan.bash .claude/ccy
```

## How to handle

1. **Confirm the diff is comment-only** before committing it. Sample:

   ```bash
   git diff -U0 -- .claude/hooks | grep '^[+-]' | grep -v '^[+-][+-]' | grep -v '^[+-]#'
   ```

   An empty result means every changed line is a comment. If anything else
   appears, stop and inspect — that would not be expected from this upgrade.

2. **Commit the files.** They are meant to be tracked; leaving them dirty makes
   every future `git status` noisy and hides real changes.

3. **Read the new boundary section** if your project runs quality gates over
   `.claude/`: `CLAUDE/LLM-INSTALL.md` → "Which Files Under `.claude/` Are
   Yours?". It enumerates every daemon-owned path and gives copy-pasteable ruff
   and shellcheck exclusions. Every one of those files is checked upstream
   against its language's **default** rule set, so you should only need an
   exclusion if your project selects stricter rules than the defaults.

4. **If a daemon-owned file reports a finding under DEFAULT rules**
   (`ruff check --isolated`, `shellcheck` with no rc), that is an upstream bug —
   please report it rather than excluding around it.

## How to confirm

`git status` is clean for the paths above, and your own lint run reports nothing
from them.

## Rollback / if this goes wrong

Nothing to roll back — the change is comment-only and the files are regenerated
from the daemon on every install and upgrade. If a file was hand-edited locally
before upgrading, that edit was already being discarded on every upgrade;
recover it from `git log -p -- <path>` and move the logic into a project-level
handler or your own script instead.

# Task 1.2 (duplicate-block half) — fix report

**Scope**: clear the two `duplicate-block` findings from `bin/hooks-daemon docs-qa --sweep`
named in Task 1.2. The two `module-doc-budget` findings were explicitly out of scope
(owner fixing those in parallel).

## Finding 1: `CLAUDE/Architecture/StatusLine.md:207-215` duplicate of `README.md:223-231`

Both files carried an identical fenced `json` block (the `.claude/settings.json`
`statusLine` registration). Per R1/R3 (agent tree owns the depth; `README.md` is a
human-facing satellite), the canonical home is `CLAUDE/Architecture/StatusLine.md`
("Claude Code Settings (settings.json)" section), which already carries the fuller
explanation (including the `bash <path>` executable-bit rationale citing Plan 00102).

**Fix**: extract-and-link (R1). `README.md`'s "Setup" section no longer repeats the
JSON block or its rationale paragraph; it now points at
`CLAUDE/Architecture/StatusLine.md#claude-code-settings-settingsjson` and keeps only
the README-specific application note (the daemon's auto-suggestion / `DAEMON FAILED`
indicator sentence, which is not stated in the target).

**File changed**: `/workspace/README.md`

## Finding 2: `CLAUDE/PROJECT_HANDLERS.md:172-176` duplicate of `CLAUDE/core/Worktree.core.md:881-885`

Both carried an identical 3-line `bash` fence (`hooks-daemon restart` /
`hooks-daemon status` / `# Expected: Status: RUNNING`). `CLAUDE/core/Worktree.core.md`
is DAEMON-OWNED (deployed and overwritten wholesale on every install/upgrade — its own
header says "never hand-edit it"), so it could not be turned into a pointer or given an
explicit `<!-- ssot-anchor -->` marker. This is also exactly the case R4b names as its
own worked example ("a short verification snippet repeated at several points of use"),
and `structured_blocks.py`'s own docstring cites this project's `hooks-daemon restart`
/ `status` idiom as the canonical illustration of that mechanism.

**Fix**: R4b (`ssot-quote`), applied only to the non-daemon-owned side. Wrapped
`PROJECT_HANDLERS.md`'s block in
`<!-- ssot-quote: CLAUDE/core/Worktree.core.md#skipping-daemon-restart-verification -->`
… `<!-- /ssot-quote -->`. `Worktree.core.md` has no explicit `ssot-anchor` marker at
that point, so the anchor resolves via the heading-slug fallback against its own
`### ❌ Skipping Daemon Restart Verification` heading — confirmed unique in that file
and confirmed to slugify (via the project's pinned `slugify_heading`, which drops the
emoji as a non-word character) to exactly `skipping-daemon-restart-verification`.

**File changed**: `/workspace/CLAUDE/PROJECT_HANDLERS.md`

`CLAUDE/core/Worktree.core.md` was **not** touched (daemon-owned, never hand-edited).

## Verification

`bin/hooks-daemon docs-qa --sweep --json` (captured to
`untracked/scratch/docsqa-after.json`) now returns `[]` / exit 0 — both target
`duplicate-block` findings are gone, no `quote-drift` finding appeared (confirming the
new `ssot-quote` verifies against its source span), and no new findings of any kind
were introduced. The two `module-doc-budget` findings were already clear at sweep time
(the parallel fix), which is expected and out of this report's scope.

## Working-tree state

Only `README.md` and `CLAUDE/PROJECT_HANDLERS.md` were modified. Nothing staged,
committed, or pushed — left for the plan owner to review/commit alongside the
`module-doc-budget` fix.

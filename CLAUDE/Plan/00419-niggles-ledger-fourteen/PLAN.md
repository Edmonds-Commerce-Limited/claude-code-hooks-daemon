# Plan 00419: niggles ledger fourteen

**Status**: In Progress
**Created**: 2026-09-15
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The rolling ledger for defects found in passing. Ledger thirteen
([00413](../Completed/00413-niggles-ledger-thirteen/PLAN.md)) closed with all
seventeen entries terminal, so this is the open one.

## Goals

- Record each niggle with enough evidence that someone else can reproduce it.
- Resolve each entry to a terminal state: fixed, graduated to its own plan, or
  dismissed as not-a-defect with the reasoning kept.

## Non-Goals

- **Becoming a feature plan.** A niggle that needs design graduates to its own
  numbered plan and leaves a pointer here.

## Niggles

### N1 — `debug_hooks.sh` cannot work in the repository that dogfoods it

Found by a sub-agent following Plan 00418 Task 1.1, which names
`scripts/debug_hooks.sh` as the way to capture real hook payloads.
`CLAUDE/DEBUGGING_HOOKS.md` says the same, and `CLAUDE/HANDLER_DEVELOPMENT.md`
tells handler authors to debug first rather than guess at `hook_input`'s shape.
The script fails on this repository, and has two independent defects.

**Defect 1 — it looks in the wrong place for a self-install.**
`scripts/debug_hooks.sh:32` searches
`$PROJECT_ROOT/.claude/hooks-daemon/untracked/`. That directory **does not
exist here**: in self-install mode the daemon IS the project, and its sockets
live at `$PROJECT_ROOT/untracked/` — verified, two are there now
(`untracked/daemon-*.sock`). The comment above the line says it "supports both
suffixed (container) and unsuffixed (desktop) paths", which is true and beside
the point: it handles two socket NAMES and only one LAYOUT.

**Defect 2 — it dies before reaching its own fallback.** The line is

```bash
SOCKET_PATH=$(find "$PROJECT_ROOT/.claude/hooks-daemon/untracked/" -name "daemon*.sock" 2>/dev/null | head -n1)
```

under `set -euo pipefail`. `find` on a missing directory exits 1; `pipefail`
carries that through `head`'s success; the assignment therefore fails and
`set -e` kills the script — **before** the `CLAUDE_HOOKS_SOCKET_PATH` fallback
five lines below. So the env-var escape hatch is unreachable on exactly the
layout that needs it, and the failure is silent: no message, no non-zero
explanation, just nothing.

Reproduced directly rather than reasoned about, and the first attempt to
reproduce it was WRONG in an instructive way: running the pipeline bare in a
subshell reaches the next line and exits 0. It only dies in the ASSIGNMENT form,
because that is what makes the pipeline's status the statement's status. A
reproduction that drops the assignment concludes there is no bug.

**Why it matters more than a broken script.** Three documents route an agent
here as the sanctioned alternative to guessing at payload shapes. An agent that
follows that instruction gets silence, concludes the tool is unavailable, and
falls back to inference — which is precisely the failure mode Plan 00418 exists
to avoid, since the handler it is rebuilding was deleted the first time because
the project reasoned about a hook field from documentation instead of capture.

### N2 — archiving a plan silently breaks every link it makes to a sibling

Archiving moves `CLAUDE/Plan/NNNNN-x/` to `CLAUDE/Plan/Completed/NNNNN-x/`, one
level deeper. Every `](../00NNN-y/PLAN.md)` the plan contains then resolves to
`Completed/00NNN-y/...`, which does not exist — so a plan's OUTBOUND links all
break at the moment it is archived.

Found the day 00413 was archived: eight dead links across its `PLAN.md` and
`NIGGLES.md`, every one pointing at a plan that had graduated out of it
(00414, 00415, 00416). Those pointers are the entire reason a reader opens an
archived ledger, so the links that break are the load-bearing ones.

**Two separate gaps, and the second is the more interesting:**

1. **The archival procedure does not repoint outbound links.** The Plan
   Completion Checklist covers the `git mv`, the index row, the statistics and
   the retention window — all of which are about the plan's INBOUND references
   and the index. Nothing addresses the links pointing the other way.

2. **`plan-qa --sweep` reports the tree CLEAN with eight dead links in it.**
   Verified: the sweep was run immediately after the archival and again after
   this was found, and reported `0 findings` both times. Only docs-QA notices,
   as an ADVISORY — which is how it reached a sub-agent's QA run as unexplained
   noise in an unrelated worktree rather than reaching the person who broke it.

The inbound direction is already handled better, which is what makes the gap
easy to miss: links pointing AT an archived plan were caught the same day by a
docs-QA block on an edit. Direction determines whether you find out.

**Remedy is not yet decided** and it is a real fork: repoint links during
archival (mechanical, but rewrites an archived document), or teach `plan_qa` to
resolve links so the sweep stops reporting clean when it is not. The second is
the better guard — it catches the case regardless of how the links broke — but
it does not fix the eight that already broke, and it is the sweep's own
credibility at stake: a sweep that says "clean" while a tree is not is worse
than no sweep, because it is believed.

## Tasks

- [x] ✅ **Task 1.1**: N1 — RED first, both defects tested separately, in
  `tests/unit/scripts/test_debug_hooks_socket_discovery.py`. Clean RED was 4
  failed / 3 passed: the client-install case PASSED from the start, which is the
  point of separating them — a single test would have conflated "wrong layout"
  with "dies on a missing directory" and a fix for either could have looked
  complete.

  The tests extract the script's own discovery block and run it in a real
  `bash`, because the defect lives in shell semantics (`set -e` + `pipefail` +
  command substitution) that no Python-level assertion can observe. One guard
  pins that the fix does not reach for `|| true`.

- [x] ✅ **Task 1.2**: N1 fixed. Both layouts are searched in order, each
  directory tested with `-d` before it is searched, and `mapfile` from a process
  substitution replaces `find | head -n1` — which also removes a latent SIGPIPE
  in the producer when the reader closes early. The
  `CLAUDE_HOOKS_SOCKET_PATH` fallback is now reachable, and the not-found error
  names both searched locations instead of only the one that does not exist
  here.

  Proved on the real repository, not only in tests: discovery resolves
  `/workspace/untracked/daemon-*.sock`. Before the fix it produced nothing and
  exited silently. `bash -n` and `shellcheck -x` both clean.

- [x] ✅ **Task 1.3**: N2 — the eight links 00413's archival broke are
  repointed (`../` to `../../` in `PLAN.md` and `NIGGLES.md`), and each verified
  to resolve on disk rather than by eye.

- [ ] ⬜ **Task 1.4**: N2's remedy — decide between repointing at archival time
  and teaching `plan_qa` to resolve links, then build it. Owner-gated: the
  second changes what `--sweep` blocks on across every project, which is not a
  change to make unasked.

## Success Criteria

- [x] ✅ `scripts/debug_hooks.sh` resolves a socket in this repository, and a
  test fails if the self-install layout stops being found.

- [x] ✅ A missing socket directory produces the script's own readable error,
  not a silent `set -e` death, and the documented env-var escape hatch is
  reachable.

- [ ] ⬜ **Assessed when this ledger closes, not before**: every entry is
  terminal — fixed with a RED-first test, determined from the record, or
  graduated to its own numbered plan. Open while this is the current ledger,
  because a rolling ledger exists to keep collecting.

## Delivery & Milestones

- Opened because ledger thirteen closed, by the convention recorded in
  `CLAUDE/Plan/CLAUDE.md`: a niggle is appended to the open ledger, and if none
  is open a new one is scaffolded.

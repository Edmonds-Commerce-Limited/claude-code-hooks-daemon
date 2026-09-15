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

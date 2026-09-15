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

**New evidence, and it narrows the fork to one option.** Archiving 00409 broke
two inbound links in Plan 00408 — one in `PLAN.md`, one in a `JOURNAL/`
day-file. Repointing the `PLAN.md` one was uneventful. Repointing the JOURNAL
one tripped `journal-append-only`, because a journal is append-only and a
repoint is by definition a rewrite of an earlier entry. Leaving it dead tripped
`pointer-resolves` at BLOCK. Both were observed as real handler output, in that
order, rather than reasoned about.

So the two rules genuinely contradict each other on a journal link, and no
archival procedure can satisfy both: **"repoint outbound links at archival
time" is not a remedy a JOURNAL can accept.** That leaves teaching the resolver
that a plan may have moved to `Completed/` as the only option which fixes the
class without rewriting an append-only record — and it is independently the
better guard. The fork this ledger recorded as open is closed by the
constraint, not by preference.

### N3 — the two plan-close gates are mutually exclusive on the legal close path

Closing a plan legitimately requires two changes to `PLAN.md`: a ticked
holding-area success criterion, and a terminal status header. Each gate refuses
the other's change when it arrives first:

- `plan_done_requires_holding_area` refuses the status flip while no
  holding-area criterion is present.
- `header-body-coherence` refuses a fully-ticked body under a non-terminal
  header — which is exactly what adding the criterion first produces.

So neither order works. Both gates are individually correct and neither is
wrong about the state it refuses; the defect is that no sequence of single
edits satisfies both, because each is judging an intermediate state that only
exists on the way to a valid one.

The escape is a single whole-file `Write` carrying both changes, so the content
is judged once in its final shape. That works, but nothing says so — an agent
discovers it by being blocked twice and inferring it. This happened three times
in one session (00409, 00417, and once more before that), each time costing two
blocked calls and a re-read of the file.

**Candidate remedies**, none chosen:

1. Have `header-body-coherence` ignore the holding-area criterion specifically
   when judging "the body claims completion" — it is a step TOWARDS closing,
   not a claim of being closed.
2. Have `plan_done_requires_holding_area` accept a status flip when the
   criterion is being added in the same write (it already sees whole content).
3. Document the whole-file `Write` as the sanctioned close move, and have
   whichever gate fires second say so in its remediation.

(3) is the cheapest and the weakest: it makes the workflow learnable without
making it sound. (1) looks most correct — the criterion is a precondition of
closing, so reading it as a completion claim is the actual category error.

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
  directory tested with `-d` before it is searched, and a `read` loop over a
  process substitution replaces `find | head -n1` — which also removes a latent
  SIGPIPE in the producer when the reader closes early. The first version of
  this fix used `mapfile`, which is bash 4+ and broke this project's own macOS
  `/bin/bash` 3.2.57 portability gate; caught by the full QA run on merged main,
  not by the targeted tests, because the portability check is a separate sweep
  over shell scripts. Fixing one defect inside a block is exactly when the next
  one gets introduced. The
  `CLAUDE_HOOKS_SOCKET_PATH` fallback is now reachable, and the not-found error
  names both searched locations instead of only the one that does not exist
  here.

  Proved on the real repository, not only in tests: discovery resolves
  `/workspace/untracked/daemon-*.sock`. Before the fix it produced nothing and
  exited silently. `bash -n` and `shellcheck -x` both clean.

- [x] ✅ **Task 1.3**: N2 — the eight links 00413's archival broke are
  repointed (`../` to `../../` in `PLAN.md` and `NIGGLES.md`), and each verified
  to resolve on disk rather than by eye.

- [ ] ⬜ **Task 1.4**: N2's remedy — build the resolver that knows a plan may
  have moved to `Completed/`. The fork this task was opened to decide is now
  settled by constraint rather than preference (see N2's new evidence): a
  journal link cannot be repointed without violating append-only, so
  "repoint at archival time" is not available. Still owner-gated, because it
  changes what `--sweep` blocks on across every project.

- [ ] ⬜ **Task 1.5**: N3 — choose between the three candidate remedies and
  build it. Owner-gated: (1) and (2) both relax a gate that currently blocks,
  and relaxing a correct gate to fix a sequencing problem is the kind of change
  that should be asked for rather than assumed.

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

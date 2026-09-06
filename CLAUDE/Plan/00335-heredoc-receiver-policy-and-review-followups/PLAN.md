# Plan 00335: heredoc receiver policy and review followups

**Status**: Not Started
**Created**: 2026-09-06
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

This plan carries the non-blocking findings from the v3.62.0 release
code-review gate, filed per the "Never drop a finding" rule in
[RELEASING.md](../../development/RELEASING.md). The gate's three BLOCKING
findings were fixed and shipped in v3.62.0 (`b149808f`, `67471f47`); nothing
here is a shipped-broken security hole. What follows is the residue that was
deliberately not fixed before the tag, because editing after the reviewer's
PASS would have meant the shipped tree was not the tree that was reviewed.

The centre of gravity is Phase 1, which is a **design decision, not a bug
fix**. Two of the findings pull in opposite directions on the same question —
how `curl_pipe_shell` decides whether a quoted-heredoc body is data or a
payload — and fixing either one alone partly undoes the other. They are
sequenced together for that reason.

Phases 2-4 are independent and can proceed in any order. Evidence for every
finding is preserved in this folder (`review-report.md`, `probes/`) because
the original lived in gitignored `untracked/`, which does not survive a
container restart.

## Goals

- Decide and implement a single coherent receiver policy for the
  quoted-heredoc exemption, resolving the `jq` over-block and the inversion
  proposal as one decision.
- State the expansion-receiver limit in the code and in resident guidance, so
  it is a recorded decision rather than an undiscovered gap.
- Close the two `project_containment` path-resolution gaps (I1, I2), both
  re-confirmed as reproducing on shipped code.
- Fix the docstring/behaviour contradiction in `_close_session` (I4) and the
  two config-gated defects (I3, I5).

## Non-Goals

- ~~**Closing the word-expansion receiver family**~~ — **superseded by
  Decision 1, and now CLOSED.** This was excluded on the reviewer's reasoning
  that the family is unbounded (`${x:0:0}bash`, `$(printf bash)`, …) so no
  finite normalisation closes it. That reasoning holds only for an allowlist
  of BAD receivers. Inverting to an allowlist of data sinks closes the family
  without resolving anything: `b$ash` and `SHELL` are simply not sink names,
  so they withhold the exemption like any other unrecognised word. All ten
  obfuscated shapes in the reviewer's corpus now DENY. `$SHELL` still is not
  *resolved* — it does not need to be.
- Re-opening any of the three blocking findings already fixed in v3.62.0.

## Tasks

### Phase 1: Receiver policy for the quoted-heredoc exemption

Decide first, then implement. Do not start with the narrow fix — Task 1.1's
outcome determines whether Task 1.2 is still wanted.

- [x] ✅ **Task 1.1**: Decided — **the inversion**, which subsumes the narrow
  fix rather than competing with it. Recorded in `DECISIONS.md`. Probing the
  shipped handler before deciding (`probes/probe_phase1.py`) settled it: it
  found a FOURTH live bypass the review missed — `ssh host <<'EOF'` executes
  the body on the remote host and was ALLOWED — which is decisive evidence
  that the executor family cannot be enumerated.
- [x] ✅ **Task 1.2**: Implemented. `_DATA_SINKS` replaces the interpreter and
  executor receiver lists in `curl_pipe_shell`; a new
  `quoted_heredoc_command_words` reports one command word per heredoc for an
  allowlist caller, leaving `quoted_heredoc_receivers` (which must report
  every word for its opposite question) untouched. The `jq -r .` over-block
  disappears by construction: arguments are no longer consulted, so `.` has
  no list to be on. 21 new tests.
- [x] ✅ **Task 1.3**: Corpus re-run green — **0 ordinary misses, 0
  obfuscated misses, 0 false positives**. All 11 data-heredoc controls keep
  their exemption and `jq -r .` joins them. Full suite 18,103 passed.

### Phase 2: Write down what the exemption now promises

Re-aimed by Decision 1. The original task was to document the expansion
family as an unclosed limit; the inversion closed it, so the thing that needs
writing down is the ALLOWLIST and its failure direction instead.

- [x] ✅ **Task 2.1**: Docstrings state it —
  `quoted_heredoc_command_words` explains why an expansion-built word needs
  no resolving under an allowlist, and `_scannable` records the four failed
  enumerations that motivated the inversion.
- [x] ✅ **Task 2.2**: Resident guidance (`get_claude_md`) now states the
  exemption is an allowlist, names the common sinks, gives `ssh` /
  `eval "$(cat …)"` / `. /dev/stdin` as why an unknown receiver is not
  trusted, and keeps the `project_containment` framing: a clean command is
  not evidence the body is inert, only that its receiver is recognised. It
  also states that withholding SCANS rather than denies, so the guidance
  does not overstate the cost.

### Phase 3: `project_containment` path resolution

Both re-confirmed reproducing on shipped code (`probes/probe_containment.py`).

- [ ] ⬜ **Task 3.1** (I1): Resolve relative destinations for
  flag/positional commands. `_destination_targets()` returns RAW TOKENS
  and `_is_outside()` declares any non-absolute path "never outside", so
  `echo hi > ../../tmp/out.txt` DENIES while
  `curl … -o ../../../tmp/x.sh`, `wget -O`, `mkdir -p`, `tar -cf` and
  `rsync` with the same traversal all ALLOW. Two commands with identical
  effect get opposite verdicts purely by extraction route. The stated
  rationale ("resolves against a working directory the daemon does not
  know") is contradicted by the sibling accessor one layer down, which
  does know it (`HookInputField.CWD`). Fix: run `_destination_targets`
  output through the same cwd-join before the containment test.
  Location: `handlers/pre_tool_use/project_containment.py:247-282,     383-389`.
- [ ] ⬜ **Task 3.2** (I2): A trailing slash makes a copy destination vanish —
  `cp README.md /tmp/` yields no target at all, while
  `cp /repo/README.md /tmp/copy.md` denies. This is arguably the most
  natural spelling of the thing the handler exists to stop, and the
  handler's own resident guidance calls its covered-shape list
  "exhaustive, not illustrative". Declining is correct for a CONTENT
  guard (nothing is authored at `/tmp/`), but a containment guard wants
  `dest/<basename>`. Location: `core/utils.py:557-558`
  (`_resolve_write_target`).
- [ ] ⬜ **Task 3.3**: Record, in guidance rather than code, two limits the
  probe re-confirmed: `cd /tmp && echo hi > out.txt` resolves against the
  SESSION cwd (the shared accessor's documented limit), and a
  triple-nested `sh -c` yields no target. Decide whether the nesting depth
  is worth raising or is correctly a documented bound.

### Phase 4: Independent defects

- [ ] ⬜ **Task 4.1** (I4): `remote_docs/fetchers.py:131-149, 204-210` —
  `_close_session` raises `CaptureError` from inside a `finally`, so a
  cleanup failure supersedes the real fetch error. Its own docstring says
  it must not do this ("raising here would replace a real fetch error with
  a cleanup one"). The likeliest trigger — a missing or renamed binary —
  makes BOTH raise, so the operator sees the reap failure and not the
  cause. Either restore the documented behaviour (log at warning, do not
  raise) or correct the docstring; as it stands the rationale on the page
  is false. Appears to be collateral from `a734b19d`.
- [ ] ⬜ **Task 4.2** (I3): `docs_qa/checks/source_tree_markdown.py` and
  `docs_qa/checks/module_doc_budget.py` (`_walk_into`) —
  `may_contain_vendor_exception` returns True unconditionally for any
  pattern with no literal prefix, so a single `**/ours/**`
  `vendor_exceptions` entry un-prunes EVERYTHING, including `.git` and
  `untracked/`. A vendor exception can never live in either, so the
  conservative fallback should not apply to `_OWN_EXCLUDED_DIR_NAMES`. In
  this repository `untracked/` holds virtualenvs and worktrees, so this is
  a large silent slowdown on every sweep for any project that sets the
  key.
- [ ] ⬜ **Task 4.3** (I5): `install/core_docs.py:368-381` — core-doc
  deployment derives its target directory from
  `plan_workflow.workflow_docs`' parent, so all three documents follow
  `PlanWorkflow`'s configured location. Only `PlanWorkflow` has a config
  key of its own; `Worktree` and `DocumentationStrategy` are named by
  handler and check text as `CLAUDE/Worktree.md` and
  `CLAUDE/DocumentationStrategy.md`. With
  `workflow_docs: docs/agent/PlanWorkflow.md` the latter two deploy to
  `docs/agent/`, recreating the precise defect Plan 00334 exists to fix —
  guidance naming a file that does not exist — for the two documents that
  cannot be renamed. Also: `workflow_docs: "PlanWorkflow.md"` yields
  `parent == "."` and scatters `core/` into the project root. Correct in
  the default configuration, which is why it did not block.

## Success Criteria

- [ ] Phase 1's decision is recorded in `DECISIONS.md` with the trade stated,
  not just the outcome.
- [ ] `jq -r . <<'EOF'` behaves per the recorded decision, with a regression
  test pinning it.
- [ ] The 34-shape receiver corpus still yields zero misses, and all 11
  data-heredoc controls keep their exemption.
- [ ] The expansion limit is stated in both the docstring and resident
  guidance.
- [ ] `curl -o`, `wget -O`, `mkdir -p`, `tar -cf` and `rsync` with a relative
  traversal outside the root all DENY, matching the redirect route.
- [ ] `cp README.md /tmp/` DENIES.
- [ ] A fetch error survives a concurrent close failure, and `fetchers.py`'s
  docstring matches its behaviour.
- [ ] A leading-wildcard `vendor_exceptions` entry no longer un-prunes `.git`
  or `untracked/`.
- [ ] Core docs deploy to the location each document's own guidance names,
  under a non-default `workflow_docs`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00335-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed from the v3.62.0 release gate; source review at `review-report.md`,
  probe harness at `probes/`.

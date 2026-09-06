# Plan 00335: heredoc receiver policy and review followups

**Status**: Complete
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

Both were re-confirmed reproducing on shipped code before being fixed
(`probes/probe_containment.py`), which mattered: the dedupe scout had
reported Plan 00333 already resolved these.

- [x] ✅ **Task 3.1** (I1): Relative destinations now resolve. A new
  `_resolve_against_cwd` joins every `_destination_targets` result against
  `HookInputField.CWD` before the containment test, so the flag/positional
  route and the redirect route finally agree. `curl -o`, `wget -O`,
  `mkdir -p`, `tar -cf` and `rsync` with a `../../../tmp/` traversal all DENY
  where all five previously ALLOWed.
- [x] ✅ **Task 3.2** (I2): `cp README.md /tmp/` now DENIES.
  `_resolve_write_target` strips a trailing slash instead of declining the
  token outright, and the "declared to be a directory" test moved into
  `_written_paths` keyed on the RAW destination — so it still declines rather
  than guesses when a trailing-slash target is not actually a directory.
  Content guards are provably unaffected: only `authored=True` candidates
  reach them via `get_written_file_paths(authored_only=True)`, and those never
  carry `sources`.
- [x] ✅ **Task 3.3**: Both limits recorded and deliberately left as bounds.
  `cd /tmp && echo hi > out.txt` still resolves against the SESSION cwd — the
  shared accessor's documented limit, not this handler's — and a
  triple-nested `sh -c` still yields no target while the doubled form is
  caught. Neither is worth chasing here: the first needs session cwd
  tracking, the second is a depth bound that trades off against scanning cost.

### Phase 4: Independent defects

- [x] ✅ **Task 4.1** (I4): `_close_session` no longer raises from inside a
  `finally`, so a fetch error survives a concurrent close failure. It logs the
  close failure at WARNING with the binary name and the underlying exception,
  caught by type rather than bare — handled, not silenced. The docstring was
  aspirational rather than descriptive and now matches the code.

  This tripped the project's own error-hiding audit (`log-and-continue`),
  which is the correct thing for that audit to notice. Resolved through the
  audited exclusions registry — NOT an inline suppression — with the reasoning
  recorded: in a `finally`, the only alternative to logging IS masking, and
  suppressing the primary error to report a cleanup error is strictly worse
  than the pattern the rule exists to catch. The entry names its own reversal
  path.

- [x] ✅ **Task 4.2** (I3): `_walk_into` in both `source_tree_markdown.py` and
  `module_doc_budget.py` now checks `_OWN_EXCLUDED_DIR_NAMES` first and returns
  immediately, before the conservative vendor-exception fallback can run. A
  leading-wildcard `vendor_exceptions` entry no longer un-prunes `.git`,
  `untracked/` or `worktrees`, while a genuinely vendored directory is still
  descended — the conservative behaviour exists for a reason and is preserved,
  pinned by its own test.

  Noted but NOT actioned: the two `_walk_into` implementations are
  near-identical (one carries an extra `scope_exclude_globs` parameter). A
  shared helper is plausible, but a refactor was out of proportion to the fix.

- [x] ✅ **Task 4.3** (I5): Investigated and found NOT to be a defect. See
  "Outcome note on I5" below. One characterization test was added to stop a
  future pass "fixing" it; no source change.

## Outcome note on I5

**I5 was not a defect.** Verified before fixing: the coupling is Plan 00334
Decision 7's deliberate design — the other core documents have no config key
of their own and keep canonical names in `workflow_docs`' directory precisely
so a project that moved its docs tree does not also acquire a stray `CLAUDE/`
it never asked for. It is already pinned by a passing test
(`test_nothing_is_written_to_the_default_tree`), which the proposed fix would
have regressed. The `parent == "."` concern is also a non-issue: pathlib
collapses `root / "."`, and an existing test pins it.

The genuine residual sits elsewhere and Plan 00334 already scoped it out:
`worktree_file_copy.py` and `docs_qa/checks/rules_file_shape.py` hardcode the
literal strings `CLAUDE/Worktree.md` / `CLAUDE/DocumentationStrategy.md` in
guidance TEXT, independent of any config. Making rule text
configuration-aware is its own change and is NOT taken on here.

This is the reviewer's lowest-confidence finding (75%), and it was wrong —
worth recording, because the four confident ones all held.

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
- **Phase 1-2** (receiver policy inversion): `745ff9c5`. Closed three findings
  with one change, including a fourth executor bypass (`ssh`) found by probing
  rather than review, and the word-expansion family the plan had recorded as
  unclosable.
- **Phase 3-4** (containment paths, fetchers, docs-QA pruning): see the
  archiving commit. I5 investigated and found not to be a defect.
- Four of the reviewer's five non-blocking findings held; the fifth (I5, and
  its lowest-confidence at 75%) did not survive verification.

# Category: asymmetric sibling protection

**Defence**: `scripts/qa/check_declared_invariant_pairs.py` — a checked-in
registry of site pairs that must agree, each relation asserted mechanically.

Index: [README.md](README.md). Found by
[Routine 00001](../Routine/00001-security-review-full/ROUTINE.md), across eight
independent checks rather than one.

## The class

This repository already implements the correct behaviour at another site, and
this site re-derives it, derives it shorter, or omits it.

A defect belongs here when the fix is **already written somewhere in this
codebase** and simply did not reach the site in question. The correct code is
often in the same file, sometimes twenty lines above.

The boundary is the SIBLING. A guard that is merely incomplete is not in this
class; a guard that is incomplete *while its neighbour is complete* is. That
distinction is what makes the class mechanically checkable at all — the
neighbour supplies the oracle.

Eleven prose instances and thirteen table rows came out of run 2026-001, from
eight reports whose authors never saw each other's work. Three reached for
almost identical phrasing without coordination:

- *"the escaper already exists, in this module, twenty lines above"* (D-EXEC F3)
- *"the shared fragment exists, is used by the neighbouring handler"* (D-PUB-4)
- *"a fix applied to the instance rather than to the class"* (F-DEPL-4)

That convergence is the strongest ranking signal in the entire review, and it is
why this class outranks defects with worse individual consequences.

## Why a review finds it and the test suite does not

**A test can only check a site against its own contract, and each site's own
contract is satisfied.** `pipe_blocker`'s tests assert that whitelisted
producers are allowed and expensive ones denied; `env` was whitelisted, so
allowing it was the tested behaviour. `process_probe`'s tests assert that
wrappers are unwrapped; `env` is in `_WRAPPERS`, so unwrapping it was the tested
behaviour. Both suites passed. Both were right about their own file.

Nothing in either test suite could see the other, because the defect is not in
either site — it is in the RELATION between them. A test fixture is built from
one module's imports, and that is exactly the boundary the defect hides behind.

This generalises past this class. **A defect that lives in a relation is
invisible to any check whose scope is one side of it**, which is the same
lesson [authored path resolution](AuthoredPathResolution.md) reached from the
other direction: there, both instances were missing *variables* rather than
missing tests.

## Instances

**The `env` pipe whitelist** — `strategies/pipe_blocker/common.py`,
`UNIVERSAL_WHITELIST_PATTERNS`, against `utils/process_probe.py`'s `_WRAPPERS`.

What it allowed: `env pytest tests/ | head -20` truncated pytest's output. The
pipe blocker attributed the pipe to `env` at the segment head, found it
whitelisted as a cheap filter, and allowed the truncation the handler exists to
prevent. Any expensive command could be hidden behind it.

The sibling that does it right is the rest of the repository. `_WRAPPERS`
classifies `env` as a command runner, and the evasion suite asserts that
`env git commit`, `env gh issue create`, `env pgrep -f` and `env cat <DETAIL>`
are each judged on the WRAPPED command. The pipe whitelist was the single site
holding the other reading.

Removal cost nothing: `printenv` is the non-wrapper spelling, does the same job,
cannot run another command, and remains whitelisted.

- Defence: `79421f21`, committed deliberately red over 1 declared row.
- Fix: `85b5adc4`.

**The worktree relocation verbs** —
`handlers/pre_tool_use/worktree_file_copy.py`, `_RELOCATION_VERBS`, against
`core/utils.py`'s `_WRITE_INDICATOR_RE`.

What it allowed: `install` and `dd` relocate a file and were not matched, so
the same move out of a worktree was denied when spelled `cp` and allowed when
spelled `install`. Verified by probing the handler rather than reading the
regex — three verbs denied, two allowed.

The sibling had carried both all along. The worktree verbs were an alternation
inlined at their only call site, which is the shape that has no sibling to be
checked against and drifts from one silently.

- Defence: `602c5fa3`, committed deliberately red.
- Fix: `55f374e8`.

**Judging prose as a command** — the same handler, found by hitting it: the
commit message for `602c5fa3` was DENIED, because it described this handler and
so contained a worktree path beside a relocation verb. A **call-path** instance
rather than a constant one.

What it cost: the deny renders "WHY THIS IS CATASTROPHIC" and five bullets about
destroying branch isolation, so someone writing a sentence was told they nearly
destroyed their work. A guard that cries wolf on prose is a guard people switch
off, which is how a false positive becomes a security problem.

`utils/shell_segmentation.strip_inert_spans` is this repository's existing
answer to "what command is actually being run", and `destructive_git`,
`pipe_blocker`, `merge_to_main_approval` and `daemon_location_guard` all reach
it. This handler judged the raw string. The helper existed; the site did not
reach it.

The boundary was kept rather than widened: `bash <<'EOF'` still has its body
judged, because the receiver RUNS those bytes whatever the outer shell quoted.

- Fix: `c23b1b8c`, whose own message carries the previously-denied shape and is
  therefore the regression proof.

This instance has **no registry row**. A call-path row needs a single named
helper both sites must call, and this site's fix was to route its whole scan
target through one — expressible, but not yet written. It is recorded as an
instance because it happened, not because it is covered.

**The unguarded refresh** — `remote_docs/store.py::refresh_document` against
`write_capture`, on the helper `content_guard`. The first instance found by the
**call-path** rule kind rather than by comparing two constants.

What it allowed: `write_capture` refuses to vendor content the sensitive-content
scanner rejects, because a capture writes from a CLI and bypasses the `Write`
hook that would otherwise inspect it. `refresh_document` ran the same fetch and
the same write with no scan at all.

The reasoning applies more strongly on the refresh path, which is what makes
this more than tidiness: a capture is something a human ran deliberately once,
while a refresh exists *because upstream may have changed*, and those new bytes
have had no review by anyone.

The fix added a `REFUSED` outcome rather than reusing `FAILED` — a failed fetch
is transient and retryable, a refusal means upstream is now serving something
that must not enter the repository — and placed the scan BEFORE the
unchanged-hash short-circuit, so the short-circuit cannot become a route past
the guard.

- Defence: `5b6ac98b`, committed deliberately red.
- Fix: `a6ce7bb7`.

**The forwarder interpolations** — `install/forwarder_generator.py`,
`build_relay_guard_block`, against `_escape_for_double_quotes` in the same
module. **Partially fixed, and listed that way on purpose.**

What it allowed: a checkout path carrying `$` or a backtick produced a forwarder
that expanded a variable, or ran a command substitution, every time the daemon
was down. The escaper's own docstring calls this failure "silent and remote" and
escapes an internal CONSTANT for that reason — while the paths, which are
wherever the user cloned, went in raw.

Reading the site found the worklist's one defect to be **three quoting
contexts**. Three sites are a plain double-quoted string, where the existing
escaper is exactly right, and are fixed. Two sit inside `${VAR:-default}`,
where `}` terminates the expansion and the escaper has no rule for it.

**No registry row was added**, and the reason belongs in this register rather
than only in the plan: a `reaches` row asserts the function CALLS the helper, so
applying the escaper to all five sites would have turned the row green while two
remained broken. A row satisfiable by a partial fix is worse than no row,
because it converts an open defect into a closed one on paper.

The remaining fork is an owner decision, written up with a recommendation in
[DECISION-forwarder-interpolation-contexts.md](../Plan/00412-jobs-recurring-work-and-security-review/DECISION-forwarder-interpolation-contexts.md).

Twelve further table rows are recorded in
[the consolidated worklist](../Plan/00412-jobs-recurring-work-and-security-review/subagent-reports/260915-consolidated-defence-worklist.md),
with the registry's design notes in
[DESIGN-declared-invariant-pairs.md](../Plan/00412-jobs-recurring-work-and-security-review/DESIGN-declared-invariant-pairs.md).
Each becomes an instance here as its row lands. Two of their fixes are
owner-gated, because both add a refusal in installing projects: D-PUB-3's
fail-closed on an oversized body file, and F-HYG-3's new deny in
`staged_lint_gate`.

## Rejected rows

A row is a human claim that two sites must agree. Some proposed pairs turn out
to be **correctly different**, and recording those is as much a part of the
category as recording the instances — otherwise the same pair gets re-proposed
by the next reviewer and eventually written.

**`sensitive_content` vs `staged_lint_gate` on `path_is_protected`** — proposed
by two independent checks (`D-SEC-1`, `F-HYG-3`) as "one excludes protected
paths and the other does not". Rejected after reading both.

`staged_lint_gate` skips a protected file because a lint diagnostic can quote
the offending source line verbatim, so scanning one would leak its content into
a deny message. `sensitive_content` has no such vector by construction: its deny
names the file path and a pattern name or entry index, **never the line**.

So the exclusion that is right in one is wrong in the other. Adding
`path_is_protected` to `sensitive_content` would stop it scanning staged
protected files — and a protected file staged *with a secret term in it* would
then commit silently. The row would have removed protection in the name of
consistency.

**The real defect under `F-HYG-3` points the other way**: `staged_lint_gate`
silently `continue`s past a staged protected file. A protected file reaching the
index is itself the alarming event and nothing says so. That fix is a new deny
in installing projects and is therefore owner-gated, which is how the
consolidated worklist already classified it.

The generalisable point: **two guards touching the same concept are not
obliged to agree — only guards with the same DISCLOSURE behaviour are.** The
asymmetry is a defect when one site is wrong, not whenever the sites differ,
and telling those apart is the reading a registry exists to capture.

## What the Defence does not catch

- **Only declared pairs.** This is the defining limitation and it is
  structural, not an oversight. A divergence with no row in
  `scripts/qa/declared-invariant-pairs.yaml` is invisible, and the registry
  currently holds three rows against thirteen known instances. **Read a green
  run as "every declared pair holds", never as "the class is clear."**

  The third instance above proves the point from inside: it is a real member of
  this category, found while building the Defence, and the Defence does not
  cover it.

  The generative half — proposing candidate pairs by finding a constant or
  helper consumed by one of two handlers that judge the same command — was
  measured as noisy and deliberately does not gate a build. A noisy rule gets
  switched off, and a switched-off rule protects nothing.

- **Two extractors, both shallow.** `dict_keys` reads the string keys of a
  module-level dict literal; `regex_head_names` reads the `^name\b` head of each
  literal pattern in a module-level tuple or list. A member computed at import
  time, built by a comprehension, or assembled from another module is not seen.

- **A non-literal entry is SKIPPED, not guessed at.** The pipe whitelist mixes
  plain literals with f-strings built from the shared git grammar
  (`rf"^{GIT_INVOCATION}log\b"`). Inventing a member from one would be a false
  positive; skipping it under-reports. That direction is chosen deliberately —
  the cheap error for this rule is missing a member, because crying wolf once
  costs the whole check.

- **Three relations.** `disjoint`, `superset` and `reaches` are implemented;
  `equal` and `same-normalisation` are designed and not built.

- **`reaches` proves a CALL, not an effect.** It asserts that the named helper
  is invoked somewhere in the function body. It cannot tell whether the result
  is acted on, whether the call sits behind a condition that is never true, or
  whether it runs before the write it is supposed to guard. Ordering was the
  load-bearing detail in the `content_guard` fix and no rule checked it — a
  test did.

  It also cannot see a helper reached through an alias, a partial, or a
  dispatch table, and a name-only match means a DIFFERENT function of the same
  name satisfies the row.

- **Still only declared pairs.** Rows cover `pipe_blocker`/`process_probe`,
  the worktree verbs, and the remote-docs writers.

- **A proposed pair can be WRONG, and nothing mechanical says so.** The
  `path_is_protected` pair came from two independent checks and would have
  weakened a guard had it been written (see Rejected rows). The Detector
  asserts whatever a row claims — it has no opinion on whether the claim is
  correct, so a badly-read row turns into enforced damage.

  This is the real cost of "near-zero false positives by construction": the
  construction is a human reading both sides, and the rule inherits that
  reading rather than checking it.

  `_escape_for_double_quotes` is the instructive absence. It has a recorded
  instance, a partial fix, and deliberately **no row** — because the row would
  be satisfied by the partial fix. Where a rule can be satisfied without the
  defect being gone, writing the row down is worse than leaving it out, and the
  register has to be able to say so.

- **A row must name which MEMBERS participate.** This was bought the hard way.
  The first row drafted asserted a superset between two relocation-verb
  alternations that were each missing members of the other — `rsync` on one
  side, `install`, `dd` and `tee` on the other — so a naive set comparison
  reported a violation in BOTH directions and neither was the defect. A check
  that opens with noise on its first row gets switched off rather than
  satisfied.

- **A rotted row is caught, but only structurally.** A renamed file or symbol
  raises rather than yielding an empty set, because empty is disjoint from
  everything and a rotted row would otherwise read as a row that passes.
  What is NOT caught is a row whose sites still exist and whose declared
  relation has quietly stopped being the right thing to assert; only a human
  re-reading the `reason` catches that.

- **It proves agreement, not correctness.** Two sites can agree and both be
  wrong. The registry asserts that this project's own reasoning propagates, not
  that the reasoning was sound.

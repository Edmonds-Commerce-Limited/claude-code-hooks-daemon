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

Twelve further table rows are recorded in
[the consolidated worklist](../Plan/00412-jobs-recurring-work-and-security-review/subagent-reports/260915-consolidated-defence-worklist.md),
with the registry's design notes in
[DESIGN-declared-invariant-pairs.md](../Plan/00412-jobs-recurring-work-and-security-review/DESIGN-declared-invariant-pairs.md).
Each becomes an instance here as its row lands. Two of their fixes are
owner-gated, because both add a refusal in installing projects: D-PUB-3's
fail-closed on an oversized body file, and F-HYG-3's new deny in
`staged_lint_gate`.

## What the Defence does not catch

- **Only declared pairs.** This is the defining limitation and it is
  structural, not an oversight. A divergence with no row in
  `scripts/qa/declared-invariant-pairs.yaml` is invisible, and the registry
  currently holds one row against thirteen known instances. **Read a green run
  as "every declared pair holds", never as "the class is clear."**

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

- **One relation so far.** Only `disjoint` is implemented. `superset`, `equal`
  and `same-normalisation` are designed and not built, so a row needing them
  cannot be added yet.

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

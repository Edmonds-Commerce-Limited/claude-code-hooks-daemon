# Detector design: declared invariant pairs

The Defence for the `asymmetric-sibling-protection` class — the largest in the
run 2026-001 corpus, thirteen table rows drawn from eight reports that never saw
each other.

Read with
[the consolidated worklist](subagent-reports/260915-consolidated-defence-worklist.md)'s
class 1, which is the source of the rows. This document records what changed
after three of those rows were checked against the code they name.

## The class, and why a registry

This repository already implements the correct behaviour at another site, and
this site re-derives it, derives it shorter, or omits it. The correct code is
usually visible in the same file.

The class has no syntactic signature, so no Detector can find a member by
reading one site. What it can do is assert a relation between a **declared
pair**: a checked-in table of `(site A, site B, relation)` rows, each asserted
mechanically. False positives are near zero by construction, because every row
was written by a human who had read both sides.

The cost is the blind spot, and it must be written into the category: **a
registry only covers declared pairs.** A fourteenth divergence with no row is
invisible. The generative half — proposing candidate pairs by finding a constant
or helper consumed by one of two handlers that judge the same command — is
reportable as noisy and must not gate a build.

## What checking the rows changed

Three rows were read against the real code before any Detector was written. One
did not survive contact, and the way it failed is the design input.

### The relation cannot be over a raw literal

`F-BYPS-7` declares `worktree_file_copy.py` ⊇ `core/utils.py`'s
`_WRITE_INDICATOR_RE`. Neither side is a superset of the other:

| Side                                    | Members                                                |
| --------------------------------------- | ------------------------------------------------------ |
| `worktree_file_copy.py:113`             | `cp`, `mv`, `rsync`                                    |
| `_WRITE_INDICATOR_RE` (`core/utils.py`) | `tee`, `cp`, `mv`, `install`, `dd`, plus `>` and `of=` |

`rsync` is only in the first; `install`, `dd` and `tee` only in the second. A
rule that extracted each alternation and compared the sets would report a
violation in **both** directions, and neither report would be the defect.

The defect is real but narrower than the row says: `install` and `dd` relocate a
file, and `worktree_file_copy` does not match them. `cp src/x.py ../wt-foo/src/`
is denied; `install src/x.py ../wt-foo/src/` is not.

So a row declares **which members participate**, not just two symbol names. The
participating set here is the relocation verbs — `tee` writes new content and
`>`/`of=` are operators, so none of the three belongs in the comparison. Without
that, the check is noise on its very first row, and a check that opens with
noise gets switched off rather than satisfied.

### A row can under-report the gap it names

`F-HYG-1` declares `gitignore_safety_checker.py`'s
`_REQUIRED_GITIGNORE_PATTERNS` against `utils/secret_file_matching.py`'s
resolved patterns. Confirmed, and the gap is wider than the row states.

The checker hardcodes `*.secret` and `*.secrets`. The protected list also
carries `.vault-pass*`, `*.vault-password`, `*vault_pass*`, `id_rsa` and
`id_ed25519` — five shapes the daemon refuses to READ but never asks the project
to gitignore. Guarding the read while ignoring the commit is the asymmetry.

It is wider still because `protected_paths` is project-configurable: a project
that declares its own protected glob gets no gitignore advice about it at all,
so the divergence grows with every installing project rather than staying at
five.

This row needs one named opt-out from day one — a protected glob a project
deliberately tracks, of which an `.example` template is the standing case, and
this repository had exactly that until recently.

### A row can be exactly right

`F-EXPT-1` declares the `pipe_blocker` whitelist disjoint from
`process_probe.py`'s `_WRAPPERS`. Confirmed with nothing to restate:
`strategies/pipe_blocker/common.py` whitelists `^env\b` as a cheap filter, while
`_WRAPPERS` classifies `env` as a command **runner**.

The two readings cannot both hold, and the consequence follows from the runner
one: `env pytest tests/ | head -20` is attributed to the whitelisted `env` at the
head, so the truncation the handler exists to prevent goes through.

The relation is `disjoint`, currently violated by exactly `{env}`. This is the
row to build first — it is a pure set intersection over two literals, the
violating member is a single name, and the fix is a one-line whitelist removal.

## Rule kinds

- **Constant pairs** — extract a literal alternation or tuple from each side and
  assert the declared set relation over the declared participating members.
  `superset`, `equal`, `disjoint`, `same-normalisation`.
- **Call-path pairs** — assert that a named helper reached from site A is also
  reached from site B. `_escape_for_double_quotes`, `path_is_protected`,
  `content_guard`, `_expand_home`.

## Build order

`F-EXPT-1` first, for the reasons above: it is the cheapest row to assert, its
fix is one line, and it exercises `disjoint` — a relation the original hypothesis
did not list, which surfaced only because a row was checked rather than trusted.

Two fixes in this class are owner-gated and must not be built with the Detector:
`D-PUB-3`'s fail-closed on an oversized body file, and `F-HYG-3`'s new deny in
`staged_lint_gate`. Both add a refusal in installing projects.

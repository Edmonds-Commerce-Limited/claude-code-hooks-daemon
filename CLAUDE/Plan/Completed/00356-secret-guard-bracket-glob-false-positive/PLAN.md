# Plan 00356: secret guard bracket glob false positive

**Status**: Complete
**Created**: 2026-09-08
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

`secret_file_guard` denies ordinary array-subscript expressions. A jq path
such as `.foo.v[0]` is reported as referencing the protected glob
`*.vault-password`, so any script reading the first element of a repeated
field cannot be authored, and the same token in a Bash command is denied too.
The incoming report's evidence was an accept/deny table, reproduced here
because it is what the fix is verified against. Each row was the body of a
file written with the `Write` tool; every blocked row cited `*.vault-password`:

| Token in the written content | Reported verdict |
| ---------------------------- | ---------------- |
| `.aliases.v[0]`              | BLOCKED          |
| `.foo.v[0]`                  | BLOCKED          |
| `.foo.v[z]`                  | BLOCKED          |
| `.foo.v`                     | allowed          |
| `.foo[0]`                    | allowed          |
| `.foo.x[0]`                  | allowed          |
| `.aliases["v"][0]`           | allowed          |

It is not brackets in general (`.foo[0]` passes) nor the letter `v` in general
(`.foo.v` passes) — it is a `.v` segment followed by a bracket. The whole
table is now a test class, so the report was consumed and deleted rather than
promoted: its identifiers would have needed stripping for this public
repository, and the table plus the analysis below is everything that carried
forward.

The reporter inferred, from a black-box accept/deny table, that a bracket
expression is "widened to `*`". That inference is directionally right but the
mechanism read out of the source is more specific, and the distinction decides
which fix is correct. Nothing textually rewrites `[0]` into `*`. What happens
is in `utils/secret_file_matching.py`:

1. `_has_trailing_wildcard(".foo.v[0]")` returns `True`, because a complete
   bracket expression sits at the token's right edge. That predicate means
   "this edge is open to an arbitrary suffix" — which is false for a bracket:
   `[0]` matches exactly one character from a finite set, it opens nothing.
2. `_token_literal_residue` deletes bracket expressions whole, so the residue
   is `.foo.v` — the token's asserted literal text loses the `0` entirely.
3. `_glob_token_overlaps_stem` therefore runs the forward-truncation test, and
   `_suffix_prefix_overlap_length(".foo.v", ".vault-password")` is `2` (the
   `.v` edge), meeting `_MIN_GLOB_OVERLAP_CHARS`. Since `*.vault-password`
   begins with `*`, the token is declared a plausible truncation and denied.

So the defect is the edge-openness predicate conflating "a bracket expression
is here" with "an arbitrary-length run may follow", compounded by the residue
dropping the bracket's own character. `.foo.v[z]` is the decisive case the
reporter identified: it can only ever denote `.foo.vz`, which no expansion can
turn into a `*.vault-password` file, and it is denied anyway.

This is the sixth incremental false positive in this matcher, which is
evidence for the re-derivation
[Plan 00311](../00311-v3590-release-review-followups/PLAN.md) Task 1.2
proposes. This plan is deliberately NOT that re-derivation: it fixes a
confirmed live defect without betting the guard on a rewrite. It adds no
seventh special case either — see the Approach note below.

## Approach: why bracket EXPANSION, and what was rejected

The report offered two fixes. Both were live options; the first is taken.

**Chosen — expand finite bracket expressions (report fix 1).** A non-negated
bracket expression denotes a finite character set, so a token containing only
such expressions denotes a finite set of concrete spellings. Expanding
`.foo.v[0]` to `.foo.v0` before any glob analysis runs makes the existing
machinery correct without touching it: the expansion carries no `*`/`?`, so it
is not glob-shaped, so the truncation heuristics never run on it. This is a
refinement of the INPUT to the four existing gates rather than a fifth gate,
which is why it does not aggravate Plan 00311 Task 1.2. It also leaves
`_has_leading_wildcard`/`_has_trailing_wildcard`/`_is_glob_shaped` untouched —
required, because `test_posix_literal_bracket_first_class_is_glob_shaped`
asserts `_has_trailing_wildcard("x[]]") is True` directly, and that contract
must not be weakened.

**Rejected — gate on path shape before glob-matching (report fix 2).** The
report proposed requiring a token to contain a separator (`/`, `~`, `$HOME`)
or to match a protected glob's literal stem before the wildcard machinery
runs. This would kill the whole jq/JSONPath/subscript class in one stroke, but
it fails open on a case the current corpus already protects:
`test_trailing_wildcard_truncation_of_protected_basename_is_matched` asserts
that `cat dummy.vault-p*` is denied. That token has no separator, and its
literal stem is `dummy.vault-p`, which is not a prefix of any protected stem —
the arbitrary `dummy` prefix belongs to the pattern's own leading `*`. A
shape gate would let a genuine truncation of a real protected filename
through. `cat .vault-p*` (documented in the handler's own guidance as caught)
has no separator either. Failing open is the one outcome this guard cannot
accept, so the shape gate is rejected.

## Goals

- A token whose bracket expressions are all finite and non-negated is matched
  as the finite set of concrete spellings it denotes, not as an open wildcard.
- Every existing accept/deny contract in
  `tests/unit/utils/test_secret_file_matching.py` continues to hold unchanged.
- A negated bracket (`[!...]`, `[^...]`) and an over-cap expansion stay
  conservative — treated exactly as today.
- The deny message names the token it matched on, not only the protected glob.
- The printed remediation points somewhere an agent can actually follow.

## Non-Goals

- **The from-scratch re-derivation of the matching heuristics** proposed in
  Plan 00311 Task 1.2. That task stays open and this plan is further evidence
  for it; conflating the two would gate a confirmed bug fix on a rewrite.
- **Path-shape gating before glob matching** — rejected above, with reason.
- **Exempting the daemon's own emitted globs from the Bash mention check.**
  The report floated this. It is a real loosening of a security guard and is
  not undertaken here; the remediation-pointer fix removes the need for it.
- Changing the shipped default protected globs, or the deliberate breadth of
  `*.secret*`.

## Tasks

### Phase 1: Bracket expansion

- [x] ✅ **Task 1.1**: RED — add failing cases to
  `tests/unit/utils/test_secret_file_matching.py` covering the report's table:
  `.foo.v[0]`, `.foo.v[z]`, `.aliases.v[0]` must be allowed; `.foo.v`,
  `.foo[0]`, `.foo.x[0]`, `.aliases["v"][0]` must stay allowed. Add the
  security counter-cases in the same commit: `cat .vault-p*`,
  `find . -name "*secret*"` and a bracket expression that genuinely names a
  protected file (`[Vv]ault_pass`) must all stay DENIED.
- [x] ✅ **Task 1.2**: GREEN — add `_bracket_expression_members` and
  `_expand_bracket_expressions` to
  `src/claude_code_hooks_daemon/utils/secret_file_matching.py`, and consume
  them in `find_protected_mention`. Negated and over-cap expressions return
  the token unchanged. The unexpanded spelling stays in the LITERAL match
  check, because a shell passes an unmatched glob through verbatim and a file
  literally named `x[0].secret` is reachable under that exact name.

### Phase 2: Diagnosability

- [x] ✅ **Task 2.1**: report fix 3 — surface the matched TOKEN in the deny
  message. Add a `find_protected_mention_detail` returning `(pattern, token)`
  and have `find_protected_mention` delegate to it, so the four existing call
  sites keep their signature. The token is content the agent itself just
  wrote; it is never file content, so echoing it discloses nothing.
- [x] ✅ **Task 2.2**: point the remediation at
  `bin/hooks-daemon explain-handler secret_file_guard`. The report's claim
  that inspecting the config is itself blocked did NOT reproduce — grepping
  `.claude/hooks-daemon.yaml` for the handler NAME is allowed. The real
  problem is narrower and still worth fixing: repeating the GLOB the message
  just printed is denied, and a project running on shipped defaults has no
  `protected_paths` in its config at all, so the config file cannot answer the
  question the message sends the reader there to ask. `explain-handler` prints
  the effective list.

## Follow-up found while working, deliberately NOT fixed here

- [x] ✅ Shipped as Plan 00357 at `ce95acae`, exactly as described below.
  **`_expand_glob_token` crashes on a `***` token, failing a security
  handler OPEN.** `find_protected_mention_strict` → `_expand_glob_token` does
  `try: matches = base.glob(pattern_str) except (OSError, ValueError): continue`
  and then iterates `matches` OUTSIDE the `try`. `Path.glob` is a generator
  function, so pattern validation is deferred to the first `next()` — the
  `ValueError("Invalid pattern: '**' can only be an entire path component")`
  is raised on the `for` line, which nothing catches. Any Bash command
  containing a token like `***` therefore raises out of
  `quarantine_artefact_read_guard`, so that guard does not run for that
  command. Reproduced live: a probe command of this plan's own triggered
  `Handler exception: ValueError` from the daemon, and the same call
  reproduces standalone against a synthetic pattern.

  Left as a follow-up because it is a different function, a different
  handler's contract, and needs its own RED test — not because it is minor.
  The fix is to move the iteration inside the `try` (or materialise the
  generator there); the exception list is already correct.

## Success Criteria

- [x] The report's reproduction table is reproduced as tests and passes in
  full, in both directions.
- [x] `cat .vault-p*`, `find . -name "*secret*"` and `[Vv]ault_pass` remain
  denied — the fix does not over-correct into a fail-open.
- [x] `./scripts/qa/llm_qa.py all` is green (the run that closed Plans 00357
  and 00359 covered this tree).
- [x] Plan 00311 Task 1.2 carries a cross-reference recording this as the
  predicted next incident.
- [x] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/03-bracket-expression-no-longer-read-as-wildcard.md`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00356-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Fixed on the agent branch and merged to main by the worktree sub-agent; the
  follow-up it found shipped as Plan 00357 at `ce95acae`.

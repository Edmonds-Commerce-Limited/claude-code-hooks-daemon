# Category: fail-open when the check cannot run

**Defence**: `scripts/qa/check_fail_open_inventory.py` — a fail-open boundary
in the enforcement path with no declared row in
`scripts/qa/fail-open-boundaries.yaml`

## The class

The guarded action proceeds because the guard could not reach a verdict.

Not "the guard decided to allow" — the guard never decided. A timeout expired,
an exception was swallowed, a size bound was hit, a dependency failed to
import, a config failed to validate. The tool call goes through and the only
record is, in the worst instances, a single line on a stream nothing collects.

What makes it a security class rather than a robustness one is the second
half: **in several instances the party the guard constrains can induce the
condition.** The daemon's work on a PreToolUse event is a function of input the
caller chooses — a large staged commit, an ESLint spawn, a tree-wide QA gate.
Make the guard slow, and the guard is skipped.

Deciding a new case:

- **Did a verdict exist?** If the guard reached one and the failure is in
  recording it (`_record_verdicts`, `log_error_to_file`), that is an audit
  loss, not this class. The row says so and says why.
- **Does the handler re-raise?** A boundary that propagates is not fail-open;
  the caller still gets the failure. This is the predicate the scanner uses to
  keep the candidate list to a size a person will fill in honestly.
- **Is the suppression the answer?** `kill -0 pid 2>/dev/null` hides a
  diagnostic whose absence IS the function's return value. Suppressing a
  message the script has already branched on discards nothing.

## Why a review finds it and the test suite does not

Uniquely in this corpus, the test suite does not merely miss this class — it
**encodes** it. `test_timeout_fail_open`,
`test_missing_body_file_is_allowed`, `test_stdin_body_file_is_allowed` and
`test_a_body_file_that_cannot_be_read_is_skipped_and_logged` all pass, all
assert the allow, and all read to a reviewer as deliberate coverage of the
branch.

Coverage of a fail-open is not a defence against one. A test that pins the
behaviour makes the branch look considered, which is exactly the impression
that stops the next reader asking whether the caller can reach it on purpose.

## Why an inventory rather than a code rule

The discriminator is a property of the **surface**, not of the code.
`sensitive_content`'s staged-diff stand-down and its `gh`-body stand-down are
the same shape — a size bound whose value feeds a haystack rather than a deny —
and one is defensible while the other is not, because a commit can be amended
before it is pushed and a published comment cannot be recalled. No regex sees
that difference, and a general `except`-scan over the tree is noisy enough that
it would be switched off rather than satisfied.

So the scanner enumerates candidates mechanically over five named surfaces, and
the inventory carries the judgement: one row per candidate, written by someone
who read the site. Every `fail-open` row must name what induces the boundary,
whether the inducing input is caller-controlled, and **what trace it leaves
in-band**. The third column is the one that pays, and the sweep proved it: it
is the only column that came back empty.

## Instances

The sweep found **33 candidates in scope; 20 are fail-open**, across
`core/chain.py`, `core/front_controller.py`, `daemon/controller.py`,
`relay/hooks_relay.rs` and `init.sh`. The full table is the inventory file.
Three are worth naming here:

- **`front_controller.run`, `except json.JSONDecodeError`** — prints `{}`,
  exits 0. **No stderr line, no log entry, nothing in-band.** Every guard for
  that event is inert and nothing anywhere records that it happened. The
  emptiest third column in the inventory, and the only one whose remedy —
  leaving a trace — needs no behaviour change at all.
- **`relay/hooks_relay.rs::mid_exchange_fail`** — F-BYPS-5, the 30,000 ms
  forwarder budget. One stderr line, then `{}` and exit 0, which Claude Code
  cannot tell from a clean allow. Caller-controlled and measurably reachable:
  a commit staging 16 MiB of added text judges in 17.8 s, 59.3% of the budget,
  and the cost grows superlinearly in bytes.
- **`core/chain.py::execute`** — the per-handler `except`, recorded because a
  correct boundary belongs on the inventory too. Blast radius is one handler,
  the exception reaches the caller in the result's context, and strict mode
  denies instead. Declaring it is what makes the other nineteen rows mean
  something.

The Defence landed RED at `4d0fcead` with an empty inventory and 33 undeclared
boundaries; the sweep that filled it is the commit that follows.

**No instance is fixed.** Converting any of these to fail-closed changes
behaviour in every installing project — a slow guard would begin blocking, a
bad config would begin refusing every tool call — so the fix is owner-gated.
The inventory exists so that the decision is made against a list rather than
against an impression.

## What the Defence does not catch

- **Anything outside the five surfaces.** D-PUB-3 (`sensitive_content.py`'s
  `gh`-body bound) and D-DEP-08 (`jsonschema` imported under
  `try/except ImportError`, with `strict_mode` defaulting to `False`) are
  instances of this class and are **not** in scope, because the scope is
  F-BYPS's enforcement path. Widening it is how the inventory grows; narrowing
  it is how this Defence stops working.
- **The judgement itself.** The scanner checks that a row EXISTS and is
  complete. It cannot check that `verdict: not-fail-open` is correct or that
  `trace:` is honest. A wrong row passes. What the Defence buys is that the
  wrong row is *written down*, attributable and reviewable, instead of being
  an absence.
- **Size bounds and timeouts that are not spelled as an `except`.** The
  Python half keys on exception handlers; a stand-down expressed as
  `if len(x) > LIMIT: return ""` is invisible to it. The Rust half keys on
  `-> !`, the shell half on four suppression spellings.
- **Shell noise in the other direction.** All eleven `init.sh` candidates
  resolved to `not-fail-open`: `2>/dev/null` in a probe whose exit status is
  the answer is not error suppression. That is a finding worth having, but it
  means the shell rule's precision is low and a future maintainer will be
  tempted to drop it. The rows are the argument for keeping it.

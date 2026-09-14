# N3 — why one dotted module path was named and another was not

Supporting evidence for [N3](PLAN.md), which was held open rather than guessed
at. The short answer: the two tokens were never the same shape.

## The mechanism

`find_protected_mention_detail`'s exemption is POSITIONAL and keyed on an
IMPORT STATEMENT — it deletes the dotted module path an `import` /
`from … import` occupies, so a module path is exempt exactly where it is
imported and nowhere else. `claude_code_hooks_daemon.utils.secret_redaction`
sat in that position and still does, at `issue_report/block_words.py:42`. The
reported token did not.

## Verified with a synthetic pattern

The real glob is itself matched by the real glob, so a probe naming it cannot
be written at all. The mechanism is pattern-agnostic, so it was exercised with
`*.probeword*` and invented module names:

| input                                  | named token                        |
| -------------------------------------- | ---------------------------------- |
| the path inside a real `from … import` | (no match — exempt)                |
| the same path in a comment             | `pkg.issue_report.probeword_terms` |
| both present, import first             | the PROSE one                      |
| both present, prose first              | the PROSE one                      |
| two prose mentions, neither imported   | the FIRST only                     |

Order does not decide it; position does.

## The secondary suspicion: true, and not the explanation

The scan does stop at the first match — the function's docstring says "for the
FIRST protected mention", and every branch of `_matched_pattern_and_route`
returns on the first hit. The last row above demonstrates it: two prose
mentions, one named.

So "Matched on this token from your input" is indeed non-exhaustive. Worth
knowing, and defensible: scanning on after a hit purely to lengthen a message
buys nothing, and the message's job is to save a bisection, which naming one
real token already does.

## Why leaving it open beat guessing

First-match-wins was plausible AND true, and it was still the wrong answer to
the question asked. Writing it down while it was merely plausible would have
left the entry reading as settled while pointing at the wrong cause — and the
positional import exemption, which is the thing an author actually needs to
know, would never have been found.

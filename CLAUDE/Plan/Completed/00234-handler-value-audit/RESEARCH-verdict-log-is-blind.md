# Evidence note: the instrument built to answer this audit's question is blind

**Gathered by**: main thread (requires running the live CLI against the live log;
no cohort agent could obtain this)
**Date**: 2026-08-13

## Summary

Plan 00209 built the verdict log for exactly the question this audit asks. Its
own config docstring says so, verbatim:

> the daemon makes hundreds of handler decisions per session and persisted none
> of them, so **"which handlers earn their keep?"** and "what is the real
> false-positive rate per handler?" were answerable only by anecdote.
> — `src/claude_code_hooks_daemon/config/models.py:795`

It cannot answer that question, and the reason is measurable.

## The measurement

| Quantity                                     | Value                                             |
| -------------------------------------------- | ------------------------------------------------- |
| `verdicts.jsonl` size                        | 10,485,530 B (at its 10 MiB cap, `models.py:827`) |
| Records retained                             | 44,180                                            |
| Oldest retained record                       | 2026-08-13T14:28:04Z                              |
| Newest retained record                       | 2026-08-13T15:33:07Z                              |
| **Retained window**                          | **65 minutes, one session**                       |
| Records from `status-*` handlers             | 43,929 (**99.43%**)                               |
| Records from every other handler combined    | 251                                               |
| Distinct verdicts ever emitted by `status-*` | 1 (`allow`, 100%)                                 |

Thirteen status-line handlers each fired ~3,383 times in 65 minutes — roughly
one render per 1.15 s, which is simply the status line's refresh rate. Every one
of those records is `allow`. A status handler is a **renderer, not a decider**:
it has no other verdict it could return, so its records carry zero bits of
information about whether it earns its keep.

## Consequence

The audit trail is a 10 MiB rolling sample. At 99.43% zero-information content,
it retains **65 minutes** of history. Suppressing `status-*` records would leave
~251 records per 65 min at ~237 B/record ≈ 59.5 KB/hour, so the same 10 MiB cap
would retain **≈ 8 days** — a ~176x longer observability window, at no cost to
the question being asked.

This is the vacuous-guard shape from Plans 00196/00230, one level up: the
instrument is registered, running, and reporting confident-looking totals
("Total recorded decisions: 44168") that describe an hour of one session. The
report does carry a caveat about the retained window, but nothing tells the
reader that the window is 65 minutes rather than months.

## ⚠️ Anti-inference warning for the judge — read before using the report

`hooks-daemon verdicts` prints a **"Never-fired handlers (59)"** list. **It is
not evidence that those handlers are pointless, and must not be used that way.**
It means only "did not fire in the last 65 minutes."

The list includes `prevent-destructive-git`, `block-security-antipatterns`,
`block-sensitive-content`, `root-recursion-guard` and `lock-file-edit-blocker` —
handlers whose entire value is that they fire rarely and catastrophically. Their
absence from an hour of logs is what success looks like. Any reasoning of the
form "the verdict log shows X never fires, therefore delete X" is invalid on
this data, for all 59 entries.

What the list CAN legitimately support: it is a starting point for asking
whether a handler is *structurally* incapable of firing (vacuity), which must
then be established from the code and its tests — the cohort dossiers' job.

## What the fire counts DO support

The 251 non-status records are a real, if small, sample of one session's
behavioural handlers. Two observations survive:

- **Deny is rare**: 14 denies across 44,168 records. The daemon is overwhelmingly
  an advice machine, not a blocking one. Whatever value it delivers is mostly
  delivered as injected context, which is precisely the cost the cohort
  audits were asked to weigh.
- **`bash-error-detector` fired 110 times in 65 minutes** — by a wide margin the
  most active non-status handler, ~1.7 fires/minute. Whether that volume is
  earning its keep is a question for cohort D, but the frequency is a fact.

## Recommended remedy (for the plan, not for this note to decide)

Exclude `status-*` handlers from verdict recording, or record them under a
separate cap. The status line's health is already observable directly — a broken
segment is visible to the human on every render, which is the whole point of a
status line. Logging 43,929 `allow` records per hour to prove it rendered is the
same category of act as archiving a file to protect it from a deletion that
never happens.

Doing this before the removals decided by this audit would also give the project
a working instrument to *verify* those removals against — currently there is no
way to observe a handler's real-world firing rate over any meaningful period.

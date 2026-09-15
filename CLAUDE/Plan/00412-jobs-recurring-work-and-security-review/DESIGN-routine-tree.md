# Design notes: the Routine tree

Durable reasoning behind Plan 00412's Phase 2, extracted from `PLAN.md` so that
document stays lean enough to be read in full each session. These decisions are
settled and shipped; this is the record of *why*, which a task checkbox cannot
carry.

The `D<n>` references are the routine-concept decisions: coverage is an
INTERVAL never a pointer (D2); a missed run WIDENS the next interval (D5);
"never ran" is deliberately NOT a run state (D6); a cron PROMPTS a run, the
record PROVES one (D7); `session_start` is a first-class trigger (D9); five run
states (D10); period PLUS grace (D11); anchor runs to release TAGS (D12).

## The ledger: one row per EVENT, not per run

The shape is **forced, not chosen**. Two independent constraints land on it:

D10's `failed` means "started and did not finish" — and nothing can *write*
that row, because whatever would have written it died with the run. So `failed`
has to be DERIVED from a start with no terminal event, and deriving it needs
two rows.

Separately, row-per-run cannot be append-only: finishing a run would edit a row
already on disk.

Both validity guards sit in the constructor. A terminal outcome with no
interval silently breaks gap detection; a `skipped` with no reason is exactly
the unexplained absence the state exists to replace. `skipped` is exempt from
the interval rule because it genuinely covered nothing.

The on-disk form is a markdown table, because this is a tree humans read. The
parser therefore treats cell padding as presentation — this project's own
`markdown_table_formatter` will re-align a ledger the moment anyone opens it.

### The gap it exposed in D10's vocabulary

There is no IN-PROGRESS state, so a run happening *right now* derives to
`failed`. That is literally true and genuinely indistinguishable in the record,
which is the reason the state is derived at all.

The listing renders it `unfinished` rather than accusing a healthy run of
having died. Separating the two for real needs D11's "period plus grace", so it
was recorded for Task 2.4 rather than settled inside a display label — a label
that papers over a modelling gap is how the gap survives.

### Split into three modules

`routines/ledger.py`, `routines/resolver.py` and the verb itself, so the part
that can be wrong is testable without argparse. `cli.py` is already ~9,000
lines and the last collector that grew inside it had to be extracted; this one
starts outside.

## The QA checks

Five, not the four originally listed. `routine-not-configured` was added
because every other check consults `Status` and `Trigger`, so an unrecognised
value silently removes a routine from all of them. **A check a typo can switch
off is worse than no check, because it still looks like one.**

**Grace is not optional and its default is not zero** (D11). An omitted `Grace`
takes a fifth of the period, floor one day; a declared `0` is honoured. Only an
*omission* takes a default. The fifth is a chosen value, which is precisely why
it is overridable.

**Only a run that FINISHED counts as coverage.** Otherwise a start would reset
the overdue clock, and the obligation would read as met because somebody began.

`OVERLAP` is not reported: wasteful, never dangerous, and it would bury the
finding that matters. Retired routines are skipped by overdue and never-run —
reporting one for ever trains its reader to skim the section, which costs more
than the report is worth.

## A defect in the ledger, surfaced by its own consumer

Building the checks found a bug in Task 2.3's ledger: a hand-edited row that
could not become a `RunEvent` made `read_events` **raise**, so a sweep over a
corrupted ledger would have reported nothing at all — the worst possible answer
from a check whose job is detecting absence.

Fixed before the work that found it. Reading now skips and logs, and
`malformed_rows()` reports. Shipped as a **pair**, deliberately: skipping alone
would have traded a crash for a silent omission, which is the same defect
wearing better clothes.

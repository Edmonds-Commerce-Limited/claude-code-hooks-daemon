# Plan {{PLAN_NUMBER}} — Journal {{DATE}}

_Scaffolded by `mkplan.bash`; timestamps in this file are UTC._

> **Append-only activity log** for plan {{PLAN_NUMBER}}. One file per entry,
> in a folder per day (`JOURNAL/YYYY-MM-DD/HHMMSSZ-<category>-<hex>.md`); older
> plans also hold legacy day-files (`{{PLAN_NUMBER}}-Journal-YY-MM-DD.md`). `PLAN.md` tracks the plan (what/why,
> current state, tasks); this journal tracks what actually *happened* —
> findings, decisions, dead-ends, hand-off state — the linear lifecycle a plan
> document structurally cannot carry.
>
> **Entry grammar** — add new entries ONLY with
> `mkplan.bash --journal <plan-number> <category> <body-file>` (it stamps the
> real UTC time and writes a new file; a hand-written entry is denied); NEVER
> edit an existing journal file (corrections are new entries):
>
> ```
> ## HH:MM · category · REF   — optional short title
> ```
>
> - `HH:MM` UTC 24h (the date is the folder name, also UTC) and equal to the
>   time in the entry file's name. A legacy day-file with no sentinel line
>   above predates this system — its times are local, zone unrecorded (legacy;
>   never rewritten).
> - `category` ∈ `action` | `finding` | `decision` | `thought` | `blocker` | `handoff` | `correction`
> - `REF` = optional task/phase ref (`T1.2`, `P1`) or `—`.
> - A `correction` corrects an earlier entry without touching it. Its `REF`
>   (`--ref`, required) names that entry: `HH:MM` for today, or
>   `YY-MM-DD/HH:MM` for an earlier day. An entry a correction names no longer
>   counts for time order, so a future-dated stamp can be corrected at the
>   honest time.
> - Bodies may embed fenced logs/diffs/snippets — no size limit — with a
>   one-line takeaway above the fence.
> - End a working session with a `handoff` entry so the next agent's entry
>   point is the newest entry file.

## {{TIME}} · action · — — plan scaffolded

Plan {{PLAN_NUMBER}} created via `mkplan.bash`; `JOURNAL/` initialised. Next:
fill in `PLAN.md`, then log progress with `mkplan.bash --journal` as it happens.

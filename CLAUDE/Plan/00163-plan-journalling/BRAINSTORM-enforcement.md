# Plan Journaling — Daemon Enforcement & Handler Design (brainstorm)

**Angle**: enforcement mechanism only. Data model / entry-format / naming semantics are a
sibling agent's remit; here I reuse the existing plan-QA machinery and say WHERE each journaling
touchpoint lives, WHAT blocks vs advises, and HOW append-only is detected.

**Core stance**: journaling is a *habit to encourage*, not work to gate. Every journaling check
ships **advise-first** and ratchets to block only after a clean dogfood period — exactly the
rollout the existing `commit_gate_mode: warn` default already models (`config/models.py:424`).

---

## 0. How the existing machine works (so we bolt on, not rebuild)

- Checks are pure `CheckContext -> list[Finding]` functions registered as a `CheckSpec`
  (`plan_qa/types.py`: `Stage{EDIT,COMMIT,SWEEP}`, `Level{BLOCK,ADVISE}`, `Finding(check_id, level, message, remediation, path)`). Catalogue assembled in `plan_qa/checks/__init__.py::all_checks()`.
- Three surfaces call `run_stage(stage, ctx)` and render:
  - `plan_qa_edit` (PreToolUse, `handlers/pre_tool_use/plan_qa_edit.py`) — HOT-PATH, single-file,
    reconstructs would-be content via `_would_be_content()` (Write=payload; Edit=apply old→new to
    current disk). **Only matches `PLAN.md`** today (`Path(file_path).name != PLAN_DOC_FILENAME`).
  - `plan_qa_commit_gate` (PreToolUse on `git commit`, staged tree + `GitFacts`).
  - `plan_qa_sweep` (SessionStart, whole tree + `GitFacts`, advise-only).
- `CheckContext` (`types.py`) already carries policy knobs mirrored from `PlanWorkflowQaConfig`
  (`config/models.py:381`) as plain values → package stays daemon-decoupled. **It has no
  "prior content" slot** — the one addition append-only needs (below).
- Context builders (`plan_qa/context.py`): `edit_context` (cheap), `staged_context`,
  `sweep_context`. `QaPolicy` Protocol duck-types the config.
- `GitFacts` (`plan_qa/gitfacts.py`): `last_commit_date(path)`, `staged_paths_under(prefix)`,
  `staged_file_text`, `head_file_text`, `staged_changes` (rename-aware).
- `PlanFolder`/`PlanTree` (`plan_qa/model.py:305`): folder carries `location` (ROOT / COMPLETED /
  CANCELLED / OTHER), `doc`, `has_plan_md`. **No journal awareness** → the one model extension needed.
- `mkplan.bash` already renders a project-managed `_TEMPLATE_.md` with pure-bash placeholder subs
  and is the SOLE counter writer — the natural scaffolder for a `JOURNAL/` + day-1 file.
- `level_for_plan()` (`checks/common.py:64`) is the grandfather ratchet: BLOCK new material,
  ADVISE plans in `legacy_plan_allowlist`.

---

## 1. What to enforce vs advise (advise-first everywhere)

| Touchpoint                                               | Behaviour                                  | Why                                                           |
| -------------------------------------------------------- | ------------------------------------------ | ------------------------------------------------------------- |
| `mkplan.bash` creates `JOURNAL/` + day-1 file            | **scaffold, not a check**                  | zero-friction good default; nothing to block                  |
| In-Progress plan has no `JOURNAL/` folder                | SWEEP **advise** (gated, see §grandfather) | nudge; never block work                                       |
| In-Progress plan's newest day-file is stale              | SWEEP **advise**                           | "log your progress" nudge                                     |
| Journal file basename ≠ `NNNNN-Journal-YY-MM-DD.md`      | EDIT **advise → block(ratchet)**           | naming is cheap to get right; safe to harden later            |
| Edit rewrites earlier journal lines / Write shrinks file | EDIT **advise** (stays advise)             | correcting a same-day typo is legit; blocking is user-hostile |
| Commit changes PLAN.md tasks but stages no journal entry | COMMIT **advise** (deferred slice)         | couples journaling to progress without blocking commits       |
| Terminal status flip without a closing journal entry     | COMMIT/EDIT **advise**                     | encourages a wrap-up note; block would stall completion       |

Rule of thumb: **only naming may ever escalate to block.** Presence/freshness/append-only are
forever advisory — they are habit nudges, and a false-block on someone's log is worse than a
missed nudge. Master switch `journal.mode: advise|block|off`, default `advise` (never block on first
ship), plus the global `plan_workflow.qa.enabled` already gating all surfaces.

## 2. Which surface hosts each check

- **EDIT (`plan_qa_edit`)** — extend its `matches()` to ALSO fire for files under
  `.../JOURNAL/` (not just `PLAN.md`). Reuses `_would_be_content()` verbatim for append-only.
  Add checks: `journal-dayfile-naming`, `journal-append-only`. These are single-file, hot-path safe.
  - Refactor note: rename the handler's `PLAN.md`-only filter into a "plan-artifact under plan dir"
    filter (PLAN.md **or** `JOURNAL/*.md`), then let each check self-select via `edit_target`-style
    resolution. Keep it ONE handler — a second PreToolUse Write/Edit handler duplicates the
    would-be-content reconstruction, which is the fiddly part.
- **COMMIT (`plan_qa_commit_gate`)** — `journal-entry-with-progress` and
  `journal-completion-entry` (deferred slice). Uses `staged_paths_under(f"{plan_dir}/NNNNN-.../JOURNAL/")`
  to see whether the same commit staged a journal file. Naturally rename/mv-aware for archive moves.
- **SWEEP (`plan_qa_sweep`)** — `journal-folder-present`, `journal-freshness`. Whole-tree, advise-only,
  already the right cost profile.
- **No new handler needed.** All five checks map onto the three existing stages. (A dedicated
  handler would only be justified if journaling needed a new *event* — it does not.)

## 3. Append-only detection rule

Add ONE slot to `CheckContext`: `file_content_before: str | None` (the on-disk content before the
edit). The edit handler already reads `current = file_path.read_text()` inside `_would_be_content`
— thread that value into the context so the check is pure.

Detection (`journal-append-only`, EDIT, ADVISE):

```
before = ctx.file_content_before   # None when file is new → APPEND-OK (creation)
after  = ctx.file_content          # would-be content
if before is None:                 return []          # new day-file, fine
if after.startswith(before):       return []          # pure append (prefix preserved) → OK
if len(after) < len(before):       warn "journal file shrank (truncation/rewrite)"
else:                              warn "edit rewrites earlier journal history, not an append"
```

- **Prefix test is the whole trick**: an append leaves all prior bytes untouched, so
  `after.startswith(before)` iff nothing earlier was rewritten. Works for both Write (full payload)
  and Edit (reconstructed payload) with no per-tool special-casing.
- **False-positive sources & handling**:
  - Trailing-newline normalisation → compare on `rstrip("\n")` of both sides before the prefix test.
  - `markdown_table_formatter` (PostToolUse, priority 26) rewrites `.md` after every Write/Edit,
    re-wrapping tables/lists → it can mutate *earlier* lines, breaking the next append's prefix
    invariant. **Mitigation: exempt `JOURNAL/*.md` from `markdown_table_formatter`** (its own
    exclude list) so journals stay byte-stable and append-only stays sound. (Open question — the
    formatter is non-terminal and helpful elsewhere.)
  - Same-day typo correction is a legitimate non-append → this is exactly why the check stays
    ADVISE, not BLOCK. No hard escape hatch required.
- **Escape-hatch shape** (if ever ratcheted to block): tool-call edits can't carry a bash
  `MUST_…BECAUSE=` env var, so the in-band signal would be a sentinel in the new content, e.g. a
  line `<!-- JOURNAL-REWRITE: reason -->`, mirroring the repo's declared-intent convention. Prefer
  NOT to block at all and avoid needing this.

## 4. New checks to add to the catalogue

All registered in `checks/__init__.py::all_checks()`, one module each under `plan_qa/checks/`.

| check_id                      | stage       | nominal level         | remediation string (sketch)                                                                                                                         |
| ----------------------------- | ----------- | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `journal-dayfile-naming`      | EDIT        | ADVISE→BLOCK(ratchet) | "Name journal files `NNNNN-Journal-YY-MM-DD.md` where NNNNN matches the enclosing plan and the date is today; rename `<got>`."                      |
| `journal-append-only`         | EDIT        | ADVISE                | "Append a new dated section to the end of the day-file; don't rewrite earlier entries. To correct today's own entry, edit only its trailing lines." |
| `journal-folder-present`      | SWEEP       | ADVISE                | "Plan `NNNNN` is In Progress but has no `JOURNAL/`. Create `JOURNAL/NNNNN-Journal-<today>.md` and log progress."                                    |
| `journal-freshness`           | SWEEP       | ADVISE                | "Plan `NNNNN` (In Progress) has no journal entry in N days. Add `JOURNAL/NNNNN-Journal-<today>.md`."                                                |
| `journal-entry-with-progress` | COMMIT      | ADVISE (deferred)     | "This commit changes plan `NNNNN` tasks but stages no `JOURNAL/` entry — add one to the same commit."                                               |
| `journal-completion-entry`    | COMMIT/EDIT | ADVISE (deferred)     | "Flipping plan `NNNNN` to <terminal> — add a closing journal entry summarising outcome before archiving."                                           |

Notes:

- `journal-moves-with-plan` is **not needed as a separate check**: `JOURNAL/` lives *inside* the
  plan folder, so `git mv NNNNN-x Completed/NNNNN-x` moves it automatically and `terminal-state-atomic`
  already asserts the folder move. Optionally fold a "JOURNAL/ present inside the moved folder"
  assertion into the existing archive checks rather than a new id.
- `journal-freshness`/`-folder-present` should read the **newest day-file name on disk** (dates are
  in the filename) rather than `GitFacts.last_commit_date` — journals are often uncommitted, so git
  dates would under-report freshness. Requires the model extension below.

**Model extension**: give `PlanFolder` (or a lazily-computed helper) `has_journal: bool` and
`latest_journal_date: date | None`, parsed in `_load_plan_folder` by scanning `folder/JOURNAL/` for
`NNNNN-Journal-YY-MM-DD.md` names. Keep it cheap (name parse, no file reads).

## 5. mkplan.bash + config

**Scaffolder** (`mkplan.bash`): after creating `$target` and `PLAN.md`, when journaling is enabled:

```
mkdir "$target/JOURNAL"
today_short="$(date +%y-%m-%d)"         # YY-MM-DD to match the naming check
journal_file="$target/JOURNAL/$padded-Journal-$today_short.md"
# render project-managed _JOURNAL_TEMPLATE_.md if present (mirror _TEMPLATE_.md flow),
# else a built-in skeleton header (plan number, date, "## <HH:MM> — Scaffolded").
```

Mirror the existing `_TEMPLATE_.md` pattern: seed `_JOURNAL_TEMPLATE_.md` on deploy, never overwrite,
pure-bash placeholder subs (`{{PLAN_NUMBER}}`, `{{DATE}}`, `{{OWNER}}`). Whether mkplan writes the
folder should itself be togglable so a client that doesn't want journaling gets clean plans — read a
marker (e.g. presence of `_JOURNAL_TEMPLATE_.md`, or a `MKPLAN_JOURNAL=1` env the daemon deploy sets).

**Config** — new nested block under `PlanWorkflowQaConfig` (`config/models.py`), so all knobs live in
`plan_workflow.qa.journal.*` and clients tune without touching daemon code:

```yaml
plan_workflow:
  qa:
    journal:
      enabled: true
      mode: advise            # advise | block | off  (naming is the only ratchet candidate)
      dir_name: JOURNAL
      freshness_days: 3       # separate from staleness_days (30) — journals nag sooner
      enforce_on_completion: false
      grandfather_before: 0   # plan numbers < N never nagged for missing JOURNAL/ (see §grandfather)
```

Thread these into `CheckContext` (plain values) via the `QaPolicy` Protocol exactly like the
existing knobs; zero rule logic in handlers.

**Grandfather / no-nag-spam**: this repo has ~160 journal-less plans. `journal-folder-present` must
NOT fire on all of them. Options: (a) `grandfather_before` plan-number threshold (simplest —
journaling starts at the plan that introduces it); (b) reuse `legacy_plan_allowlist`; (c) only nag
plans that *already have* a `JOURNAL/` (i.e. freshness yes, presence no). Recommend (a)+(c): presence
nag only above the threshold, freshness nag only where a JOURNAL/ exists.

## 6. Dogfooding & rollout

**Minimal first slice (dogfood in THIS repo, all advise-mode):**

1. `mkplan.bash` scaffolds `JOURNAL/` + day-1 file (+ seed `_JOURNAL_TEMPLATE_.md`).
2. Model: `PlanFolder.has_journal` / `latest_journal_date`.
3. SWEEP: `journal-freshness` (only where JOURNAL/ exists) + `journal-folder-present` (threshold-gated).
4. EDIT: `journal-dayfile-naming` (advise) + `journal-append-only` (advise) — extend
   `plan_qa_edit.matches()` to journal files; add `file_content_before` to context.
5. Config `plan_workflow.qa.journal.*` (mode default advise), `markdown_table_formatter` exempts JOURNAL/.

**Deferred to later slices:** block modes (naming only); COMMIT-gate coupling
(`journal-entry-with-progress`, `journal-completion-entry`); `enforce_on_completion`; any hard
escape-hatch. Ship, live with the nudges for a few weeks, THEN ratchet naming to block if it proves
low-false-positive — the same disciplined path `commit_gate_mode` took.

## 7. Reference doc — CLAUDE/PlanJournalling.md (copyable, client-customisable)

Split it explicitly into **POLICY the daemon enforces** vs **CONVENTION clients tune**:

- *Enforced by daemon* (config-driven, listed with the exact `plan_workflow.qa.journal.*` knob):
  day-file naming pattern, append-only guard, freshness/presence sweeps, mkplan scaffolding.
- *Convention (client owns)*: entry format, section headers, what to log, cadence — deferred to the
  sibling agent's data-model doc and the project-managed `_JOURNAL_TEMPLATE_.md`.
- Every enforcement lever must be a config knob (`enabled`, `mode`, `dir_name`, `freshness_days`,
  `enforce_on_completion`, `grandfather_before`) so a client customises via `.claude/hooks-daemon.yaml`
  only — never by editing `src/`. `dir_name` in particular must be config (some clients may want `journal/`
  or `LOG/`), which means checks read `ctx.journal_dir_name`, not a hardcoded `"JOURNAL"`.

## 8. Open questions & risks (need a human decision)

1. **Append-only: forever advise, or eventually block?** Correcting today's own entry is legitimate;
   the prefix test can't distinguish "fix my last line" from "rewrite paragraph 2". Lean advise-only.
2. **markdown_table_formatter exemption for JOURNAL/** — needed for a sound append-only invariant,
   but removes auto-formatting from journals. Acceptable? Or make append-only tolerant of
   whitespace-only diffs instead of exempting?
3. **Grandfathering 160 existing plans** — threshold vs allowlist vs presence-only. Which?
4. **Date source & the day-boundary** — YY-MM-DD from local clock or UTC? (This very session saw the
   system date roll 07-13 → 07-14 mid-run, which would legitimately produce two day-files in one
   session — the naming check must accept "yesterday or today", not strictly `date.today()`.)
5. **Freshness signal** — newest day-file *name* (works for uncommitted journals) vs git commit date
   (consistent with staleness-nag but blind to uncommitted logs). Recommend filename; confirm.
6. **Does journaling default ON in the daemon deploy, or opt-in?** Turning it on by default scaffolds
   JOURNAL/ in every client's next plan — is that desired out of the box, or `enabled: false` until a client opts in?
7. **One-file-per-day vs single append log** — sibling agent's data-model call, but it changes
   append-only granularity (per-day files reset the prefix invariant daily, which is *safer*). Flag the coupling.
8. **Untracked journals through a release** — CLAUDE/Plan is tracked source; the repo already warns
   against untracked plan folders. Does the commit gate need to *see* uncommitted journal files as a
   drift finding, or is that out of scope for advise-first?

```
```

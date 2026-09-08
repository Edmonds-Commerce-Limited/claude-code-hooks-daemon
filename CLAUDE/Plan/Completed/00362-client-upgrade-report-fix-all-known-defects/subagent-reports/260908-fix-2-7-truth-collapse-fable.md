# Task 2.7 (D13) — truth-changes report collapses superseded entries

**Branch**: `agent-afb52f1789221e7f8-f43a3bf2` · **Commits**: `162efcc6` (fix),
`89330900` (Plan 00329 ticks) · **Model**: Fable 5.1

## What was wrong

`format_truth_changes_for_llm` (`src/claude_code_hooks_daemon/install/truth_changes.py`)
emitted every entry of every manifest in the range with no supersession logic. The
plan-creation truth was asserted three times (v3.23.0, v3.25.0, v3.26.0) and only
the last is current, so an agent following the report literally wrote a claim into
the project's docs and then contradicted it twice.

## The key (step 1)

The schema had no field that identifies a truth across versions: `was` is by
construction the previous `now` reworded, so nothing is stable. Added an optional
`id: kebab-slug` per entry that names the TRUTH, not the release. Rules:

- Entries sharing an `id` across the loaded range form a chain; only the
  highest-version link is surfaced (coordinator decision).
- Un-keyed entries are never collapsed, even with identical text, and never
  affect a keyed neighbour (Plan 00329 Task 1.2).
- A blank `id`, or the same `id` twice in one manifest, is a `ValueError` at load.

Rejected: semantic matching (non-deterministic), `supersedes: <version>` pointers
(every link must know its predecessor; back-fill touches N files instead of tagging
N entries with one slug). Recorded in Plan 00329's journal
(`JOURNAL/00329-Journal-26-09-08.md`).

Back-filled in the live manifests:

- `plan-creation` — v3.23.0, v3.25.0, v3.26.0.
- `plan-size-remedies` — v3.50.0 ("trim it"), v3.53.0 ("three remedies"; its own
  `now` says "correct your docs if they assert the two-remedy version").

NOT keyed, deliberately: the v3.40.0 / v3.49.1 "Notes & Updates" pair Plan 00329
lists as a chain. v3.40.0 says where the activity stream lives (JOURNAL/);
v3.49.1 says what the mkplan fallback skeleton emits. v3.49.1's `now` does not
restate the JOURNAL/ instruction, so collapsing would drop it. Two truths.

## The formatter (step 2)

`collapse_superseded(manifests) -> list[SurfacedTruthChange]` keeps version order
and places a collapsed truth at the position of the release that last revised it.
Text output marks it `• (v3.26.0, revised in v3.23.0, v3.25.0) [plan-creation] WAS:`
and, when any entry collapsed, the header adds one instruction: reconcile any earlier
form of that statement to the same NOW. JSON output (`run_check_truth_changes`) is
collapsed the same way and gains `id` and `superseded_versions` per entry, so both
formats surface the same set. CLI wrapper untouched.

## Tests (step 3)

`tests/unit/install/test_truth_changes.py`: 22 new tests — id parsing and the two
load errors, collapse semantics (partial range, single-link trail, keyed removal as
latest, order), formatter trail and header, JSON collapse, and
`TestRealManifestCorpus` over the SHIPPED manifests: no `id` surfaced twice (both
via `collapse_superseded` and by counting `[id]` markers in the text), plan-creation
surfaced once as the v3.26.0 value with trail `["3.23.0", "3.25.0"]`,
plan-size-remedies once as v3.53.0, the three superseded instructions absent from
the text, and every id a lower-case slug. One pre-existing exact-dict JSON assertion
gained the two new fields.

## Measurement (Plan 00329 Task 1.3)

Full span over the real corpus: 25 manifests, 74 → 71 entries, 89,580 → 87,497
bytes. Small — bounding (Plan 00329 Phase 2) stays the primary size fix; this
change fixes the correctness defect, not the volume.

## Docs

- `CLAUDE/UPGRADES/truth-changes/README.md` — `id` documented; new "Supersession"
  section; authors told to back-fill the older file when revising a keyed truth.
- `CLAUDE/UPGRADES/UNRELEASED/truth-changes/README.md` — same guidance at staging.
- `.claude/skills/hooks-daemon/upgrade.md` step 4 — what a `revised in` marker means.
- Release-notes callout `13-truth-changes-collapse-superseded-entries.md`
  (Plan 00362, audience: client projects).

## Plan 00329

Ticked (worktree copy) with hash `162efcc6`: Tasks 1.1, 1.2, 1.3, 4.2 and the two
supersession success criteria. Left open: Phase 0 (canary envelope), Phase 2
(bounding/offload), Phase 3 (topic chunking — the `id` slug is the topic key Task
3.2 wants), Task 4.1. Plan 00362 PLAN.md Task 2.7 was not ticked — left to the
coordinator at merge.

## QA

- `pytest tests/unit/install tests/unit/daemon/test_cli_check_truth_changes.py tests/unit/docs_qa/test_corpus.py` — 1,250 passed.
- `ruff check`, `ruff format --check`, `mypy --strict` on the two touched Python
  files — clean.
- Not touched: `install/breaking_changes_detector.py`, `_parse_version`. No daemon
  restart, no sed, no stash.

## Worktree setup note

`scripts/setup_worktree.sh` creates a NEW worktree (usage: `<branch-name> [base]`) and cannot be run inside an existing one; the equivalent for a pre-made
worktree was `uv sync --frozen --extra dev` (the `dev` extra is what carries
pytest — a bare `uv sync` leaves it out).

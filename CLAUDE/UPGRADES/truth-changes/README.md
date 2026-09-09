# Truth-Changes Schema

Per-version YAML files recording statements that **were true** about how to work in
a project but became **false** (replaced by a new truth, or retired entirely) in a
given release. Used by the `check-truth-changes` CLI command and by the `upgrade.md`
skill flow to drive **project-doc reconciliation** after an upgrade.

The motivating case: before v3.16.0 the next plan number was found by scanning the
`CLAUDE/Plan/` folder; from v3.16.0 it comes from `git config --local hooksdaemon.latestPlanNumber`. A project's own docs may still assert the old truth,
and nothing reconciles them. Truth-changes close that gap.

See Plan 00118 (`CLAUDE/Plan/.../00118-docs-upgrade-guidance-mechanism/PLAN.md`).

## File Naming

```
CLAUDE/UPGRADES/truth-changes/v{X.Y.Z}.yaml
```

One file per release that changed a documented truth. The `version` field records
**when the truth changed**, which may predate the release that first ships this
mechanism (backfill is fine — the re-discovery CLI surfaces it for any upgrade range
that spans the version). Releases that change no documented truth need no file.

## Schema

```yaml
version: "3.16.0"            # Exact version string; when the truth changed
truth_changes:
  - was: >
      A natural-language statement of what used to be true. Matched
      SEMANTICALLY against the project's own docs by the LLM — not a regex.
    now: >
      The replacement truth. The LLM updates the project's docs to say this.
  - was: "Some retired concept the docs should no longer mention."
    now: ~                   # null/empty => remove all reference; no replacement
  - topic: plan-workflow     # the DOCUMENT AREA; chunks the report for delegation
    id: plan-creation        # optional: names the TRUTH, so later revisions collapse
    was: "How a plan is created, as the docs asserted it before this release."
    now: "How a plan is created from this release on."
```

Two keys per entry, plus two optional keys:

- **`was`** — what the docs used to assert, in plain language. The LLM finds docs
  that assert this and reconciles them. No `detect:` shell probes — the LLM is the
  matcher.
- **`now`** — the replacement truth, **or `~`/empty** to mean "this is no longer
  true; remove all reference to it, there is no replacement."
- **`id`** (optional) — a stable kebab-case slug naming the **truth**, not the
  release. Give an entry the same `id` as an earlier release's entry when it
  revises that same truth again (its `was` is roughly the earlier entry's `now`).
  Omit it for a truth that stands alone. A blank `id`, or the same `id` twice in
  one file, is a load error.
- **`topic`** (expected on every entry) — a kebab-case slug naming the **document
  area** the truth lives in (`plan-workflow`, `daemon-cli`, `git-safety`, …).
  Entries sharing a topic are written to one chunk file for delegation; two truths
  that could edit the same project document must share a topic, because chunks
  are dispatched to subagents in parallel. Reuse an existing slug (`grep topic:`
  across this directory) before coining one. A `topic` never collapses anything —
  that is what `id` is for. An entry with no topic falls back to its `id` as its
  chunk key, and one with neither lands in a single `unassigned` chunk the
  summary marks SEQUENTIAL, which the upgrade skill runs alone after the others.
  A blank `topic` is a load error.

### Supersession: one truth, surfaced once

A truth that changed in several releases (the plan-creation truth changed in
v3.23.0, v3.25.0 and v3.26.0) must not be replayed once per change — an agent
following the report literally would assert the v3.23.0 claim into the project's
docs and then contradict it twice. So entries sharing an `id` across the loaded
range form a chain, and the report surfaces **only the highest-version link**,
marked `(v3.26.0, revised in v3.23.0, v3.25.0) [plan-creation]`, with an
instruction to reconcile any earlier form of the statement to the same `now`.
The full history stays on disk; only what is surfaced changes.

Un-keyed entries are never collapsed — not even two with identical text — and an
un-keyed entry never interferes with its keyed neighbours. When you add an entry
that revises a truth already in the corpus, key BOTH: the new entry and the
existing one it supersedes (back-filling an `id` into an older file is expected
and harmless).

### Offload: the report is a file, stdout is bounded

`check-truth-changes` exits 1 whenever it has entries, and Claude Code delivers
an exit-1 command result head-and-tail with the middle DROPPED past roughly
10,000 characters — a full-span report (~90 KB) reached the agent with most of
its entries missing and no marker saying so. So the command writes the full
report to `<project>/untracked/truth-changes/v<from>-to-v<to>/REPORT.md`, one
subagent brief per topic chunk beside it (`chunk-NN-<topic>.md`), and prints a
summary bounded by `SUMMARY_MAX_BYTES` (8,000 bytes) that names them. The bound
is a constant, not a function of the corpus. `--full` prints the whole report
inline; `--report-dir` moves the files; `--project-root` pins the project.

## How it is consumed

1. **At upgrade time** — `upgrade.md` parses `UPGRADE_METADATA` (`from_version`,
   `to_version`), runs `check-truth-changes` for the `(from, to]` range, and
   dispatches one subagent per chunk file, in parallel (the SEQUENTIAL chunk
   last, alone). Each subagent semantically scans the project's own docs
   (`CLAUDE/`, `docs/`, `README*`, `AGENTS*` — **never** `.claude/hooks-daemon/`
   internals) for its entries, updating the `was` truth to `now` or removing it
   when `now` is empty, with minimal edits, and returns only the files it
   changed.
2. **Any time** — `check-truth-changes --from X --to Y` re-generates the report
   for the range, so an LLM can re-reconcile without an upgrade.

Idempotent by construction: if a doc no longer asserts `was`, there is nothing to do,
so a second reconcile is a no-op.

## Staging and release

Stage new entries during the release cycle in
`CLAUDE/UPGRADES/UNRELEASED/truth-changes/v{X.Y.Z}.yaml`. At release time the
`/release` skill moves them into this flat `truth-changes/` directory (keeping their
version-named filenames). See `CLAUDE/development/RELEASING.md` Step 6.

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
```

Two keys per entry. That is the whole schema:

- **`was`** — what the docs used to assert, in plain language. The LLM finds docs
  that assert this and reconciles them. No `detect:` shell probes — the LLM is the
  matcher.
- **`now`** — the replacement truth, **or `~`/empty** to mean "this is no longer
  true; remove all reference to it, there is no replacement."

## How it is consumed

1. **At upgrade time** — `upgrade.md` parses `UPGRADE_METADATA` (`from_version`,
   `to_version`), loads every truth-changes file in the `(from, to]` range, and for
   each `{was, now}` semantically scans the project's own docs (`CLAUDE/`, `docs/`,
   `README*`, `AGENTS*` — **never** `.claude/hooks-daemon/` internals), updating the
   `was` truth to `now` or removing it when `now` is empty. Minimal edits.
2. **Any time** — `check-truth-changes --from X --to Y` re-prints the aggregated
   `was → now` list for the range, so an LLM can re-reconcile without an upgrade.

Idempotent by construction: if a doc no longer asserts `was`, there is nothing to do,
so a second reconcile is a no-op.

## Staging and release

Stage new entries during the release cycle in
`CLAUDE/UPGRADES/UNRELEASED/truth-changes/v{X.Y.Z}.yaml`. At release time the
`/release` skill moves them into this flat `truth-changes/` directory (keeping their
version-named filenames). See `CLAUDE/development/RELEASING.md` Step 6.

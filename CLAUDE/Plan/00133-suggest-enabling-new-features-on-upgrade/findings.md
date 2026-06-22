# Findings — Investigation of the Upgrade Feature-Suggestion Gap

Investigation date: 2026-06-22. Repo state: main @ `ae7a0f1` (v3.23.0 shipped).

## Headline

**A mechanism for "announce newly-available config options on upgrade" already
exists — `config_migrations` — but it is (1) abandoned since v2.15.2, (2) not
wired into the upgrade flow, and (3) only informational, never a strong
"enable this" recommendation.** The user's request is best served by reviving,
backfilling, strengthening, and wiring this existing mechanism rather than
building a new one.

## Finding 1 — The config-changes manifest series stops at v2.15.2

`CLAUDE/UPGRADES/config-changes/` contains manifests only up to:

```
v2.2.0 … v2.13.0, v2.14.0, v2.15.0, v2.15.1, v2.15.2
```

There are **zero v3.x manifests**. Everything added across v3.0 → v3.23.0 —
including `markdown_organization.allow_untracked_claude_memory` (v3.23.0),
`markdown_organization.extra_allowed_markdown_paths` (v3.19.0),
`yolo_container_detection.show_on_session_start` (v3.22.0), and others — has
**no `added:` entry anywhere**. The advisory therefore has nothing to report
for any v3 upgrade.

## Finding 2 — `config_migrations.py` is fully built and already does most of the job

`src/claude_code_hooks_daemon/install/config_migrations.py`:

- Range-loads `config-changes/v{X.Y.Z}.yaml` between two versions.
- Schema per file: `version / date / breaking / upgrade_guide / config_changes: {added, renamed, removed, changed}`; each `added` entry has
  `key / description / example_yaml`.
- `run_check_config_migrations(...)` **diffs the manifest's `added` keys against
  the client's actual config** and produces three labelled buckets:
  - `⚠️  Action Required`
  - `💡 New Options Available` ← this is exactly the "dormant feature" surface
  - `✅ No Changes Needed`

So the diff-against-client-config capability the user wants ("features not
enabled in client projects") **already exists**. It just has no data and no
caller.

## Finding 3 — A CLI command exists but the upgrade skill never calls it

- `daemon/cli.py:1881 cmd_check_config_migrations` + subparser
  `check-config-migrations` (cli.py:3130) — present and wired to the loader.
- `src/claude_code_hooks_daemon/skills/hooks-daemon/upgrade.md` references
  **only** `check-truth-changes`. Grep for `check-config-migrations` /
  `config-changes` / `New Options` in `upgrade.md` → **NOT REFERENCED**.

So even with manifests present, the post-upgrade flow would never surface them.
truth-changes got wired into `upgrade.md` (Plan 00118); config-changes did not
(or was wired and later lost — to confirm in git history during the plan).

## Finding 4 — Wording is informational, not recommendation-grade

The advisory label is `💡 New Options Available` with each option's
`description` + `example_yaml`. There is:

- No notion of **recommended vs. neutral** — every added key reads the same.
- No distinction between "default already safe, FYI" and "**dormant unless you
  opt in** — you are missing protection until you act."

The user explicitly wants the memory feature **promoted / strongly suggested**,
which the current flat listing does not convey.

## Finding 5 — Adjacent mechanisms confirm the established pattern to mirror

- **truth-changes** (`install/truth_changes.py`) — same range-loader shape,
  `cli check-truth-changes`, wired into `upgrade.md` step 4, governed by
  RELEASING.md Step 6 (move `UNRELEASED/truth-changes/`) and Step 7 (checklist
  prompt to author entries). This is the **template** for "how a per-version
  upgrade-guidance manifest is kept current and surfaced."
- config-changes predates truth-changes and has the loader + CLI but is missing
  the *release-discipline* (no `UNRELEASED/config-changes/` staging, no
  RELEASING.md step keeping it current) — which is why it rotted after v2.15.2.

## Implications for the plan

1. **Revive + backfill** v3.x `config-changes` manifests (at minimum the
   dormant opt-in options; the memory feature is the priority example).
2. **Strengthen the schema/advisory** to mark options as `recommended` and to
   flag *dormant* (default preserves old behaviour) vs. *informational*, so the
   advisory can promote rather than merely list.
3. **Wire `check-config-migrations` into `upgrade.md`** (a step alongside
   truth-changes), so every upgrade surfaces dormant-feature suggestions.
4. **Add release discipline** mirroring truth-changes: an
   `UNRELEASED/config-changes/` staging dir + RELEASING.md steps so manifests
   never rot again, and the Step 7 checklist prompts "did this release add an
   opt-in option that should be promoted?"
5. **Hot-fix viability**: the change is additive (data + wording + wiring +
   docs) with no behaviour change to handlers, so a PATCH/MINOR is plausible;
   confirm bump level once schema changes are scoped (a new schema field leans
   MINOR).

## Open questions for PLAN.md

- Extend the existing `config-changes` schema with a `recommended: bool` /
  `dormant: bool` (or a `promote:` block), **or** add a separate lightweight
  "feature-suggestions" manifest? (Leaning: extend config-changes — DRY.)
- How far to backfill v3.x — every added key, or only dormant opt-in options?
  (Leaning: all dormant opt-in options across v3.x; neutral additions optional.)
- Should the advisory ever **auto-apply** an enable, or strictly suggest?
  (Leaning: suggest only — enabling is a client decision; matches truth-changes
  "guidance not mutation".)

# Ideation 4 — Authoring, Source-of-Truth, Content Model & Release Integration

**Lens**: Where do doc-upgrade tasks come from, how are they authored/maintained,
and how do they ship downstream. Ignores delivery UI (covered by other agents).

---

## 0. The load-bearing finding (shipping)

`config-migrations` manifests resolve via
`Path(__file__).parent.parent.parent.parent / "CLAUDE/UPGRADES/config-changes"`
(`install/config_migrations.py:296-306`). That path is the **daemon's own clone**
(`.claude/hooks-daemon/CLAUDE/UPGRADES/...`), which DOES exist on a downstream box
because install clones the whole repo. But `post-upgrade-tasks/*.md` live in
`CLAUDE/UPGRADES/v{M}/...` of that same clone — they are *physically present
downstream after install/upgrade* yet **nothing reads them**. So the "shipping"
problem is half-solved by accident: the files are already on disk in the clone.
The real gaps are (a) they are authored as prose for THIS repo's release flow, not
as machine-aggregatable data, and (b) no code path enumerates the applicable subset.

**Decision: do NOT invent a release artifact or a `src/`-packaged data dir.**
Reuse the existing clone-on-disk convention exactly like `config-changes` does.
A doc-upgrade-task generator resolves tasks from the cloned
`CLAUDE/UPGRADES/.../doc-tasks/` the same way `_default_manifests_dir()` does.
Zero new shipping mechanism, zero new bootstrap manifest entry, refreshed on every
upgrade for free (the clone is checked out to the target tag).

---

## 1. Extend the schema, do not fork it

Doc-upgrade tasks are a **subtype of post-upgrade-tasks**, not a new artifact. The
existing schema (Type/Severity/Applies-to/Idempotent + Why/Detect/Handle/Confirm/
Rollback) already encodes 90% of what we need. Forking would mean two schemas to
maintain, two release-move steps in RELEASING.md, two CLI readers, schema drift.

Three concrete extensions to the existing schema:

1. **Add `Type: docs-update`** to the Type enum (audit | config-migration |
   workflow-change | data-migration | notification | docs-update | other). This is
   the discriminator the new CLI filters on. Existing tasks are untouched.
2. **Add a machine-readable YAML front-matter block** in addition to the human
   header, so the CLI does not have to parse markdown bullets. Today `Applies to`
   is free prose ("≤v3.2.1", "all pre-v3.7.0 installs (upgrade will...)"). That is
   unparseable. Add a fenced `yaml` block immediately after the title containing
   the same fields in structured form. The prose header stays for human/LLM
   readability; the fenced block is the source of truth for the aggregator.
3. **Add a `detect:` shell snippet field** in that block (see §3) so detection is
   machine-runnable, with the prose `## How to detect` retained for LLM nuance.

This keeps ONE directory convention, ONE release-move step, ONE schema doc.

---

## 2. Content data model — worked example

A doc-task file: `CLAUDE/UPGRADES/v3/v3.11-to-v3.12/doc-tasks/01-plan-number-git-counter.md`
(co-located beside `post-upgrade-tasks/` in the versioned guide; same move-at-release flow).

````markdown
# Task: Update plan-number docs to the git-anchored counter

```yaml
# Machine-readable header (source of truth for the CLI aggregator)
id: plan-number-git-counter          # stable slug; survives renames; used for retire/supersede
type: docs-update
severity: recommended
introduced_in: 3.12.0                 # version that INTRODUCED the behaviour change
applies_to: "<3.12.0"                 # semver range; LLM/CLI applies if synced_from < this
idempotent: yes
targets:                              # project docs likely to be stale (hints, not exhaustive)
  - "CLAUDE/PlanWorkflow.md"
  - "docs/PLAN_SYSTEM.md"
  - "CLAUDE/Plan/**/*.md"
detect: |                            # exit 0 == task APPLIES (stale docs found). See §3.
  grep -rIlE 'find +CLAUDE/Plan|ls +CLAUDE/Plan' \
    CLAUDE docs 2>/dev/null \
    | xargs -r grep -L 'hooksdaemon\.latestPlanNumber' \
    | grep -q .
supersedes: []                        # ids this task replaces (see §4)
```

**Type**: docs-update · **Severity**: recommended · **Applies to**: `<3.12.0` · **Idempotent**: yes

## Why

Since Plan 00112 (v3.12.0) the authoritative next-plan-number source is the git
counter `hooksdaemon.latestPlanNumber`, bootstrapped from a folder scan only when
unset. Projects that copied an early `PlanWorkflow.md` still instruct agents to
scan `CLAUDE/Plan/` (`find CLAUDE/Plan ...`), which races and reuses numbers under
parallel agents.

## How to detect if this applies to you

Run the `detect:` snippet, or by hand: search your project docs for
`find CLAUDE/Plan` / `ls CLAUDE/Plan` plan-number idioms that do NOT mention
`hooksdaemon.latestPlanNumber`. Any match → your docs predate the git counter.

## How to handle

In each matched file, replace folder-scan plan-number guidance with: "The next plan
number comes from `git config --local --type int hooksdaemon.latestPlanNumber`
(+1); the daemon increments it atomically. Fall back to scanning `CLAUDE/Plan/` for
the highest `NNNNN-` prefix only when the counter is unset (first run)." Keep the
project's own surrounding wording. Ask the user before deleting large doc sections.

## How to confirm

Re-run the `detect:` snippet — it must now exit non-zero (no stale files). Optionally
`git diff` the edited docs to confirm only plan-number guidance changed.

## Rollback / if this goes wrong

`git restore --source=HEAD~1 -- <file>` (or revert the docs commit). No runtime
effect — these are documentation edits only.
````

Why this shape: the fenced `yaml` is a strict, lintable contract the CLI parses
without markdown heuristics; the markdown body is the LLM execution surface. One
file serves both consumers — no duplicate data file.

---

## 3. Detection — a three-tier "machine-gated, LLM-flexible" model

False nags are the #1 failure mode (a task that always fires trains the LLM to
ignore it). Encode detection in tiers, evaluated cheapest-first:

1. **`applies_to` semver gate (machine, mandatory)**: CLI computes
   `synced_from_version` (the persisted docs-synced marker, see §4) and only
   considers tasks whose `applies_to` range contains it. Pure version arithmetic;
   no I/O. This alone kills most noise on a fresh install.
2. **`detect:` shell snippet (machine, optional but strongly encouraged)**: a
   POSIX-sh one-liner whose **exit code is the contract — `0` = task applies**.
   Runs read-only against the project (grep/find/ls; never mutates). The CLI runs
   it with a timeout and treats non-zero / timeout / error as "does not apply"
   (fail-safe: when unsure, don't nag). This is what distinguishes "your docs say
   `find CLAUDE/Plan`" from "your docs already migrated".
3. **`## How to detect` prose (LLM, mandatory)**: the human/LLM fallback for nuance
   the snippet can't capture (e.g. "if you have a custom plan tool, the wording
   may differ"). The LLM is told the snippet's verdict but may override with reason.

A task with no `detect:` snippet is treated as "applies whenever the version gate
passes" — acceptable for `notification`/`workflow-change` types, discouraged for
`docs-update` (those should always be grep-detectable). A QA check (see §5) can warn
when a `docs-update` task omits `detect:`.

This is the right mix: tier-1 is free and exact for version scoping; tier-2 is a
small, reviewable, deterministic gate that prevents nagging migrated projects;
tier-3 keeps the LLM in the loop for the irreducibly fuzzy cases.

---

## 4. Versioning, synced-marker, retire/supersede

**`introduced_in` vs `applies_to`**: `introduced_in` is documentation (which release
shipped the change). `applies_to` is the *trigger predicate* — a semver range
(`"<3.12.0"`, `">=3.5.0 <3.18.0"`). The aggregator's job for a v3.5→v3.18 jump is:
*emit every task whose `applies_to` range contains the project's last-synced
version.* A six-version jump naturally unions all still-applicable tasks because
each evaluates its own range against the single `synced_from` point.

**The persisted "docs-synced version" marker (the one genuinely missing piece).**
Store it as a git-config key to mirror Plan 00112's own pattern and the project's
existing `hooksdaemon.*` namespace:

```
git config --local --type int? -> use string: hooksdaemon.docsSyncedVersion = 3.18.0
```

Stored in the **project** repo (not the venv metadata, which is per-environment and
wiped on venv prune). The CLI reads it as the lower bound; after the LLM completes
the emitted tasks, the skill/CLI writes the current daemon `__version__` back.
First run (key unset) → treat as `0.0.0` so the full applicable history is offered
once, then the marker advances. This makes the whole thing idempotent: a project
that already migrated and stamped `docsSyncedVersion` gets zero tasks next upgrade.

**Retire / supersede.** Two mechanisms:

- **Natural expiry**: a task simply stops matching once every supported project has
  passed its `applies_to` upper bound — but we never delete the file (history /
  late upgraders from very old versions). Tasks are cheap on disk.
- **`supersedes: [<id>, ...]`**: when a later task replaces an earlier one (the
  earlier guidance was wrong or the behaviour changed again), the new task lists the
  old `id`. The aggregator, when emitting a set, drops any task whose `id` appears
  in a newer in-range task's `supersedes`. Stable `id` (not filename) is what makes
  this robust across the release-move/rename.

---

## 5. Release-flow integration & maintenance burden

**Who authors, when** — mirror post-upgrade-tasks exactly:

- A doc-task is authored during the dev cycle that introduces the doc-affecting
  change, dropped into `CLAUDE/UPGRADES/UNRELEASED/doc-tasks/NN-*.md` (sibling of
  the existing `UNRELEASED/post-upgrade-tasks/`). **Crucially: the same plan that
  changes daemon behaviour writes the doc-task that tells downstream projects to
  update their docs.** For the motivating case, Plan 00112 should have written
  `01-plan-number-git-counter.md` at the time.
- **RELEASING.md Step 6 already moves `UNRELEASED/post-upgrade-tasks/` into the
  versioned guide.** Extend that same step to also move `UNRELEASED/doc-tasks/`.
  One additional `git mv` line + one additional index-populate. No new gate.
- A new **blocking-lite checklist item** in RELEASING.md Step 7 (Opus docs review):
  "if this release changed any guidance the daemon injects or any documented
  workflow, a `doc-task` exists for it." This is the anti-drift mechanism — it
  forces the author to ask "did I just make some downstream project's docs wrong?"

**Keeping the burden low**:

- Reuse of the existing schema/dir/move-step means ~3 extra lines in RELEASING.md,
  not a new pipeline.
- The `detect:` snippet is the only genuinely new authoring effort, and it's a
  one-line grep for the `docs-update` case.
- A QA check (`scripts/qa/run_doc_tasks_check.sh`, sibling of the magic-value check)
  validates every `doc-tasks/*.md`: parseable `yaml` block, required fields present,
  `applies_to` is a valid semver range, `detect:` snippet has valid sh syntax
  (`sh -n`), `id` unique across all tasks, every `supersedes` id resolves. This
  catches schema rot mechanically at commit time, not in the field.

---

## 6. MVP vs full vision; risks

**Full vision**: every behaviour/guidance change ships a doc-task; CLI emits the
applicable union for any version range; skill drives the LLM through them and stamps
`docsSyncedVersion`; SessionStart advisory nudges when stale; back-filled tasks for
historical versions.

**Risks**:

- *Tasks never authored* (highest risk — same as why post-upgrade-tasks are sparse).
  Mitigation: the RELEASING Step 7 checklist + the dogfooding culture; make writing
  one cheap (one grep + one paragraph).
- *Schema rot / drift*: mitigated by the QA validator (§5).
- *False nags*: mitigated by the tiered version+detect gate (§3) and fail-safe
  "unsure → silent".
- *Marker desync* (project on v3.18 but `docsSyncedVersion` stuck at 3.5): the CLI
  always shows the computed range so the LLM can sanity-check; `--from`/`--to`
  overrides (mirroring `check-config-migrations`) let it be forced.
- *Stale `targets:`/`detect:` for projects with unusual layouts*: tier-3 LLM prose
  is the escape hatch; `targets` are explicitly "hints, not exhaustive".

---

## Recommended MVP

1. **Extend, don't fork**: add `Type: docs-update` + a fenced `yaml` source-of-truth
   block (with `id`, `applies_to`, `introduced_in`, `detect`, `supersedes`,
   `targets`) to the existing post-upgrade-task schema. Update
   `UNRELEASED/post-upgrade-tasks/README.md` (or a sibling `doc-tasks/README.md`).
2. **Ship via the existing clone** (like `config-changes`): a resolver mirroring
   `_default_manifests_dir()` that globs `CLAUDE/UPGRADES/**/doc-tasks/*.md` from the
   daemon clone. No new release artifact, no `src/` data dir, no bootstrap entry.
3. **One persisted marker**: `git config --local hooksdaemon.docsSyncedVersion`,
   read as lower bound, written after completion.
4. **One CLI command** `cmd_docs_upgrade` (aggregator) that: computes the version
   range from the marker (or `--from/--to`), loads in-range tasks, applies the
   version gate + runs each `detect:` snippet, drops superseded ids, prints the
   surviving tasks' markdown bodies for the LLM. (Delivery UI/skill = other agents.)
5. **Author the motivating task now**: `01-plan-number-git-counter.md` as the first
   real `docs-update` task and proof-of-schema.
6. **QA validator** for doc-task files (schema, semver, `sh -n`, unique ids).
7. **RELEASING.md**: extend Step 6 move to include `doc-tasks/`; add the Step 7
   "did this change downstream docs?" checklist line.

Deferred to full vision: SessionStart staleness advisory, back-filling historical
tasks, a dedicated skill vs subcommand (other agents own that call).

## Open questions for triage

1. **Separate `doc-tasks/` dir or just `Type: docs-update` inside `post-upgrade-tasks/`?**
   Separate dir gives the CLI a clean glob and keeps the docs-sync marker logic from
   entangling with severity/audit tasks; single dir is less churn. I lean **separate
   `doc-tasks/` dir, shared schema** — clean machine boundary, one schema doc.
2. **Marker storage**: git-config (`hooksdaemon.docsSyncedVersion`, my pick — matches
   00112 pattern, survives venv prune, per-project) vs a tracked project file
   (`.claude/.docs-synced`) vs venv metadata (rejected — per-env, ephemeral)?
3. **Should `detect:` snippets run automatically by the CLI, or only be *shown* to
   the LLM to run?** Auto-run avoids false nags but means the daemon executes
   project-authored... no — these are *daemon-authored* snippets, read-only grep, run
   with timeout. I lean auto-run with fail-safe-silent. Confirm the sandbox/timeout
   posture with the delivery-lens agent.
4. **Back-fill scope**: author historical `docs-update` tasks (e.g. for every
   `get_claude_md()` that changed) or start fresh from v3.18 and only the
   plan-number task? Back-fill is high-value but high-effort; triage call.
5. **Interaction with `get_claude_md()` injection**: should fixing
   `plan_number_helper.get_claude_md()` (currently `None`) be in-scope here, since
   the injected guidance and the doc-task are two faces of the same fix? They should
   land together so the daemon's own injected CLAUDE.md and the downstream doc-task
   tell the same story.

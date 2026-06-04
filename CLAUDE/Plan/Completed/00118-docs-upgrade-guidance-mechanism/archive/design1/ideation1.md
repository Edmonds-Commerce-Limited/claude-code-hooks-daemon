# Ideation 1 — Lens: The CLI Command Design

**Agent**: #1 of 4 | **Lens**: the daemon CLI subcommand(s) that emit per-version
docs-upgrade guidance. Opinionated, modelled directly on `check-config-migrations`.

---

## 1. The command: `check-docs-migrations`

Name it as the **sibling of `check-config-migrations`**. Config migrations cover
`.claude/hooks-daemon.yaml`; docs migrations cover the project's `CLAUDE/` and
`README.md`. Same verb (`check-`), same noun shape (`-migrations`), same mental
model. Do NOT invent a novel word ("docs-upgrade", "post-upgrade") at the CLI
layer — the noun used for config is `migrations`, so reuse it. Alias
`docs-upgrade` may be added later but `check-docs-migrations` is canonical.

### Flags (mirror config exactly, plus two new ones)

| Flag                                             | Default           | Meaning                                                     |
| ------------------------------------------------ | ----------------- | ----------------------------------------------------------- |
| `--from VERSION`                                 | **auto** (see §4) | version upgrading from (exclusive)                          |
| `--to VERSION`                                   | `__version__`     | version upgrading to (inclusive)                            |
| `--format text\|json`                            | `text`            | LLM-readable vs machine-readable                            |
| `--applies-only`                                 | off               | suppress tasks whose detection probe says they do NOT apply |
| `--project-root PATH`                            | cwd resolution    | standard daemon flag                                        |
| `--manifests-dir PATH`                           | default resolver  | test override (mirrors config cmd)                          |
| `--severity-min critical\|recommended\|optional` | `optional`        | floor filter                                                |

**Deliberately NO `--output FILE`.** The LLM pipes to a temp file itself
(`> /tmp/docs.md`); adding `--output` duplicates shell redirection and invites
the pipe_blocker footgun. Keep the surface minimal, like the config command.

### Example invocations + sample output

```bash
# After an upgrade: "what docs must I touch going 3.11.0 → 3.17.0?"
$PYTHON -m claude_code_hooks_daemon.daemon.cli check-docs-migrations \
    --from 3.11.0 --to 3.17.0

# Re-discovery weeks later, only tasks that STILL apply to my repo:
$PYTHON -m ...cli check-docs-migrations --applies-only --severity-min recommended

# Machine-readable for a wrapping skill / SessionStart handler:
$PYTHON -m ...cli check-docs-migrations --from 3.11.0 --format json
```

Sample `text` output (LLM-targeted; mirrors `format_advisory_for_llm`):

```
Docs Migration Advisory: v3.11.0 → v3.17.0

⚠️  Action Required (1 task)

  [recommended] plan-number-docs-git-counter   (since v3.12.0)
  Applies-to: ≤v3.11.x   Detect: APPLIES (found "find CLAUDE/Plan" in CLAUDE/PlanWorkflow.md)
    Why:  Plan 00112 moved the authoritative next-plan-number to the git
          counter `hooksdaemon.latestPlanNumber`; folder-scan docs are now wrong.
    Do:   Update <project>/CLAUDE/PlanWorkflow.md and docs/PLAN_SYSTEM.md to state
          the next number = `git config --local hooksdaemon.latestPlanNumber` + 1,
          bootstrapped from a folder scan only when the key is unset.
    Confirm: grep -L "latestPlanNumber" CLAUDE/PlanWorkflow.md  → no output.
    Full guidance: CLAUDE/UPGRADES/v3/v3.11-to-v3.12/post-upgrade-tasks/01-...md

✅ No further docs tasks for this range.
```

Exit codes follow the config precedent: **0** = nothing applies, **1** =
tasks present, **2** = error. This lets a wrapping script branch trivially.

---

## 2. Data model & source of truth

**Reuse the existing `post-upgrade-tasks` schema as-is** — it is already 90% of
the requirement (RESEARCH §E). The new machinery is a *loader + aggregator +
detector*, not a new schema. Two concrete decisions:

### 2a. Source-of-truth location: a per-version manifest index, NOT loose `.md`

Loose `NN-*.md` files under `CLAUDE/UPGRADES/v{M}/.../post-upgrade-tasks/` are
the **authored content**, but the CLI must aggregate across an arbitrary version
*range* fast and without re-parsing every guide dir. Add a thin machine-readable
index — exactly the `config-changes/v{X.Y.Z}.yaml` pattern — at:

```
CLAUDE/UPGRADES/docs-changes/v{X.Y.Z}.yaml
```

Each file lists the docs tasks introduced **in that version**, each pointing at
its canonical `.md` for the long-form `Why/How`:

```yaml
version: "3.12.0"
date: "2026-..."
docs_tasks:
  - id: plan-number-docs-git-counter
    type: workflow-change
    severity: recommended
    applies_to: "<=3.11.999"          # version predicate, parsed like config range
    title: "Plan-number docs predate the git-anchored counter"
    summary: "Update plan-number docs to read hooksdaemon.latestPlanNumber."
    detect:                            # see §4 — drives --applies-only
      kind: file_grep
      paths: ["CLAUDE/PlanWorkflow.md", "docs/PLAN_SYSTEM.md"]
      pattern: "find\\s+CLAUDE/Plan|scan(ning)? CLAUDE/Plan"
      applies_when: present            # present|absent
    guide: "v3/v3.11-to-v3.12/post-upgrade-tasks/01-plan-number-git-counter.md"
```

This mirrors `config_migrations.py`'s `ConfigMigrationManifest` 1:1 — I'd build
a `DocsMigrationManifest` dataclass + `load_manifests_between()` clone. Reusing
the proven version-range loader (`_parse_version`, `from_v < v <= to_v`) is the
single biggest cost saving; copy that module's structure verbatim.

### 2b. Aggregation, dedupe, ordering

- **Aggregate**: `load_docs_manifests_between(from, to)` → flat list of tasks
  across the range (same exclusive-from/inclusive-to semantics as config).
- **Dedupe by `id`**: if a task is re-listed in a later version (re-emphasised),
  keep the *earliest* `since` version but the *latest* content. `id` is the dedup
  key — this is why each task carries a stable slug id, not just a filename.
- **Order**: `(severity_rank, since_version, id)` — critical first, then by the
  version that introduced it, then alphabetically. Severity rank is a named
  constant map `{critical:0, recommended:1, optional:2}` (NO magic ints).

---

## 3. How tasks are contributed: manifest vs `get_doc_upgrade_tasks()`

The RESEARCH points at two models. **My opinionated call: static manifest is the
MVP source of truth; a handler hook is an optional secondary contributor, not the
primary one.** Argument:

|                           | Static `docs-changes/*.yaml`                        | `Handler.get_doc_upgrade_tasks()`                        |
| ------------------------- | --------------------------------------------------- | -------------------------------------------------------- |
| Versioned                 | ✅ file *is* the version                            | ❌ handler only knows "now", not "what changed in v3.12" |
| Multi-version range       | ✅ load N files                                     | ❌ a single handler can't enumerate per-version deltas   |
| Authored at release time  | ✅ fits `/release` Step 6                           | ⚠️ needs a "version introduced" field per task anyway    |
| Survives handler deletion | ✅ (the plan_number doc task outlives any refactor) | ❌ task vanishes if handler removed                      |
| Detection logic           | declarative (`detect:` block)                       | could be real Python (richer)                            |

The decisive point: **docs tasks are about *what changed between versions*, which
is inherently a release-time, version-keyed fact — not a property of a live
handler instance.** `get_acceptance_tests()` works for playbooks because tests
describe *current* behaviour; doc-migration tasks describe *historical deltas*.
A handler cannot answer "what did v3.12 change about my docs" — only the v3.12
manifest can. So manifest wins as source of truth.

**Where the handler hook still earns its place** (full vision, not MVP): an
optional `get_doc_upgrade_tasks() -> list[DocUpgradeTask]` on `Handler`, collected
exactly like `get_acceptance_tests()` (the `_collect_tests` loop in
`playbook_generator.py` is the template). Its niche is **"applies to all,
version-agnostic" doc-consistency checks** — e.g. `plan_number_helper` itself
returning a task that says "if your CLAUDE.md still describes folder-scan, fix
it", regardless of upgrade range. These get merged into the manifest-sourced list
under a synthetic `since: all` version and deduped by `id`. This keeps the
motivating handler honest (it can ship its own doc-fix task) without making the
range-aggregation depend on live handlers.

---

## 4. Idempotency, re-runnability, "applies to current state"

This is the lever that makes it a *rediscoverable CLI command* rather than a
scroll-away message.

### 4a. Re-discovery

The command is **stateless and re-runnable** — an LLM weeks later just runs
`check-docs-migrations` with no flags. It needs a default `--from`. Resolve it,
in order:

1. `--from` if given.
2. A persisted **docs-synced marker** (RESEARCH §A flags this as missing): write
   `CLAUDE/UPGRADES/.docs-synced` (project-owned, committed) containing the last
   version whose docs tasks were acknowledged. `--mark-synced VERSION` writes it.
3. Fall back to the venv `.daemon-metadata.json` `daemon_version` if no marker.
4. Last resort: `0.0.0` (show everything).

So the loop is: upgrade → run command → do the doc edits → `--mark-synced 3.17.0`
→ future runs only show *newer* deltas. This is the idempotency story.

### 4b. "Does this still apply to MY repo?" — the `detect:` block

Every task carries a declarative detection probe so `--applies-only` can filter.
MVP supports two `kind`s (both pure-Python, no shelling out):

- `file_grep`: regex over named project files; `applies_when: present|absent`.
- `git_config`: check a `git config --local <key>` is set/unset.

For the plan example: `file_grep` for `find CLAUDE/Plan` in `PlanWorkflow.md`.
If the project already updated its docs, the probe returns "does not apply" and
`--applies-only` drops it — so re-running after the fix yields a clean ✅ even
if `--mark-synced` was never run. **Detection is the true idempotency guarantee;
the marker is just an optimisation/UX nicety.** This dual mechanism means a
multi-version jump LLM can trust `--applies-only` to show only real work.

---

## 5. The plan-number example, end to end

1. **Release-time (this repo)**: Plan 00112's release authors
   `CLAUDE/UPGRADES/docs-changes/v3.12.0.yaml` with the `plan-number-docs-git-counter`
   task (full §2a YAML above) + the long-form `.md` under the v3.11-to-v3.12 guide.
   `/release` Step 6 gains a sub-step: "for any moved post-upgrade-task of
   type `workflow-change`/`config-migration` that touches project docs, add a
   `docs-changes/v{X}.yaml` entry." (Maintenance cost: one YAML block per
   doc-affecting release — cheap.)
2. **Ship downstream**: `docs-changes/` lives under `CLAUDE/UPGRADES/`, which is
   in the cloned daemon tree at `.claude/hooks-daemon/`, so the manifest resolver
   (`Path(__file__).parents[3]`) finds it in *both* self-install and normal
   installs — identical to config-changes. No new shipping mechanism needed.
3. **Post-upgrade (downstream project)**: LLM (prompted by the upgrade skill or a
   SessionStart advisory) runs `check-docs-migrations --from 3.11.0`. The v3.12
   manifest is in range; `file_grep` finds `find CLAUDE/Plan` in their
   `PlanWorkflow.md` → APPLIES. Text output tells it exactly which files to edit
   and the confirm grep.
4. **LLM acts**, edits the project's `CLAUDE/PlanWorkflow.md`, re-runs with
   `--applies-only` → probe now returns absent → ✅ clean. Runs `--mark-synced 3.17.0`.

---

## 6. MVP vs full vision; risks; cost

**Full vision**: manifest + handler-contributed tasks + persisted marker +
SessionStart advisory ("docs stale for vX, run check-docs-migrations") + a
`/hooks-daemon docs-upgrade` skill subcommand wrapping the CLI + auto-apply mode.

**Risks**

- *Manifest rot*: authors forget the `docs-changes/` entry at release. Mitigate
  with a `/release` checklist gate + a QA lint that flags doc-affecting
  post-upgrade-tasks lacking a manifest entry.
- *Detection false-negatives*: a project that paraphrased its docs won't match
  `file_grep`. Accept it — the task still shows without `--applies-only`; detection
  is best-effort, the LLM is the backstop.
- *Self-install confusion*: tasks reference `<project>/CLAUDE/` but this repo IS
  the project. The command must label paths clearly; in self-install the daemon's
  own docs are the target, which is correct.

**Maintenance/release cost**: low. One new module cloning `config_migrations.py`,
one `cmd_check_docs_migrations` in `cli.py` (∼60 lines, copy the config cmd), one
manifest YAML per doc-affecting release, one `/release` sub-step. No new shipping
or bootstrap machinery.

---

## Recommended MVP

1. **`check-docs-migrations` CLI subcommand** with `--from/--to/--format/--applies-only/--severity-min/--manifests-dir`, exit codes 0/1/2 — a near-verbatim clone of `cmd_check_config_migrations`.
2. **`docs_migrations.py`** module: `DocsMigrationManifest` dataclass, `load_docs_manifests_between()` (copy the proven version-range loader), `generate_docs_advisory()`, `format_docs_advisory_for_llm()`.
3. **`CLAUDE/UPGRADES/docs-changes/v{X.Y.Z}.yaml`** manifests as source of truth, reusing the `post-upgrade-tasks` `.md` files for long-form via the `guide:` pointer.
4. **`detect:` block** with `file_grep` + `git_config` kinds powering `--applies-only` (this is the idempotency core).
5. **The v3.12 plan-number manifest** authored as the first real entry + acceptance test (`CliAcceptanceTest`) asserting it surfaces for `--from 3.11.0`.
6. Defer to v-next: persisted `.docs-synced` marker + `--mark-synced`, the `get_doc_upgrade_tasks()` handler hook, the SessionStart advisory, and the skill wrapper.

## Open questions for triage

1. **Marker in MVP or deferred?** I put `--mark-synced` in the full vision, but without it the default `--from` falls back to venv metadata — is that good enough, or is the committed marker needed day one for the multi-version-jump UX?
2. **Command name**: `check-docs-migrations` (config-sibling) vs `docs-upgrade` (matches the user's wording / future skill name). Pick one canonical, alias the other?
3. **Manifest vs reuse config-changes file**: should docs tasks live in a *separate* `docs-changes/` dir, or as a new `docs_changes:` section inside the existing `config-changes/v{X}.yaml`? One file per version is simpler to ship but couples two concerns.
4. **Should `--applies-only` be the default?** Showing only applicable tasks is the LLM-friendly behaviour; the verbose "show all" mode is arguably the opt-in. I defaulted to show-all for parity with config; reconsider.
5. **Auto-apply**: out of scope here, but does triage want a future `--apply` that edits docs directly (risky) vs. always leaving edits to the LLM (safe)?

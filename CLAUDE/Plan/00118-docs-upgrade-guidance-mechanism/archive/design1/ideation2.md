# Plan 00118 — Ideation #2: The Skill Design (LLM-Facing Experience)

**Lens**: How a developer/LLM actually invokes and runs the docs-upgrade flow.
Assumes the backend CLI command exists (designed by sibling agents). Here I
design the skill that *drives the LLM to edit project docs*, not just print.

---

## 1. New top-level skill vs. subcommand of `hooks-daemon`

**Decision: NEW SUBCOMMAND of the existing `hooks-daemon` skill router —
`/hooks-daemon docs-upgrade`. Not a new top-level skill.**

Trade-off analysis:

| Axis            | New skill `skills/docs-upgrade/`                                    | Subcommand `/hooks-daemon docs-upgrade`                        |
| --------------- | ------------------------------------------------------------------- | -------------------------------------------------------------- |
| Deployment      | New dir → `deploy_skills()` must copy it; second `copytree` target  | Free — already inside the refreshed skill dir                  |
| Bootstrap reuse | Needs its own self-bootstrap stanza + manifest entry (a 5th script) | Reuses `daemon-cli.sh` wrapper; **zero new bootstrap surface** |
| Discoverability | `/docs-upgrade` is its own slash command — arguably easier to find  | Discovered via `/hooks-daemon help`; one more case row         |
| Conceptual fit  | Implies docs-upgrade is a peer of "the daemon", which it isn't      | It is *part of upgrading the daemon* — belongs in the family   |
| Versioning      | Two skills can drift out of sync on refresh                         | Single skill refreshed atomically on every upgrade             |

The decisive factors are **bootstrap reuse** and **refresh atomicity**. The
self-bootstrapping/`bootstrap-checksums.txt` machinery (RESEARCH §C) is the most
fragile, release-coupled part of the system. A new top-level skill that needs to
self-verify would mean a 5th manifest artifact, a 5th verification loop in
RELEASING.md Step 14, and a fifth thing that "every existing install refuses to
run" if the manifest is wrong. `docs-upgrade` is **conceptually a continuation
of `upgrade`** — you upgrade the daemon, then you upgrade your docs to match. It
belongs in the same router. A standalone `/docs-upgrade` slash command is a
marginal discoverability win that is outweighed by deployment cost and the risk
of skill drift.

Mitigation for discoverability: the SessionStart advisory (sibling-agent
backend) and `upgrade.md` both tell the LLM verbatim to run
`/hooks-daemon docs-upgrade`. Discoverability comes from those pointers, not from
a top-level slash name.

---

## 2. The router wiring (delta to existing SKILL.md)

Two edits to the existing `skills/hooks-daemon/SKILL.md`:

**(a)** Add a documented command block under "Available Commands":

````markdown
### Sync Project Docs After Upgrade
After upgrading, reconcile YOUR project's docs with daemon behaviour changes:
```bash
/hooks-daemon docs-upgrade            # tasks since last docs-synced version
/hooks-daemon docs-upgrade --from 3.11.0  # explicit floor (multi-version jump)
/hooks-daemon docs-upgrade --list     # list applicable tasks, do not act
````

See [docs-upgrade.md](docs-upgrade.md) for the full workflow.

````

**(b)** Add a case to the router `case "$SUBCOMMAND"` block. Like `report`, this
is an **LLM-driven prompt**, so it emits markdown for Claude to follow — but it
first calls the CLI to fetch the live task set and splices it in:

```bash
    docs-upgrade)
        # LLM-driven: fetch applicable tasks from the daemon, then hand the
        # workflow prompt (docs-upgrade.md) to Claude with tasks embedded.
        TASKS="$(bash "$SKILL_DIR/scripts/daemon-cli.sh" docs-upgrade --format=skill "$@" 2>&1)"
        # shellcheck disable=SC2016
        awk -v tasks="$TASKS" '{gsub(/\$DOCS_UPGRADE_TASKS/, tasks)}1' \
            "$SKILL_DIR/docs-upgrade.md"
        ;;
````

The `daemon-cli.sh` wrapper resolves `$PYTHON` and forwards to
`python -m ...daemon.cli docs-upgrade` (the new CLI command). `--format=skill`
yields a compact, LLM-ready rendering of each applicable task (id, severity,
detect/handle/confirm). **No new script file is needed** beyond the existing
wrapper — only a new CLI subcommand + a `docs-upgrade.md` prompt doc.

---

## 3. Realistic `docs-upgrade.md` draft (the LLM workflow)

The crux of the lens: the skill must *make the LLM actually edit the files*,
confirm each task, and reassess across many versions. Draft:

```markdown
# Sync Project Docs With Daemon Upgrade

You upgraded the hooks daemon. Daemon BEHAVIOUR changed in ways that may make
YOUR project's own docs (CLAUDE/, docs/, README, AGENTS.md) inaccurate. Your job
is to bring those docs into line. **Do the edits — do not just describe them.**

## Applicable tasks

The daemon computed these tasks for the version range you crossed (newest
daemon version minus your last docs-synced marker). Each has a stable id, a
severity, and detect/handle/confirm steps:

$DOCS_UPGRADE_TASKS

If the block above says "No applicable tasks", tell the user docs are already in
sync and STOP — do not invent work.

## Procedure (per task, in id order)

For EACH task:

1. **DETECT** — Run the task's "How to detect" check against THIS project's
   files (grep the project's own CLAUDE/, docs/, README, AGENTS.md — never the
   daemon's `.claude/hooks-daemon/` internals). If the detect check finds
   nothing, the task does not apply here: record SKIPPED(not-applicable) and
   move on. Do not edit files the check did not flag.

2. **HANDLE** — For each file the detect step flagged, open it with `Read`,
   then make the MINIMAL `Edit` that satisfies the task. Stay within the lines
   the detect check identified. Do not rewrite whole files. Do not touch files
   outside this project (nothing under `.claude/hooks-daemon/`, no vendored
   copies of the daemon).

3. **CONFIRM** — Re-run the detect check. It MUST now report clean for the files
   you edited. If it still flags them, your edit was wrong — fix it, do not move
   on. Record DONE only after a clean re-check.

4. **RECORD** — Append one line to the run summary:
   `<task-id>  <DONE|SKIPPED(reason)|BLOCKED(reason)>  <files touched>`.

## Multi-version jumps

If the range spans several versions, tasks may overlap or supersede each other.
Process strictly in id order; a later task's CONFIRM check is authoritative. If
two tasks edit the same lines, apply the higher-version one and mark the earlier
SKIPPED(superseded). Reassess the WHOLE set — never stop after the first task.

## Finish

1. Print the run summary table (all tasks + status).
2. If you made edits, stage ONLY project doc files you changed (explicit
   `git add` of each path — never `git add .`, never daemon-owned paths) and
   commit: `docs: sync project docs to daemon vX.Y.Z (docs-upgrade)`.
3. Record the synced version so this run is not repeated:
   `$PYTHON -m claude_code_hooks_daemon.daemon.cli docs-upgrade --mark-synced`
4. Tell the user which tasks were DONE/SKIPPED/BLOCKED and that re-running
   `/hooks-daemon docs-upgrade` is now a no-op.

## Rules
- Edit project docs only. The daemon's own files are upstream; never edit them.
- Idempotent: a second run must find nothing (the marker + detect checks ensure
  this). If a second run still finds tasks, a CONFIRM was skipped — report it.
- When a detect check is ambiguous, prefer SKIPPED + a note to the user over an
  over-eager edit. Wrong edits to CLAUDE.md are worse than a missed one.
```

Frontmatter is inherited from the parent `hooks-daemon` SKILL.md (single skill).
`allowed-tools: Bash, Read, Write, Edit` already covers everything this flow
needs — no frontmatter change required.

---

## 4. How it confirms a task is done

The CONFIRM step is the key anti-hallucination mechanism. **Every task's
detect-check is re-used as its done-check** — this is why the task schema
(RESEARCH §A: `## How to detect if this applies` + `## How to confirm`) must be
*executable* (a grep/CLI invocation), not prose. The skill leans entirely on
"detect found it → edit → detect now clean". This makes idempotency structural:
once edited, detect returns empty, so a re-run records SKIPPED(not-applicable).
The `--mark-synced` marker is a fast-path so the common case ("already synced")
returns the empty set without re-running every detect check.

---

## 5. Interaction with bootstrap / `deploy_skills()` / scripts

- **No new bootstrap surface.** Because this is a subcommand routing through the
  existing `daemon-cli.sh` wrapper (which already self-bootstraps), there is no
  5th manifest artifact, no new RELEASING.md Step 14 verification loop. This is
  the single biggest argument for the subcommand choice.
- **Refresh-on-upgrade is automatic.** `deploy_skills()` does
  `rmtree + copytree` of the whole skill dir every upgrade (RESEARCH §C), so the
  new `docs-upgrade.md` and the router edit land in the project the moment the
  daemon is upgraded — exactly when they are needed. No separate deploy step.
- **One new file in the skill dir**: `docs-upgrade.md` (the prompt). Plus the
  two SKILL.md edits. Both copied for free by `deploy_skills()`.
- **One new CLI subcommand**: `docs-upgrade` in `daemon/cli.py` with
  `--from`, `--list`, `--format`, `--mark-synced` (sibling agents own its
  internals + the synced-version marker store). The skill only consumes it.
- **`.claude/skills/CLAUDE.md` single-source rule**: `docs-upgrade.md` links to
  the canonical task schema in `CLAUDE/UPGRADES/.../post-upgrade-tasks/README.md`
  rather than restating it.

---

## 6. Concrete run — the plan-number example (transcript sketch)

```
dev> /hooks-daemon docs-upgrade

(skill runs daemon-cli docs-upgrade --format=skill; splices tasks into prompt)

Claude> Daemon at v3.17.0; docs last synced at v3.11.0. 1 applicable task:

  [00112-plan-number-counter]  severity: recommended
   Detect: grep -rnE 'find +CLAUDE/Plan|ls +CLAUDE/Plan' <project>/CLAUDE <project>/docs
   Handle: state next plan number = git config --local hooksdaemon.latestPlanNumber + 1,
           bootstrapped from a folder scan only when the counter is unset.
   Confirm: re-run the detect grep → must be clean.

  Running detect…
  → CLAUDE/PlanWorkflow.md:412:  "next number: find CLAUDE/Plan -maxdepth 1 ..."
  → docs/PLAN_SYSTEM.md:88:      "scan CLAUDE/Plan/ for the highest number"

  Editing CLAUDE/PlanWorkflow.md (Read → Edit line 412)…
  Editing docs/PLAN_SYSTEM.md (Read → Edit line 88)…
  Re-running detect… clean. ✓

  Summary:
  | task                       | status | files                              |
  |----------------------------|--------|------------------------------------|
  | 00112-plan-number-counter  | DONE   | CLAUDE/PlanWorkflow.md, docs/PLAN_SYSTEM.md |

  Committing: "docs: sync project docs to daemon v3.17.0 (docs-upgrade)"
  Marking synced (v3.17.0). Re-running /hooks-daemon docs-upgrade is now a no-op.
```

A project that never had the stale idiom: detect finds nothing → task
SKIPPED(not-applicable) → marker still advanced → no spurious edits. That is the
idempotency / no-over-edit guarantee in action.

---

## 7. MVP vs full vision

**MVP (ship in this plan):**

- `docs-upgrade` subcommand row in SKILL.md router + the documented block.
- `docs-upgrade.md` prompt (procedure above).
- Consumes the new CLI command with `--format=skill`, `--list`, `--mark-synced`.
- Ships the single plan-number task (00112) end-to-end as the proof case.

**Full vision (later):**

- SessionStart advisory auto-suggests `/hooks-daemon docs-upgrade` when daemon
  version > synced marker (sibling-agent delivery channel).
- `--dry-run` that prints the diff it *would* make without editing.
- Per-task `Idempotent: no` handling (skill warns + requires user confirm before
  destructive doc rewrites).
- Project-handler-contributed tasks (a project ships its own docs-upgrade tasks).

---

## 8. Risks & maintenance cost

| Risk                                                            | Mitigation                                                                                                                                                               |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Skill edits the WRONG files (daemon internals, vendored copies) | Prompt forbids editing under `.claude/hooks-daemon/`; detect-checks are scoped to project `CLAUDE/`/`docs`. `daemon_location_guard` already blocks `cd` into daemon dir. |
| Over-eager edits (rewrites whole files)                         | Prompt mandates MINIMAL edits within detect-flagged lines; CONFIRM re-check is the only gate to DONE.                                                                    |
| Non-idempotent re-runs                                          | detect = confirm = same check; `--mark-synced` short-circuits. A second run that finds work is itself a reported anomaly.                                                |
| Task schema written as prose, not executable                    | Hard requirement: each task's detect/confirm MUST be a runnable grep/CLI line. Skill is useless without this — flag to schema owners.                                    |
| Skill drift on refresh                                          | Single skill dir, atomic `deploy_skills()` copytree — cannot drift from the router.                                                                                      |
| LLM declares DONE without editing                               | CONFIRM re-runs detect; can't be clean unless the edit landed.                                                                                                           |

**Maintenance cost: LOW.** No new bootstrap artifact, no new script, no new
release-flow verification loop. The skill is a prompt + one router case; all
real logic (task set, version range, marker) lives in the CLI command the
sibling agents design. Adding a future task is a content change in
`post-upgrade-tasks/`, not a skill change.

---

## Recommended MVP

1. **Subcommand, not new skill**: `/hooks-daemon docs-upgrade` — one `case` row
   in `SKILL.md` routing through the existing `daemon-cli.sh` wrapper. Zero new
   bootstrap surface, refreshed atomically by `deploy_skills()`.
2. **One new prompt file** `skills/hooks-daemon/docs-upgrade.md` implementing the
   detect → handle → confirm → record → commit → mark-synced loop, with explicit
   "edit project docs, never daemon files; minimal edits; CONFIRM gates DONE"
   rules.
3. **Consumes** the sibling CLI command via `docs-upgrade --format=skill`
   (task set), `--list`, `--mark-synced`.
4. **Proof case**: the plan-number (00112) task wired end-to-end, demonstrating a
   real project-doc edit + idempotent re-run.
5. Defer SessionStart auto-nudge, `--dry-run`, non-idempotent task handling to
   the full vision.

## Open questions for triage

1. **Format contract**: what exactly does `--format=skill` emit, and is it
   stable enough to splice into a prompt via `awk`? (Newlines, code fences inside
   the task body could break the `awk gsub` — may need a sentinel file instead of
   inline substitution, like `report.md` uses `sed`.)
2. **Marker location**: where does `--mark-synced` persist? Per-venv
   `.daemon-metadata.json` (RESEARCH §A) is venv-scoped; a *project*-scoped
   "docs-synced" marker (e.g. `.claude/hooks-daemon/untracked/docs-synced` or a
   git-config key like the plan counter) is arguably the right home. Skill must
   know which to read for the "already synced" fast path.
3. **Commit policy**: should the skill auto-commit doc edits, or leave them
   staged for the user? `upgrade.md` auto-commits; but doc edits are
   project-authored content — user may want to review. Lean toward auto-commit
   with a clear message + easy revert, matching upgrade ergonomics.
4. **Detect-check execution**: who runs the grep — the skill (Bash) or the CLI?
   If the CLI runs detect and only emits *applicable* tasks, the skill's job
   shrinks to handle+confirm. Cleaner, but couples the CLI to scanning project
   docs. Recommend CLI emits the *check command string* and the skill executes
   it, keeping the CLI free of project-filesystem assumptions.
5. **Should `--list` (read-only) be auto-invocable** (`disable-model-invocation`)
   while the editing path stays user-gated? Splitting invocability by subcommand
   isn't supported in current frontmatter — may need the read-only listing to be
   a separate CLI call the SessionStart advisory can surface without the skill.

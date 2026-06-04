# Plan 00118 — Final Triage

> ⚠️ **HISTORICAL — partially superseded.** This triage locked a heavy design
> (git-config docs-synced marker, staleness detection, `detect:` probes,
> supersede/severity metadata, QA validator, SessionStart push advisory). The
> user judged that over-engineered. **`PLAN.md` is the authoritative, simplified
> design**: a per-version `was → now` truth-changes list delivered through the
> existing upgrade flow (which already knows `from→to`), with no marker, no
> staleness detection, and no push channel. This document is retained as design
> history / rationale; read it for *why* the simpler choices are safe, not as the
> spec. §7 (delivery-channel revision) remains valid and motivated the cut.

Synthesis of `RESEARCH.md` + `ideation1.md` (CLI) + `ideation2.md` (skill) +
`ideation3.md` (delivery/push) + `ideation4.md` (authoring/content). This
document **resolves the open questions** and locks the architecture that
`PLAN.md` implements.

---

## 1. Where the four agents converged (accept as-is)

These were proposed independently by ≥2 agents and are mutually reinforcing.
They are **decided, not open**:

01. **Extend, do not fork, the `post-upgrade-tasks` schema.** Add a
    `Type: docs-update` discriminator and a fenced machine-readable `yaml`
    header block on top of the existing Why/Detect/Handle/Confirm/Rollback body.
    One schema, one release-move step, one reader. *(ideation 4, 1)*
02. **Static per-version task files are the source of truth — NOT a live handler
    hook.** Doc-migration tasks describe *historical, version-keyed deltas*,
    which a live handler instance cannot enumerate. `get_doc_upgrade_tasks()` is
    explicitly deferred to a future "applies-to-all" niche. *(ideation 1, 4)*
03. **Ship via the existing clone — zero new release/bootstrap surface.**
    `CLAUDE/UPGRADES/` is already physically on disk downstream inside the cloned
    `.claude/hooks-daemon/`, refreshed to the target tag on every upgrade, and is
    already how `config-migrations` resolves its manifests. The aggregator globs
    the cloned tree the same way `_default_manifests_dir()` does. *(ideation 4 —
    the load-bearing finding; 1)*
04. **The docs-synced marker is a git-config key**:
    `git config --local hooksdaemon.docsSyncedVersion`, via the existing
    `GitRepo.read_config`/`write_config` facade — mirroring Plan 00112's
    `hooksdaemon.latestPlanNumber`. Branch-stable, survives `git pull` and venv
    prune, per-repo resolution for nested repos, correct (coarse) isolation for a
    working-tree property. Beats a tracked file (branch-switch reverts, diff
    churn) and venv metadata (per-env, wiped on prune). *(ideation 3, 4 — both
    independently picked it; overrides ideation 1's tentative `.docs-synced`
    file)*
05. **Detection is the idempotency core**: each task carries a read-only,
    machine-runnable `detect:` probe whose **exit 0 = "task applies"**. Re-running
    after the fix yields a clean result even if the marker was never advanced.
    The marker is a UX fast-path; `detect:` is the correctness guarantee.
    *(ideation 1, 4)*
06. **Skill = a subcommand of the existing `hooks-daemon` skill router
    (`/hooks-daemon docs-upgrade`), NOT a new top-level skill.** Decisive reason:
    it routes through the existing self-bootstrapping `daemon-cli.sh` wrapper, so
    it adds **zero new `bootstrap-checksums.txt` artifacts** and **zero new
    RELEASING.md Step 14 verification loops**, and is refreshed atomically by
    `deploy_skills()`. `docs-upgrade` is conceptually a continuation of
    `upgrade`. *(ideation 2)*
07. **`get_claude_md()` stays stateless / present-tense.** Migration ("your old
    docs are wrong, change them") is transient, confirm-gated state that belongs
    in the CLI + SessionStart advisory, never in the always-on `<hooksdaemon>`
    block (which auto-commits on every restart and would go stale the instant
    docs are synced). The *current* policy ("next plan number comes from
    `hooksdaemon.latestPlanNumber`") DOES belong in the injector — so fixing
    `plan_number_helper.get_claude_md()` (returns `None` today) is the stateless
    half of the same fix and lands in this plan. *(ideation 3, 4)*
08. **The push channel is a SessionStart advisory** (`docs_sync_advisor`) modelled
    on `version_check`: new-sessions-only, 24h cache keyed on
    `(installed, synced)`, fires ONLY when `installed > synced` **AND** ≥1
    applicable task exists in range; emits a short `context` nudge pointing at the
    durable CLI/skill; `get_claude_md()` → None. Two-condition gate + cache +
    snooze + severity-floor kill nagging. *(ideation 3)*
09. **Marker advancement is confirm-gated, never on upgrade.** Advancing on
    upgrade would mark docs "synced" the instant they went stale → silent rot.
    Advance only (a) after the LLM runs the flow and confirms, or (b)
    auto-advance when the applicable set is *empty* (nothing to do). Bias toward
    under-advancing (re-nag is recoverable; silent skip is not). *(ideation 3)*
10. **Release-flow integration mirrors post-upgrade-tasks** (RELEASING.md Step 6
    move + a Step 7 anti-drift checklist line) plus a **QA validator** for the
    task schema. *(ideation 4)*

---

## 2. Resolved open questions (the genuine decisions)

| #   | Question (raised by)                                                                              | DECISION                                                                                                                                                                                                                  | Rationale                                                                                                                                                                                               |
| --- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Q1  | CLI command name: `check-docs-migrations` vs `docs-upgrade` (i1, i2, i3)                          | **`check-docs-migrations`** is the canonical CLI command (read/aggregate). Marker advance is `--mark-synced VERSION` on the same command. The *skill* is `/hooks-daemon docs-upgrade` and wraps it.                       | Maximises reuse of the proven `check-config-migrations` pattern (flags, exit codes, range loader). Skill name stays verb-like for humans; CLI name stays sibling-symmetric.                             |
| Q2  | Separate `doc-tasks/` dir vs `Type: docs-update` inside `post-upgrade-tasks/` (i4 Q1)             | **Separate `doc-tasks/` dir, shared schema.** Tasks live at `CLAUDE/UPGRADES/v{M}/v{P}-to-v{N}/doc-tasks/NN-*.md`.                                                                                                        | Clean machine glob boundary; keeps docs-sync aggregation from entangling with audit/severity post-upgrade tasks; still one schema doc.                                                                  |
| Q3  | Per-version YAML index (`docs-changes/v{X}.yaml`, i1) vs glob-and-parse the task `.md` files (i4) | **Glob `doc-tasks/**/*.md` and parse the fenced `yaml` header.** No separate index file.                                                                                                                                  | DRY: one self-describing file per task, no index to keep in sync. The fenced block is a strict lintable contract; parsing only that block is cheap and bounded.                                         |
| Q4  | `--applies-only` default on/off (i1 Q4)                                                           | **Default ON** (show only applicable tasks). `--all` opts into showing the full range incl. already-satisfied tasks.                                                                                                      | The LLM-friendly behaviour is "show me real work". Verbose/audit mode is the opt-in. (Departs from config-cmd parity deliberately — different use case.)                                                |
| Q5  | Unset-marker semantics (i3 Q2, i4)                                                                | **Unset ⇒ `0.0.0` (ancient) ⇒ offer all in-range tasks once, then advance.** Bounded because we **do NOT mass-back-fill** (Q6).                                                                                           | An unmarked repo is maximally suspect. With only the plan-number task authored, "ancient" is a 1-task wall, not a flood.                                                                                |
| Q6  | Back-fill historical doc-tasks (i4 Q4)                                                            | **No mass back-fill.** Start fresh: author **only** the plan-number task (`introduced_in: 3.12.0`). Future doc-affecting changes author their own task going forward.                                                     | Back-fill is high-effort, low-marginal-value, and risks a task flood on first run. The plan-number task is the proof case and the highest-value single fix.                                             |
| Q7  | Who runs `detect:` — CLI auto-run vs only show to LLM (i2 Q4, i4 Q3)                              | **CLI auto-runs** each `detect:` snippet read-only with a timeout; non-zero/timeout/error ⇒ "does not apply" (fail-safe silent). The CLI emits the snippet text too, so the skill/LLM can re-run it as the CONFIRM check. | Auto-run is what makes `--applies-only` and the advisory's "≥1 applicable" gate real. Snippets are **daemon-authored**, read-only grep — safe to run. The LLM still gets the text for the confirm loop. |
| Q8  | `--format=skill` splice contract (i2 Q1)                                                          | The skill writes the CLI output to a **temp file** and the prompt `@`-references / cats it, rather than `awk gsub` inline substitution.                                                                                   | Task bodies contain newlines and code fences that break inline `awk` substitution. The `report.md` file-based pattern is the safe precedent.                                                            |
| Q9  | Commit policy for doc edits (i2 Q3)                                                               | **Auto-commit** with a clear message (`docs: sync project docs to daemon vX.Y.Z (docs-upgrade)`) + explicit per-file `git add`, matching `upgrade.md` ergonomics; easy to revert.                                         | Consistency with the existing upgrade flow; the message + single-purpose commit make review/revert trivial.                                                                                             |
| Q10 | Should fixing `plan_number_helper.get_claude_md()` be in-scope (i4 Q5)                            | **Yes — in scope, same plan.** The injected current-policy and the downstream doc-task are two faces of one fix and must tell the same story.                                                                             | Avoids shipping a doc-task that says "use the counter" while the daemon's own injected guidance still says nothing.                                                                                     |
| Q11 | In-process aggregator vs shell-out for the SessionStart gate (i3 Q1)                              | **In-process**: the advisory imports the same aggregator module the CLI uses and asks "≥1 applicable in range?".                                                                                                          | Cheaper at SessionStart than spawning a subprocess; single source of aggregation logic.                                                                                                                 |
| Q12 | `git clone` of a project has no `.git/config` marker (i3 Q5)                                      | **Accept the one harmless nudge.** A fresh clone → unset → "ancient" → one nudge; if the committed docs are already current, every `detect:` returns "does not apply" ⇒ empty set ⇒ auto-advance ⇒ silent thereafter.     | No tracked fallback needed; the `detect:` layer makes the false nudge self-healing on the first session.                                                                                                |

---

## 3. Locked architecture (what PLAN.md builds)

```
AUTHORING (this repo, release-time)
  CLAUDE/UPGRADES/UNRELEASED/doc-tasks/NN-*.md      <- staged during dev cycle
        │  (RELEASING.md Step 6 move, extended)
        ▼
  CLAUDE/UPGRADES/v{M}/v{P}-to-v{N}/doc-tasks/NN-*.md
        - fenced yaml header: id, type:docs-update, severity, introduced_in,
          applies_to (semver range), idempotent, targets[], detect:(sh), supersedes[]
        - markdown body: Why / How to detect / How to handle / How to confirm / Rollback

SHIPPING  (no new mechanism)
  Already on disk downstream in .claude/hooks-daemon/CLAUDE/UPGRADES/... (the clone)

AGGREGATION  (new module: install/docs_migrations.py, sibling of config_migrations.py)
  load_doc_tasks_between(from, to) -> glob doc-tasks/**/*.md, parse yaml headers,
    filter by applies_to ∋ from, run detect: probes (timeout, fail-safe), drop
    superseded ids, order by (severity, introduced_in, id)

MARKER  (new util: docs_sync_marker.py, wraps GitRepo)
  git config --local hooksdaemon.docsSyncedVersion   (unset ⇒ 0.0.0)
  seeded to installed version on FRESH install only (gated on unset)
  advanced only on confirm or empty-set

PULL / CLI  (new: cmd_check_docs_migrations in daemon/cli.py)
  check-docs-migrations [--from V] [--to V] [--format text|json] [--applies-only(default)|--all]
                        [--severity-min recommended] [--mark-synced V] [--snooze 7d]
  exit 0 = nothing applies, 1 = tasks present, 2 = error

SKILL  (subcommand of existing hooks-daemon skill)
  /hooks-daemon docs-upgrade  -> router calls daemon-cli.sh check-docs-migrations,
    writes output to temp file, hands docs-upgrade.md prompt to the LLM:
    per task: DETECT -> HANDLE (minimal Edit, project docs only) -> CONFIRM
    (re-run detect) -> RECORD -> commit -> --mark-synced

PUSH  (new SessionStart advisory: docs_sync_advisor, priority ~58)
  fires when installed > synced AND aggregator reports >=1 applicable task;
  short context nudge -> points at /hooks-daemon docs-upgrade; get_claude_md() None;
  24h cache, snooze, severity-floor; auto-advance + silent on empty set

CURRENT-POLICY FIX  (stateless half)
  plan_number_helper.get_claude_md(): None -> markdown stating the git-anchored
  counter is authoritative (present-tense policy in the <hooksdaemon> block)

GOVERNANCE
  RELEASING.md Step 6 (move doc-tasks) + Step 7 (anti-drift checklist line)
  QA validator scripts/qa/... : yaml parseable, required fields, semver range
  valid, detect: passes `sh -n`, ids unique, supersedes resolve
```

---

## 4. Phasing (drives PLAN.md task breakdown)

Dependency-ordered. Phases 1–4 are the MVP (the user's explicit asks: per-version
CLI rediscovery + skill + the plan-number fix). Phases 5–6 complete the vision.

- **Phase 1 — Schema + first task + marker util.** Extend the task schema doc,
  author `doc-tasks/.../01-plan-number-git-counter.md`, build `docs_sync_marker.py`
  (+ tests). Fix `plan_number_helper.get_claude_md()` (stateless policy).
- **Phase 2 — Aggregator.** `install/docs_migrations.py` cloning the
  `config_migrations.py` structure: glob, parse fenced yaml, semver-range filter,
  `detect:` runner (timeout, fail-safe), supersede-drop, ordering (+ tests).
- **Phase 3 — CLI command.** `cmd_check_docs_migrations` with all flags, exit
  codes, text/json formats, `--mark-synced`; `CliAcceptanceTest` proving the
  plan-number task surfaces for `--from 3.11.0` (+ tests).
- **Phase 4 — Skill subcommand.** Router case in `hooks-daemon/SKILL.md` +
  `docs-upgrade.md` prompt (detect→handle→confirm→record→commit→mark-synced),
  temp-file splice. No new bootstrap artifact.
- **Phase 5 — Push advisory.** `docs_sync_advisor` SessionStart handler + installer
  marker-seeding (fresh-install, gated-on-unset) + config entry + docs (+ tests).
- **Phase 6 — Governance.** RELEASING.md Step 6/7 edits; QA validator for
  doc-task files wired into `run_all.sh` / `llm_qa.py`; regenerate
  `HOOKS-DAEMON.md`; update changelog.

**Likely a MINOR release** (new handler, new CLI command, new skill subcommand,
new config option — all backwards-compatible).

---

## 5. Risks carried into the plan

- **Tasks never authored** (the perennial post-upgrade-tasks failure mode). The
  whole mechanism is inert without authored tasks. Mitigation: RELEASING.md
  Step 7 checklist gate + make authoring one task cheap (one grep + one
  paragraph) + the QA validator as a mechanical reminder.
- **Aggregator must read the shipped clone correctly in both self-install and
  normal installs** — verify the `Path(__file__).parents[...]` resolution matches
  `config_migrations.py` in both modes.
- **Over-advancing the marker** = silent doc-rot (cardinal risk). Confirm-gating
  - "empty-set only" auto-advance + under-advance bias.
- **Self-install path labelling**: in this repo, the "project" IS the daemon, so
  the plan-number task's `detect:`/targets resolve against this repo's own
  `CLAUDE/` — correct, but the skill prompt must not edit `.claude/hooks-daemon/`
  internals in downstream projects (`daemon_location_guard` already blocks `cd`).

---

## 6. Explicitly deferred (NOT in this plan)

- `Handler.get_doc_upgrade_tasks()` live-hook for version-agnostic checks.
- `--dry-run` diff preview; per-task partial-sync state; non-idempotent task
  confirmation UX.
- Status-line "📝N docs-behind" glyph.
- Mass back-fill of historical doc-tasks.
- Combining `version_check` + `docs_sync_advisor` into one message.

---

## 7. Delivery-channel revision (post-review, 2026-06-04)

**Trigger**: User observation, corroborated by direct introspection — SessionStart
messages are almost completely ignored. The agent could not recall any content
from its own SessionStart injection, whereas UserPromptSubmit context (git status,
POST-CLEAR notice) and PreToolUse blocks (`plan_number_helper`, `pipe_blocker`)
land reliably and change behaviour immediately within the same session.

**This invalidates the ideation #3 premise** that a SessionStart advisory
(`docs_sync_advisor`, modelled on `version_check`) is an effective push channel.
`version_check` is itself a SessionStart advisory and is therefore likely ignored
for the same reason — the new handler inherited a pattern that does not land.

**Observed channel stickiness (this session, evidence-based ranking)**:

| Channel                               | Lands?             | Why                                                                         |
| ------------------------------------- | ------------------ | --------------------------------------------------------------------------- |
| PreToolUse deny (action interception) | **Yes, strongest** | Stops the action; forces correction; perfectly recalled                     |
| UserPromptSubmit additionalContext    | Yes                | Re-injected every turn; reliably seen                                       |
| `get_claude_md()` / CLAUDE.md block   | Partly             | Always-on policy, but "wallpaper"                                           |
| PostToolUse advisory                  | No                 | The `✅` lines repeat constantly and are tuned out — repetition ≠ attention |
| SessionStart additionalContext        | **No, weakest**    | Injected once, positionally buried, compacted away                          |

**Key principle**: stickiness comes from **interrupting the relevant action at the
decision moment**, not from frequency. Claude Code's own designers route the
"act now" POST-CLEAR signal through UserPromptSubmit, not SessionStart —
corroborating evidence.

**Revised decision (supersedes §1.8 and Q11's delivery assumption)**: the push
channel is built on action interception, in priority order:

1. **Rider on existing interceptions** — when a handler already blocks/advises an
   action whose guidance a doc-task covers (`plan_number_helper` blocking a
   folder-scan), append the "your docs are stale → `/hooks-daemon docs-upgrade`"
   pointer. The block is the delivery.
2. **`docs_staleness_advisor` PreToolUse** — non-blocking advice when the agent
   `Edit`/`Write`s a file a doc-task's `detect:` flags as stale (teachable moment).
3. **Once-per-session UserPromptSubmit** line (home alongside `post_clear_auto_execute`,
   prio ~54), cached to fire once — NOT SessionStart.

The git-config marker, aggregator, and confirm-gating (§1.4, §1.5, §1.9) are
unchanged — only the delivery surface moved. The `docs_sync_advisor` SessionStart
handler is **dropped**; SessionStart is demoted to optional/cosmetic. PLAN.md
Phase 5 is rewritten accordingly.

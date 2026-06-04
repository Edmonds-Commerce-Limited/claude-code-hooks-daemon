# Plan 00118 — Ideation #3: Delivery, Staleness Detection & the Nudge Channel

**Lens**: PUSH. The CLI/skill (ideation #1/#2) is pull-based — the human or LLM
must *think to run it*. This lens designs the half that makes the project LLM
*get told* "your docs are stale, run the docs-upgrade flow" with zero human
memory required. Three parts: (A) the persisted marker, (B) the SessionStart
advisory that reads it, (C) the discipline that advances it.

The whole nudge is worthless if it nags (LLMs and humans both learn to ignore a
handler that fires every session saying nothing actionable) or if it advances
silently (docs never get updated, but the marker says they're current). Both
failure modes are designed against below.

---

## A. The docs-synced marker — use git config, not a file

RESEARCH.md flags this as the one thing that does not exist. I argue strongly:
**store it in `.git/config` via the existing `GitRepo.read_config` /
`write_config` facade** — the exact mechanism Plan 00112 chose for
`hooksdaemon.latestPlanNumber`. New key:

```
git config --local hooksdaemon.docsSyncedVersion   # e.g. "3.17.0"
```

Optionally a companion timestamp `hooksdaemon.docsSyncedAt` (ISO) for the status
line / audit, but the version string is the load-bearing value.

### Why git config beats the alternatives

| Option                                        | Verdict    | Reason                                                                                                                                                                                                                                                                                                           |
| --------------------------------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.git/config` local key                       | **CHOSEN** | Per-repo, **stable across branch switches** (not a tracked file, so checking out an old branch doesn't resurrect a stale marker), survives `git pull`, already has a tested read/write facade, already the precedent for plan counter.                                                                           |
| Tracked project file (`CLAUDE/.docs-synced`)  | Rejected   | Branch-switch hell: switch to a year-old feature branch and the marker reverts; merge conflicts on a machine-generated value; pollutes diffs.                                                                                                                                                                    |
| `.daemon-metadata.json` (per-venv)            | Rejected   | Lives *inside the fingerprint-keyed venv*. It tracks the **installed** version, which is exactly what we compare *against* — co-locating the "docs-synced" value there conflates "what's installed" with "what docs reflect". Also wiped on venv rebuild/prune, so the marker would reset spuriously and re-nag. |
| Untracked file (`untracked/docs-synced.json`) | Rejected   | Not branch-stable, not shared, easy to .gitignore-clobber.                                                                                                                                                                                                                                                       |

### Multi-container / hostname isolation

This is a real concern the lens demands I address. `.daemon-metadata.json` is
**per-venv (fingerprint-keyed)** and daemon runtime files are **per-hostname**.
The docs-synced marker is deliberately **neither** — docs are a property of the
*repository working tree*, which is shared across every container that mounts it.
Two containers sharing a bind-mounted repo SHOULD see one docs-synced value and
nudge once, not race. `.git/config --local` gives exactly that: one value per
repo, visible to every container, written through git's own locking. This is the
correct isolation level — coarser than venv/hostname on purpose. (A nested/vendor
repo resolves its *own* `.git/config` via `GitRepo.resolve_for`, mirroring the
plan-counter's per-repo resolution — free correctness.)

### Who writes it, and the bootstrap problem

- **Installer (`install_version.sh`)**: on a *fresh* install, seed
  `docsSyncedVersion = <installed version>` immediately. A brand-new project has
  no legacy docs to fix, so it starts synced. **Critical**: this seeding must be
  gated on "key unset" — never overwrite an existing marker on reinstall.
- **Upgrade (`upgrade.sh`)**: does **NOT** advance the marker (see §E). Upgrade
  changes the *installed* version; the marker stays where it was so staleness is
  detected.
- **The docs-upgrade flow itself** (CLI/skill): advances the marker, but **only
  after the LLM confirms tasks are done** (§E).
- **Bootstrap for existing installs that predate this plan**: the key will be
  unset. The handler treats "unset marker" as **"synced as of the version where
  this plan shipped minus one"** — i.e. unset ⇒ assume the oldest version that
  has applicable doc-tasks, so the very first session after upgrading surfaces
  everything. Concretely: unset ⇒ run the full applicable-task scan from the
  earliest task version. This is the right default: an unmarked repo is
  maximally suspect, not minimally.

---

## B. New SessionStart advisory handler: `docs_sync_advisor`

Modelled directly on `version_check` + `hook_registration_checker` (priority
band 56–59, terminal `False`, `Decision.ALLOW`, emits `context`).

```python
class DocsSyncAdvisorHandler(Handler):
    # priority=Priority.DOCS_SYNC_ADVISOR  (e.g. 58)
    # tags=[WORKFLOW, ADVISORY, NON_TERMINAL]
```

### When it fires

- `hook_event_name == "SessionStart"` AND **new session only** — reuse
  `version_check`'s `_is_resume_session()` transcript-size check verbatim. Resumes
  never nag.
- Behind a 24h cache file in `daemon_untracked_dir()` (same pattern as
  `version_check_cache.json`). The expensive part isn't git config (cheap) — it's
  *re-emitting the same nudge every new session in a busy day*. Cache key =
  `(installed_version, docs_synced_version)`; if that pair is unchanged and we
  already nudged within TTL, stay silent. The moment the LLM advances the marker
  the pair changes and the cache naturally invalidates.

### How it detects staleness (the gate)

Three conditions, **all** required to emit:

1. `installed_version > docs_synced_version` (semver compare, reuse
   `version_check._compare_versions`), OR marker unset (treat as "very old").
2. **Applicable doc-tasks actually exist** for the version range
   `(docs_synced, installed]`. This is the false-positive killer: a patch release
   with no doc-tasks must NOT nudge. The handler asks the same aggregator the CLI
   uses (ideation #1/#2's `generate`/`list` over the shipped task set) "are there
   ≥1 doc-relevant tasks in this range?" — if zero, emit nothing and **advance the
   marker to installed** (auto-sync: nothing to do = synced). See §E nuance.
3. Not snoozed (see staleness-control below).

### What `context` it emits

Short, status-line + pointer to the *durable* surface (the CLI/skill), never the
full task list inline — the inline message scrolls away; the CLI is the
rediscoverable channel (requirement #2). Example:

```
📝 Hooks-daemon docs may be stale: docs synced at v3.11.0, daemon now v3.17.0.
   3 doc-update task(s) span this range (e.g. plan-number docs → git counter).
   Run:  /hooks-daemon docs-upgrade            (review & apply guidance)
   Or:   $PYTHON -m ...daemon.cli docs-upgrade-tasks --from v3.11.0
   This notice repeats once/day until docs are synced (marker advances on confirm).
```

The "e.g." line is the **single highest-severity task title** pulled from the
aggregator, so the nudge is concrete, not generic.

### `get_claude_md()` — return None

The handler should return `None`. Its guidance is *transient and stateful*
("you're N versions behind") — it does not belong in the always-on
`<hooksdaemon>` CLAUDE.md block, which is the wrong place for time-varying state
(it'd churn the auto-commit on every marker change and go stale the instant docs
are synced). The handler's whole job is the `context` push + pointing at the CLI.
See §D for the broader argument.

---

## C. Anti-nag / staleness-control mechanics

Five layers, cheapest first:

1. **New sessions only** — resumes are silent (transcript check).
2. **24h cache** keyed on `(installed, docs_synced)` — at most one nudge/day for a
   given un-synced state.
3. **Zero-applicable-tasks ⇒ silent + auto-advance** — a doc-irrelevant upgrade
   never produces a nudge AND clears the staleness so later sessions are clean.
4. **Snooze escape hatch**: `git config hooksdaemon.docsSyncSnoozeUntil <iso>` (or
   a CLI `docs-upgrade-tasks --snooze 7d`). Handler suppresses while now < snooze.
   For the LLM/human who genuinely wants to defer. Snooze is per-repo, branch-
   stable, same as the marker.
5. **Config kill-switch**: `enabled: false` and a `min_severity` option
   (`recommended` default) so `optional` doc-tasks never nag — only `recommended`
   /`critical` ones do.

**Idempotency**: every read is side-effect-free except the auto-advance in (3),
which is itself idempotent (advancing a marker that's already at `installed` is a
no-op). Running the CLI twice yields the same task set. Re-restarting the daemon
doesn't double-nudge (cache survives restart in untracked dir).

---

## D. Should `claude_md_injector` carry per-version "change YOUR docs" tasks?

**No. Keep `get_claude_md()` injection stateless / current-state-only.** Argued:

- The `<hooksdaemon>` block is **declarative present-tense policy** ("sed is
  blocked", "use absolute paths"). It is regenerated wholesale and auto-committed
  on every restart. Injecting per-version migration tasks there would: (a) churn
  the auto-commit constantly as the marker moves, (b) immediately go *stale and
  wrong* the moment docs are synced (the block would still say "update your
  plan-number docs" after you already did), (c) mix transient migration state into
  durable policy — a Single-Responsibility violation.
- Migration tasks are **stateful, time-bounded, and confirm-gated**. That is the
  SessionStart-advisory + CLI's job, not the always-on injector's.
- There IS a legitimate injector role: once `plan_number_helper` finally
  implements `get_claude_md()` (the motivating bug — it returns `None` today),
  the *current* policy "next plan number comes from `hooksdaemon.latestPlanNumber`"
  belongs in the injected block. That's stateless present-tense and correct
  forever. The *migration* ("your old docs say folder-scan, fix them") is the
  advisory's job. **Clean split: injector = what's true now; advisor = what you
  must change to catch up.**

---

## E. Advancing the marker — confirm-gated, never on upgrade

This is the riskiest design point. The temptation is to advance the marker on
upgrade (it's automatic, no LLM cooperation needed). **That is exactly wrong** —
it would mark docs "synced" the instant they became stale, and the doc-update
would silently never happen. The whole point is to keep the marker *behind* the
installed version until work is confirmed done.

### Three advance triggers, by trust level

1. **Confirmed-done (primary path)**: the docs-upgrade CLI/skill, after the LLM
   has been shown the tasks and reports completion, writes
   `docsSyncedVersion = installed`. The flow MUST require positive confirmation —
   ideally per-task checkboxes the LLM ticks, then `--mark-synced`. The skill's
   final step calls a CLI `docs-upgrade-tasks --mark-synced <version>`.
2. **Auto-advance on empty (safe)**: when the applicable-task set for the range is
   *empty*, advance freely — there was nothing to do. This prevents permanent
   nagging on doc-irrelevant patch releases.
3. **Manual override (escape hatch)**: `--mark-synced --force` for a human who
   audited docs by hand. Logged.

### The risk of advancing too early — and the mitigation

If the marker advances before docs are actually fixed, the nudge disappears and
the stale docs persist invisibly — the worst outcome (silent skip). Mitigations:

- **Never** advance on upgrade or install-over-existing.
- The confirm path should advance to `installed` **only**, and only when the LLM
  ran the flow this session. A `--mark-synced` with no preceding `list`/`generate`
  in the same flow is suspicious; the skill encodes the order.
- Make under-advancing the safe failure: if in doubt, *don't* advance — a repeated
  nudge is annoying but recoverable; a skipped doc-update is silent rot. Bias the
  whole mechanism toward "nudge again next session" over "assume done".

---

## F. The plan-number example, end to end

1. Project upgraded daemon from v3.11.0 → v3.17.0. `upgrade.sh` does NOT touch the
   marker. `.git/config` still has `docsSyncedVersion = 3.11.0` (or unset on a
   pre-00118 install → treated as ancient).
2. Next **new** session: `docs_sync_advisor` fires. Gate: `3.17.0 > 3.11.0` ✓;
   aggregator reports ≥1 doc-task in `(3.11.0, 3.17.0]` — including the Plan 00112
   "plan-number docs → git counter" task ✓; not snoozed ✓. Emits the `context`
   nudge naming that task, pointing at `/hooks-daemon docs-upgrade`.
3. LLM (or human) runs `/hooks-daemon docs-upgrade`. The skill calls the CLI
   aggregator, prints the full per-version task list (ideation #1/#2 surface):
   "Update `<project>/CLAUDE/PlanWorkflow.md` to state next number =
   `git config --local hooksdaemon.latestPlanNumber` + 1, bootstrapped from scan
   when unset." LLM edits the project's PlanWorkflow.md.
4. LLM confirms done → skill runs `...cli docs-upgrade-tasks --mark-synced 3.17.0`
   → `.git/config docsSyncedVersion = 3.17.0`.
5. Cache pair `(3.17.0, 3.17.0)` now equal → next session: gate condition (1)
   false → **silent**. No more nag. Branch-switch safe (value in `.git/config`).
   Second container on the same mounted repo also sees `3.17.0` → silent.

---

## G. MVP vs full vision

**Full vision**: per-task confirmation tracking (which of the N tasks are done,
partial-sync markers), severity-filtered nudges, snooze, status-line glyph
("📝 docs N behind"), multi-version aggregation across major boundaries, and the
injector finally carrying the plan-counter policy.

**Maintenance cost**: low-to-moderate. The marker read/write is ~15 lines reusing
`GitRepo`. The handler is a near-clone of `version_check` (~150 lines, mostly
copy-adapt of cache + resume logic). The ongoing cost is **authoring discipline**:
every release that changes project-facing docs MUST add a task file with an
`Applies to` range and a `doc-update` type — otherwise the aggregator finds
nothing and the nudge never fires. That discipline belongs in RELEASING.md as a
gate (this lens recommends adding it).

**Risks**:

- Aggregator must ship the task set downstream (RESEARCH.md gap E) — if tasks stay
  in the daemon's own `CLAUDE/UPGRADES/`, the handler has nothing to count. The
  marker+advisor are inert without ideation #1/#2's "ship tasks downstream" work.
- Marker drift if multiple writers race — mitigated by git's config locking.
- Over-advancing (§E) is the cardinal risk; mitigated by confirm-gating.

---

## Recommended MVP

1. `hooksdaemon.docsSyncedVersion` git-config key + a `plan_numbering`-style util
   module (`docs_sync_marker.py`) wrapping `GitRepo.read_config`/`write_config`,
   with unset ⇒ "ancient" semantics. ~40 lines + tests.
2. Installer seeds the marker to installed-version **only when unset** (fresh
   install starts synced). Upgrade does NOT touch it.
3. `docs_sync_advisor` SessionStart handler: new-session-only, 24h cache keyed on
   `(installed, synced)`, fires only when `installed > synced` AND aggregator
   reports ≥1 applicable doc-task; emits a short `context` nudge pointing at the
   CLI/skill; `get_claude_md()` → None. Auto-advances + stays silent when zero
   applicable tasks.
4. CLI `docs-upgrade-tasks --mark-synced <version>` to advance the marker (called
   by the skill after confirmation). `--snooze` and `--force` as fast-follows.

This MVP delivers the PUSH channel and is the minimal glue that makes
ideation #1/#2's pull-based CLI *discoverable without human memory*. It depends on
their "ship task set downstream + aggregator" work to have anything to count.

## Open questions for triage

1. **Where does the aggregator live and does it run in-process?** The handler
   must cheaply answer "≥1 applicable doc-task in range?" at SessionStart. Reuse
   the `generate-playbook`-style in-process aggregation, or shell out to the CLI?
   In-process is faster but couples the handler to the task-shipping mechanism.
2. **Unset-marker default**: treat as "ancient" (nudge everything) vs "synced now"
   (silent). I argue ancient; but on a huge multi-major backlog that could be a
   wall of tasks on first session. Snooze mitigates — confirm with triage.
3. **Per-task vs whole-range marker**: MVP uses one version marker (all-or-
   nothing). Do we need partial-sync (LLM did 2 of 3 tasks)? Adds real state;
   probably YAGNI for v1.
4. **Status-line glyph**: worth a Status handler showing "📝N" docs-behind, or is
   the SessionStart nudge enough? Lean: defer.
5. **Marker on `git clone` of a project**: `.git/config --local` is NOT cloned
   (it's per-clone). A fresh clone of a project has no marker → "ancient" → nudges
   on first session even though the *committed docs* may be current. Is that
   acceptable (one harmless nudge + auto-advance if no tasks) or do we need a
   tracked fallback hint? Triage.
6. **Interaction with `version_check`**: both fire at SessionStart in the same
   band. Should they coordinate (one combined "you're behind on code AND docs"
   message) or stay independent? Independent is simpler; combined is less noisy.

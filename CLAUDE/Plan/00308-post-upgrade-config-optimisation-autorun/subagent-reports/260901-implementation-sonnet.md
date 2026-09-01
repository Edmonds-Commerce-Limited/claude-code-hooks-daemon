agent: sonnet
plan: 00308-post-upgrade-config-optimisation-autorun

# Task 1.1 — Audit findings

Surfaces a project can learn about handler configuration today, and the gap
each one leaves:

- `.claude/skills/optimise` — full five-area scored analysis + apply. This
  IS the analysis engine; the only gap was that nothing *invoked* it
  automatically, and it had no concept of "what's new since I last ran".
- `.claude/skills/configure` — targeted single-handler get/set. No project-wide
  review; correctly stays out of scope for this plan (Non-Goal: don't fork
  `optimise`'s analysis).
- `CLAUDE/LLM-INSTALL.md` — a "Post-Installation: Handler Status Report
  (MANDATORY)" section existed, but it only ran `hooks-daemon handlers` (a
  raw enabled/disabled listing) and asked the human to eyeball it — no
  recommendation engine, no per-project profiling. Never pointed at `/optimise`.
- `CLAUDE/LLM-UPDATE.md` — a "What to Do with New Handlers (CRITICAL)" section
  duplicated a *manual* 5-step enable/verify walkthrough (category table,
  hand-edit YAML, restart, grep for "enabled") that fully re-implemented, in
  prose, what `/optimise` already does in code — and still never invoked it.
  This is the exact gap the owner's recurring prompt was covering by hand.
- Upgrade scripts (`scripts/upgrade.sh`, `scripts/upgrade_version.sh`) — the
  final printed summary told the user to restart Claude Code, and nothing
  else. No mention of a configuration review at all.
- `src/claude_code_hooks_daemon/skills/hooks-daemon/upgrade.md` (the actual
  `/hooks-daemon upgrade` agent workflow, 7 numbered steps) — step 5 already
  runs `check-config-migrations` (surfaces newly-available/recommended config
  *keys* from the manifests) but stopped at "adopt if useful" — no step ever
  ran the full per-handler review or applied anything.
- `UPGRADES/config-changes/*.yaml` manifests — rich, structured, versioned
  `added`/`changed`/`removed` handler/config entries with `recommended`/
  `dormant` flags. Consumed today only by `check-config-migrations` (a diff
  report) — never cross-referenced against what `/optimise` recommends, so a
  new handler's existence and its recommendation were two disconnected facts.
- `project_handler_load_checker` (SessionStart) — alerts when project
  handlers fail to *load*. Orthogonal: nothing to do with disabled-by-default
  vendored handlers or stale config review.
- `tool_disable_advisor` (SessionStart) — checks `tool_policy.never_want`
  against Claude Code's own settings. Also orthogonal to handler config review.

**The gap in one line**: `/optimise` was a complete, unused engine — no
automatic trigger existed anywhere in the install/upgrade lifecycle, so it
only ran when the owner remembered to prompt for it by hand, verbatim, every
time.

# Task 2.1 — Mechanism decision

**Decision: promote `/optimise`, do not fork or create a parallel
`config-optimisation` subcommand.** Rationale: the plan's own Non-Goal
forbids re-implementing the five-area analysis; `/optimise` already had it,
plus an apply path (Task 2.2 was already satisfied structurally — "apply
all"/"apply N,M"/"skip" with confirmation gating, no silent writes). The
smallest faithful mechanism was:

1. Add a **Step 0** to `.claude/skills/optimise/invoke.sh`: read the last
   recorded config-optimisation run version (new state file, see below),
   scan `CLAUDE/UPGRADES/config-changes/v*.yaml` manifests newer than that
   version, and fold `added` entries naming a `handlers.<event>.<name>` key
   into the Step 5 recommendation list, tagged "New since vN" — this is the
   "use UPGRADES/ manifests to surface what's new" requirement from Task 2.1.
2. Add a **Step 7** (record the run) that always calls a new CLI subcommand
   `record-config-optimisation-run` regardless of apply/skip — the review
   itself is what's being tracked, not whether changes were applied.
3. Reframe SKILL.md/invoke.sh header text: `/optimise` IS the canonical
   config-optimisation step, explicitly cross-referenced to Plan 00308.

No new `/hooks-daemon config-optimisation` alias was added — one command,
one name, avoids a "which one is canonical" ambiguity for future readers.

# Task 3.2 — Session-start reinforcement mechanism

New SessionStart handler `config_optimisation_reminder`
(`src/claude_code_hooks_daemon/handlers/session_start/config_optimisation_reminder.py`,
priority 67) rather than extending `project_handler_load_checker` or
`tool_disable_advisor` — both audit a semantically different thing (load
failures / tool policy vs. config-review staleness), and the existing
`skill_opportunity_detector` module already established the exact TTL/state-
file pattern this needed (state module + `_state_dir()` seam + try/except
degrade-to-silence). Copied that shape rather than inventing a new one.

State: `src/claude_code_hooks_daemon/config_optimisation/state.py` —
JSON sidecar `config_optimisation_state.json` under the daemon untracked dir
(`{project}/untracked/` self-install, `{project}/.claude/hooks-daemon/untracked/`
normal install — same directory `version_check_cache.json` already uses).
Corrupt/missing = "never run" (fails toward reminding). Written only by the
new `record-config-optimisation-run` CLI subcommand
(`src/claude_code_hooks_daemon/daemon/cli.py::cmd_record_config_optimisation_run`),
called by the `/optimise` skill's closing step — this keeps the state schema
single-sourced in Python rather than the skill's bash prelude hand-writing
JSON matching an implicit contract.

Handler fires (advisory only, never blocks) when `state.last_run_version != __version__` — covers both "never run" and "upgraded since last run".
Fail-open: any exception during the file-stat work degrades to silence
(mirrors `skill_opportunity_detector`'s contract exactly).

# Task 3.1 / 3.3 — Wiring

- `src/claude_code_hooks_daemon/skills/hooks-daemon/upgrade.md` (the actual
  `/hooks-daemon upgrade` agent-workflow doc — NOT a skill-marketplace file
  outside this repo, it ships from `src/claude_code_hooks_daemon/skills/`)
  gained a numbered **Step 8**: run `/optimise` after the upgrade commit,
  mandatory unless `--skip-config-optimisation` was passed.
- `scripts/upgrade.sh` (Layer 1, curl-fetched) now accepts
  `--skip-config-optimisation`, forwards it to Layer 2 via `UPGRADE_FLAGS`
  (an env-var forwarding channel that already existed for `--force`, just
  unused until now — same convention, not a new one).
- `scripts/upgrade_version.sh` (Layer 2) prints a mandatory-next-step banner
  naming `/optimise` at the end of every successful upgrade, or an
  opt-out acknowledgement if the flag was forwarded.
- `CLAUDE/LLM-UPDATE.md`: replaced the manual 5-step "What to Do with New
  Handlers" walkthrough with a single numbered mandatory step pointing at
  `/optimise` (DRY — the walkthrough is now owned entirely by the skill).
- `CLAUDE/LLM-INSTALL.md`: added a "Post-Installation: Run the
  Config-Optimisation Review (MANDATORY)" section, pointing at `/optimise`,
  positioned before Planning Workflow Setup so it decides that section's
  handlers too.

# Task 4.1 — Dogfood

Ran the audit trail (Step 0/1/3 logic) by hand against this repo's own
`.claude/hooks-daemon.yaml` and `CLAUDE/UPGRADES/config-changes/v3.58.0.yaml`
(the newest manifest): its one `added` entry naming a handler key
(`handlers.session_start.monorepo_detector`) is already `enabled: true` in
this repo's config, so it would NOT appear in Step 5's recommendation list —
correct behaviour (nothing to recommend when already adopted). The new
`config_optimisation_reminder` handler itself was added to this repo's own
`.claude/hooks-daemon.yaml` (`enabled: true, priority: 67`) as part of this
plan's dogfooding — this repo now exercises the exact mechanism being built.

**Left for the coordinator to verify live** (cannot be exercised from an
isolated worktree per the pitfall documented in Plan 00309's JOURNAL — the
shared `/workspace/.venv` editable install resolves to the MAIN repo's
`src/`, not this worktree's):

1. `bin/hooks-daemon restart && bin/hooks-daemon status` from the merged
   main-repo checkout, then confirm `config_optimisation_reminder` appears in
   `bin/hooks-daemon handlers`.
2. Delete/rename `untracked/config_optimisation_state.json` (or run in a
   fresh checkout where it never existed), start a new session, and confirm
   the SessionStart advisory fires with "No config-optimisation review... has
   ever been recorded".
3. Run `bin/hooks-daemon record-config-optimisation-run`, confirm the file is
   written, restart a session, confirm the advisory is now silent.
4. Full client-mode install/upgrade smoke test per
   `CLAUDE/development/` client-mode testing docs — genuinely running
   `scripts/upgrade.sh --project-root <test-project>` end to end (including
   the `--skip-config-optimisation` flag path) is out of reach from this
   worktree without a second scratch project and network access to fetch the
   script from `main`, which would fetch the PRE-merge version of this very
   change.

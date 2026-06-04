# Plan 00118 — Research: Docs-Upgrade Guidance Mechanism

**Purpose of this document**: Ground-truth map of the existing upgrade/install,
docs-generation, skills, and version-awareness machinery, so the ideation and
PLAN phases build on what exists rather than reinventing it.

**The problem we are solving** (from the user):

> We need a mechanism to drive **project-level documentation updates** after a
> hooks-daemon upgrade/install. It must:
>
> 1. Output **clear guidance for tasks the project LLM must perform** (e.g.
>    "replace outdated plan-number-discovery docs to conform with the
>    git-config counter approach").
> 2. Be **rediscoverable via a CLI command** (not a one-shot message that
>    scrolls away).
> 3. Generate guidance **per version**, so an LLM doing a big multi-version
>    upgrade can reassess everything that changed.
> 4. Possibly ship as a **dedicated skill** for hooks-daemon docs upgrades.

The motivating concrete example: project docs (and `plan_number_helper`'s own
`get_claude_md()`, which returns `None`) still imply plan numbers come from
scanning `CLAUDE/Plan/`. Since Plan 00112 the authoritative source is the git
counter `hooksdaemon.latestPlanNumber`. Nothing tells a project LLM to update
its docs to match. This plan generalises the fix.

---

## A. Upgrade & Install Flow

### Upgrade (two layers)

- **Layer 1**: `scripts/upgrade.sh` — stable, curl-fetchable bootstrap. Stops
  daemon (PID-only), fetches tags, checks out the target tag, delegates to
  Layer 2, then **emits an `UPGRADE_METADATA` sentinel block** with
  `from_version`, `to_version`, `python_*`, `venv_path`, `modified_files`,
  `config_diff_summary`.
- **Layer 2**: `scripts/upgrade_version.sh` — "clean reinstall + config
  preservation", state snapshot + rollback trap.

**Key fact**: upgrade does **NOT** write anything into the project's `CLAUDE/`
docs, and does **NOT** surface post-upgrade tasks automatically. The skill
`upgrade.md` tells the LLM to parse `UPGRADE_METADATA`, commit atomically, and
verify the daemon — but the LLM is never handed a list of doc-update tasks.

### Install

- **Layer 1**: `install.sh` → clones daemon to `.claude/hooks-daemon/`,
  delegates to Layer 2.
- **Layer 2**: `scripts/install_version.sh` writes into the project:
  `.claude/hooks/` (forwarders), `.claude/init.sh`, `.claude/hooks-daemon.yaml`,
  `.claude/settings.json`, `.claude/commands/`, and
  `.claude/skills/hooks-daemon/` (via `install/skills.py::deploy_skills`).
- `CLAUDE/` is **project-owned** and not written during install.

### Version tracking

- Daemon version: `src/claude_code_hooks_daemon/version.py` (`__version__`).
- Per-venv marker: `daemon/metadata.py` writes `.daemon-metadata.json` inside
  each fingerprint-keyed venv with `daemon_version`, `written_at`, `lock_hash`,
  `fingerprint`, `python_path`. **This is the only persisted "installed
  version" marker** — there is no project-root version file. A
  "last-docs-synced version" marker does **not** exist yet (likely needed).

### `CLAUDE/UPGRADES/` — the existing convention we should extend

```
CLAUDE/UPGRADES/
├── README.md                       # philosophy: tasks are "discoverable by convention"
├── config-changes/                 # per-version config-schema manifests
│   ├── SCHEMA.md
│   └── v{X.Y.Z}.yaml
├── UNRELEASED/post-upgrade-tasks/   # staging; moved to versioned guide at release
│   ├── README.md                   # TASK SCHEMA (below)
│   └── NN-*.md
├── upgrade-template/                # template for a new versioned guide
└── v{MAJOR}/v{PREV}-to-v{NEW}/
    ├── v{PREV}-to-v{NEW}.md
    ├── config-{before,after,additions}.yaml
    ├── verification.sh
    └── post-upgrade-tasks/{README.md, NN-*.md}
```

**Post-upgrade-task schema** (`UNRELEASED/post-upgrade-tasks/README.md`):

- Front-matter-ish fields: `Type` (audit | config-migration | workflow-change |
  notification | other), `Severity` (critical | recommended | optional),
  `Applies to` (version range, e.g. `≤v3.2.1`), `Idempotent` (yes/no).
- Mandatory sections: `## Why`, `## How to detect if this applies to you`,
  `## How to handle`, `## How to confirm`, `## Rollback / if this goes wrong`.
- Real example: `v3/v3.6-to-v3.7/post-upgrade-tasks/01-prune-legacy-venv.md`.

**This schema is already 90% of what the user asked for** — a per-version,
LLM-actionable, detectable task description. The gap is **delivery**: these
files are authored for THIS repo's release flow and live in the daemon's own
`CLAUDE/UPGRADES/`; a downstream project never receives them, and nothing
**surfaces** the applicable ones after an upgrade. The mechanism we build is
essentially: *ship these tasks downstream + surface the applicable subset via a
CLI command and/or skill.*

---

## B. Docs-Generation & CLI Surface

- **CLI entrypoint**: `daemon/cli.py`. New subcommands follow a fixed pattern:
  define `cmd_<name>(args) -> int` before `main()`, then in `main()`:
  `p = subparsers.add_parser("name", help=...)`, add args,
  `p.set_defaults(func=cmd_<name>)`, and add a line to the module docstring.
- **`generate-docs`** (`daemon/docs_generator.py`): instantiates all handlers,
  reads tags + docstring first line, renders `.claude/HOOKS-DAEMON.md` tables.
  Good model for "aggregate per-handler metadata into a doc."
- **`generate-playbook`** (`daemon/playbook_generator.py`): calls
  `handler.get_acceptance_tests()` across all handlers and aggregates. **This is
  the closest existing pattern to "ask every handler what it contributes"** —
  the per-version guidance generator should mirror it.
- **`<hooksdaemon>...</hooksdaemon>` injection**
  (`core/claude_md_injector.py`): on daemon restart, collects
  `handler.get_claude_md()` from every handler implementing `HasClaudeMd`,
  wraps in the tag block, replaces-or-appends in project `CLAUDE.md`, preserves
  user content, writes `.CLAUDE.md.pre-inject` backup, then auto-commits
  ("Auto: hooks daemon regenerated CLAUDE.md handler guidance"). This is the
  live channel by which handler guidance already reaches the project — but it is
  **stateless about version** (always "current", no per-version diff, no
  "things you must change in YOUR docs").
- **`check-config-migrations`** (`install/config_migrations.py` +
  `config_cli.py`): `--from`/`--to`/`--config`/`--format`. Reads
  `CLAUDE/UPGRADES/config-changes/v{X.Y.Z}.yaml` manifests and reports
  renamed/removed keys still in the user's config + newly-available options.
  **This is the existing "per-version, version-range CLI guidance" precedent** —
  the new command should be its sibling for docs/feature guidance, not config.

---

## C. Skills System

- **Source**: `src/claude_code_hooks_daemon/skills/hooks-daemon/` with
  `SKILL.md` (frontmatter + bash router), per-topic `.md` docs, and `scripts/`.
- **Frontmatter schema**: `name`, `description`, `argument-hint`,
  optional `disable-model-invocation`, `user-invocable`, `allowed-tools`.
- **Deployment**: `install/skills.py::deploy_skills()` removes + `copytree`s the
  whole skill dir into `.claude/skills/hooks-daemon/`, chmods scripts. **Skills
  are REFRESHED on every upgrade** (atomic commit alongside daemon code + hook
  forwarders).
- **Self-bootstrapping scripts** (`upgrade.sh`, `daemon-cli.sh`,
  `health-check.sh`, `init-handlers.sh`): download `bootstrap-checksums.txt`
  from the latest GitHub release, sha256-verify their own body, re-exec a fresh
  copy if stale, abort on mismatch. Release bundles all four + the manifest.
- **Discovery**: Claude Code auto-discovers `.claude/skills/*/SKILL.md` →
  `/<dirname>`. A new skill needs no registration; it just needs to be deployed.
- **Single-source rule** (`.claude/skills/CLAUDE.md`): SKILL.md links to
  canonical docs (`docs/guides/...`, `CLAUDE/...`) rather than duplicating.

**Implication**: a new `hooks-daemon docs-upgrade` capability can be either a
new top-level skill dir (`skills/docs-upgrade/`) OR a new subcommand of the
existing `hooks-daemon` skill router (`/hooks-daemon docs-upgrade`). The latter
reuses deployment + bootstrap for free. Decision deferred to ideation.

---

## D. Version-Awareness Handler Pattern (the delivery model)

- **`version_check.py`** (SessionStart, prio 56): compares `__version__` to
  latest GitHub tag (cached), emits advisory `HookResult.context` lines
  ("📦 update available: vX → vY" + steps). Non-blocking, `Decision.ALLOW`.
- **Sibling advisory SessionStart handlers** —
  `hook_registration_checker` (also implements `get_claude_md()` policy),
  `optimal_config_checker`, `gitignore_safety_checker` — all share the shape:
  1. run a check at SessionStart (new sessions only),
  2. return `Decision.ALLOW`,
  3. emit a `context` list (status line + per-finding `Why/Fix/Where/Docs`),
  4. optionally inject `get_claude_md()` guidance,
  5. priority in the advisory band (56–59), terminal `False`.

**This is the ready-made channel for "your docs are stale, run the
docs-upgrade command"** — a SessionStart advisory that fires when the installed
daemon version is newer than a persisted "docs-synced" marker.

### The concrete motivating gap

- `plan_number_helper.get_claude_md()` returns `None` (confirmed) → no injected
  explanation of the git-anchored counter.
- `CLAUDE/PlanWorkflow.md` and `docs/PLAN_SYSTEM.md` describe plan workflow but
  **do not mention** `hooksdaemon.latestPlanNumber`; older bug reports/plans
  still show `find CLAUDE/Plan ...` idioms. A downstream project that copied an
  early PlanWorkflow.md will still instruct agents to scan the folder.
- So the example task the new mechanism must emit is literally: *"Your
  plan-number docs predate the git-anchored counter (Plan 00112). Update
  `<project>/CLAUDE/PlanWorkflow.md` to state the next number comes from
  `git config --local hooksdaemon.latestPlanNumber` (+1), bootstrapped from a
  folder scan only when unset."*

---

## E. Synthesis — what exists vs what's missing

| Capability needed                         | Exists today?                            | Gap                                               |
| ----------------------------------------- | ---------------------------------------- | ------------------------------------------------- |
| Per-version, LLM-actionable task schema   | ✅ `post-upgrade-tasks`                  | Not shipped downstream; not surfaced              |
| Per-version CLI guidance by version range | ✅ `check-config-migrations`             | Config-only; no docs/feature guidance             |
| Aggregate-from-all-handlers generator     | ✅ `generate-playbook` / `generate-docs` | No "doc-change/feature" contribution per handler  |
| Live channel into project CLAUDE.md       | ✅ `get_claude_md()` injection           | Stateless re version; no "change YOUR docs" tasks |
| SessionStart "you should act" advisory    | ✅ `version_check` + siblings            | No "docs out of date for vX" advisory             |
| Persisted "docs-synced version" marker    | ❌                                       | Needed to detect staleness idempotently           |
| Skill deployment + bootstrap + refresh    | ✅ skills system                         | No docs-upgrade skill/subcommand yet              |

**One-line conclusion**: We are not building from scratch. We are **connecting
four existing systems** — the `post-upgrade-tasks` schema, the
`check-config-migrations` per-version CLI precedent, the `generate-playbook`
aggregation pattern, and the SessionStart-advisory delivery channel — into a
single "docs-upgrade guidance" pipeline, plus a persisted docs-synced marker and
a CLI command (and/or skill) to re-emit the applicable task set on demand and
per-version.

---

## Key file references

| Concern                                 | Path                                                                         |
| --------------------------------------- | ---------------------------------------------------------------------------- |
| Upgrade L1 / metadata block             | `scripts/upgrade.sh`                                                         |
| Upgrade L2                              | `scripts/upgrade_version.sh`                                                 |
| Install L2 (writes project files)       | `scripts/install_version.sh`                                                 |
| Skill deployment                        | `src/claude_code_hooks_daemon/install/skills.py`                             |
| Post-upgrade-task schema                | `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md`                    |
| Versioned guide example                 | `CLAUDE/UPGRADES/v3/v3.6-to-v3.7/post-upgrade-tasks/01-prune-legacy-venv.md` |
| Config-migration CLI (precedent)        | `install/config_migrations.py`, `install/config_cli.py`                      |
| CLI entrypoint / subcommand pattern     | `daemon/cli.py`                                                              |
| Docs generator (aggregation model)      | `daemon/docs_generator.py`                                                   |
| Playbook generator (aggregation model)  | `daemon/playbook_generator.py`                                               |
| CLAUDE.md injector (live channel)       | `core/claude_md_injector.py`                                                 |
| Version-check advisory (delivery model) | `handlers/session_start/version_check.py`                                    |
| Per-venv version marker                 | `daemon/metadata.py` (`.daemon-metadata.json`)                               |
| Motivating gap                          | `handlers/pre_tool_use/plan_number_helper.py` (`get_claude_md()` → None)     |
| Skill source                            | `src/claude_code_hooks_daemon/skills/hooks-daemon/`                          |

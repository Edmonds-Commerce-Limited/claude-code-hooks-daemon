# UNRELEASED — Staging for the Next Release

Anything in this directory is destined for the **next** upgrade guide. It accumulates between releases, and the `/release` skill moves its contents into the versioned upgrade directory at release time.

## What belongs here

- **`post-upgrade-tasks/`** — instructions for LLMs/humans to follow *after* they have upgraded to the next version. See `post-upgrade-tasks/README.md` for the convention.
- **`truth-changes/`** — the per-version truth-changes manifest the upgrade flow reconciles. See `truth-changes/README.md`.
- **`config-changes/`** — config-key changes the upgrade flow previews. See `config-changes/README.md`.
- **`release-notes/`** — one short callout per plan, in the voice of the release notes, for the release to fold in. See `release-notes/README.md`.

**This directory is part of every plan's definition of done.** A plan closes only once its release-bound consequences are written here (`CLAUDE/core/PlanWorkflow.core.md`, "Definition of done" and step 0 of the Plan Completion Checklist). A plan never waits for the release to consume them.

Anything else staged for the next release (draft migration notes, config-change previews, breaking-change descriptions that aren't ready for the main guide yet) can live alongside `post-upgrade-tasks/` in sensibly-named subdirectories.

## What does NOT belong here

- Finalised content for a shipped release — that lives under `v{MAJOR}/v{PREV}-to-v{NEW}/`.
- Ephemeral notes, drafts unrelated to the next release, or project-tracking content — those belong in `CLAUDE/Plan/` or `untracked/`.

## Who writes here

Any contributor, agent, or release author who identifies something that **users/agents will need to act on after upgrading**. Examples:

- A bug fix lands that may have silently corrupted user files under prior versions → add a `post-upgrade-tasks/NN-audit-...md` task.
- A default config value changes and user configs should be reviewed → add a `post-upgrade-tasks/NN-review-config-....md` task.
- A handler's behaviour changes in a way that existing project workflows should adapt to → add a `post-upgrade-tasks/NN-adopt-....md` task.

## How the release skill handles this directory

At release time, the `/release` skill:

1. Reads every file under `UNRELEASED/`.
2. Moves them into the new versioned upgrade directory, e.g. `CLAUDE/UPGRADES/v3/v3.2-to-v3.3/`.
3. Renumbers task files if the versioned directory already has tasks from earlier drafts.
4. Links the new upgrade guide's `post-upgrade-tasks/README.md` from `RELEASES/vX.Y.Z.md`, and folds every `release-notes/` callout into those notes before moving the files.
5. Leaves `UNRELEASED/` empty (except for its own `README.md` and each shape's `README.md` scaffolding), ready for the next release cycle.

See `CLAUDE/development/RELEASING.md` for the authoritative release process.

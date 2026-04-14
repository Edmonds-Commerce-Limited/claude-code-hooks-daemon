# Post-Upgrade Tasks — Convention

This directory holds **instructions for an LLM (or human) to follow after upgrading** to the next release. Tasks are advisory, not automated — they give an agent enough context to decide what to do in the user's specific project.

## What post-upgrade tasks are for

Any situation where a successful upgrade is **not enough on its own** — the user's project may need further attention. Common categories:

| Category           | Example                                                                                                            |
| ------------------ | ------------------------------------------------------------------------------------------------------------------ |
| `audit`            | A prior version had a bug that may have silently corrupted files on disk; scan for damage and suggest remediation. |
| `config-migration` | A default config value changed; review user config and adapt if relied on the old default.                         |
| `workflow-change`  | A handler's behaviour now differs (e.g. more strict); alert the user and suggest adapting their workflow.          |
| `data-migration`   | Stored data format changed; transform existing data.                                                               |
| `notification`     | Pure awareness — something changed that the user should know but no action may be required.                        |
| `other`            | Anything else with the same shape: detect applicability, then act.                                                 |

## What post-upgrade tasks are NOT

- **Not an automation pipeline.** There is no runner. Nothing executes these tasks automatically. They are prompts/instructions for a capable agent to read and act on.
- **Not a place for general release-note content.** Release notes go in `RELEASES/vX.Y.Z.md`. Tasks are only for things that need *post-upgrade action*.
- **Not a substitute for `verification.sh`.** `verification.sh` confirms the upgrade itself succeeded. Post-upgrade tasks are about work *after* a successful upgrade.

## File naming

```
NN-kebab-case-description.md
```

- `NN` — two-digit ordinal (`01`, `02`, …). Reserve three-digit (`001`) for the rare case where ordering needs >99 slots within a single release; three-digit files sort cleanly alongside two-digit (treat all files as string-sorted).
- Descriptive kebab-case slug that makes the purpose obvious without opening the file.

Examples:

- `01-audit-markdown-frontmatter.md`
- `02-review-handler-priority-defaults.md`
- `03-migrate-workflow-state-schema.md`

## File structure (mandatory schema)

Every task `.md` MUST start with this header block so LLMs can decide whether it applies without reading the whole file:

```markdown
# Task: [Short human title]

**Type**: audit | config-migration | data-migration | workflow-change | notification | other
**Severity**: critical | recommended | optional
**Applies to**: [which prior versions trigger this — e.g. "≤v3.2.1", "v3.0.0..v3.2.1", or "all" for config/workflow changes that affect everyone]
**Idempotent**: yes | no
```

Then the following sections in order:

### `## Why`

One short paragraph on what motivated this task. If it's a bug-fix audit, link to the commit/issue. If it's a workflow change, say what changed and why.

### `## How to detect if this applies to you`

Plain-language guidance for the LLM to decide whether to continue. Embed sample commands the LLM can adapt — do not assume a particular shell, toolchain, or project layout. The LLM is expected to adapt, not copy-paste blindly.

If `Applies to: all`, this section can say so briefly.

### `## How to handle`

Plain-language instructions. Include:

- What to look for in scan results.
- Suggested remediation paths (e.g. "restore from `git log`", "regenerate from template", "ask the user").
- When to ask the user rather than act autonomously.

Sample commands are allowed and encouraged — bash for simple cases, Python for complex transformations. Label them **"sample"** so the LLM understands they may need adapting to the project.

### `## How to confirm`

How the LLM (or user) knows the task is done. Short — one or two checks is usually enough.

### `## Rollback / if this goes wrong`

Optional but encouraged for anything involving file modification. Describe how to recover if the suggested remediation turns out to be wrong for the user's project.

## Task index

This file's lower half should list the tasks currently in this directory, so an agent can see the full picture at a glance. Keep one line per task, ordered by filename:

<!-- BEGIN TASK INDEX — regenerate when adding/removing tasks -->

| File                               | Type  | Severity    | Applies to     | One-line summary                                                                                                            |
| ---------------------------------- | ----- | ----------- | -------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `01-audit-markdown-frontmatter.md` | audit | recommended | v3.0.0..v3.2.1 | Find `.md` files whose YAML frontmatter was mangled by the pre-fix `markdown_table_formatter` and restore from git history. |

<!-- END TASK INDEX -->

## When the release happens

The `/release` skill moves every task file in this directory into the versioned upgrade guide (e.g. `CLAUDE/UPGRADES/v3/v3.2-to-v3.3/post-upgrade-tasks/`), regenerates that guide's task index, and leaves this directory empty apart from this README.

# Task: Rewrite `level` → `severity` at every call site parsing `plan-qa --json`, before v3.64.0 lands

**Type**: workflow-change
**Severity**: critical
**Applies to**: upgrades from v3.63.x or earlier, in any project whose tooling parses `hooks-daemon plan-qa --json`
**Idempotent**: yes
**Detect**: `^(?![^\n]*\bseverity\b)[^\n]*plan[-_]qa\b[^\n]*--json`
**Detect in**: `*.py`, `*.sh`, `*.bash`, `*.js`, `*.mjs`, `*.ts`, `*.yml`, `*.yaml`, `*Makefile`, `*.mk`, `*.just`, `*justfile`

## Why

From v3.64.0, `plan-qa --json` names a finding's severity `severity`, as
`docs-qa --json` always did; it no longer emits `level` (Plan 00375). The
change is deliberately MAJOR in effect and ships with no deprecation window:
a window would make the two-names defect correct by policy for a release. The
daemon is installed inside the consuming repository by an agent with write
access, so the upgrade migrates the call sites instead of announcing the
change.

The failure mode is silence. A consumer reading `finding.get("level")` gets
`None` for every finding and reports a clean tree that is not clean. Done
BEFORE the new version is deployed, the rewrite means no call site is ever
broken, not even for the length of one upgrade.

This task is the pre-deploy twin of
`../post-upgrade-tasks/01-rewrite-plan-qa-json-level-to-severity.md`, which
predates the pre-deploy gate and carries the same substance.

## How to detect if this applies to you

The gate has already run the **Detect** pattern and listed every line that
invokes `plan-qa` (or `plan_qa`) with `--json`, at `file:line`. A file name
such as `plan_qa.json` is not an invocation and is not listed, and neither is
a line that already names `severity` (a one-line consumer that has been
migrated, such as `plan-qa --json | jq '.findings[].severity'`). For each
hit, find the code that reads the parsed findings, which may be on a later
line or in another file the output is handed to, and check whether it reads a
`level` key: `["level"]`, `.get("level")`, `.level`, `jq '.findings[].level'`,
or a destructuring form. Those are the call sites to change.

The pattern cannot see a consumer that receives the JSON from somewhere else
(a CI artefact, a file written earlier). If you know of one, include it.

If no hit reads `level`, there is nothing to rewrite. Say so in your report.
The upgrade still needs the owner: this task is `critical`, so any listed hit
sends the upgrade to the project owner, even a hit that on inspection turns
out not to read `level` (see below). The owner reads your finding and decides.

## How to handle

Rename the key at each consuming call site. The values are unchanged; only
the key name moves.

- Change only reads of a finding object produced by `plan-qa --json`.
  `level` is an ordinary word (log levels, nesting levels): never replace it
  project-wide.
- `docs-qa --json` already emitted `severity` and needs no change.
- A call site that branches on which key is present can drop the branch: one
  name now works for both verbs.
- If you cannot tell whether a `level` read belongs to this output, ask the
  user rather than guessing.

Because this task is `critical` and was detected, the gate also needs the
project owner's one-shot approval for the upgrade. The stop message prints the
exact command, which the owner runs in their own terminal. Report the call
sites and the rewrite to the owner, and stop: an agent cannot record the
approval.

## How to confirm

Every call site the gate listed either reads `severity`, or was checked and
does not read `level` from `plan-qa --json`. After the upgrade, run the
project's own tooling once and confirm it still reports the findings it
reported before: a run that suddenly reports zero findings is the symptom this
task exists to prevent.

## Rollback / if this goes wrong

The rewrite touches only call sites you control; `git diff` shows it, and
`git show HEAD:<file> > <file>` puts one file back as last committed. No
stored data is transformed.

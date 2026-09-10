# Guarded branch install — design note (Plan 00291 Task 3.1)

This document is the single place that records the shape of the first-party
branch-install gate. It is a supporting document of Plan 00291 and is
deliberately NOT linked from any user-facing install or update document.

## Owner ruling this implements

> "supporting main as a version should not become something normal users can
> do, its really only for us — so whatever mechanism needs to be something
> guarded and non obvious and with clear warnings." (2026-08-30, binding)

Every clause below maps to that ruling: no positional spelling, an
environment gate with a mandatory reason, a loud banner, a version stamp that
outlives the install, and a `status` / `version_check` that never call the
result "up to date".

## The gate

Two environment variables, BOTH required, read by the upgrade tooling only:

| Variable                                | Meaning                                                                    |
| --------------------------------------- | -------------------------------------------------------------------------- |
| `HOOKS_DAEMON_UNSAFE_TRACK_REF`         | The git ref to install: a branch name (`main`, `worktree-plan-00291`).     |
| `HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE` | A non-empty, free-text reason. Recorded nowhere but printed in the banner. |

Rules:

- **Neither set**: the tooling behaves exactly as before. A positional
  version that is not a tag still fails: Layer 1 normalises `main` to `vmain`
  and `git rev-parse vmain` fails. The positional spelling is never a route.
- **Exactly one set**: hard refusal, exit 1, naming the variable that is
  missing. A half-armed gate is treated as a mistake, never as "off".
- **Both set, plus a positional version**: hard refusal. The gate names the
  ref; a second spelling of the target is a contradiction, not a tie-break.
- **Both set, no positional**: Layer 1 (`scripts/upgrade.sh`) fetches the ref
  from `origin`, lands the daemon dir on that commit (forced reset in a client
  install, plain checkout in self-install), prints the banner, and hands
  Layer 2 the resolved **commit SHA** as its target. Layer 2
  (`scripts/upgrade_version.sh`) re-validates the gate, prints the banner
  again (it is a public entry point), and stamps the install.
- The gate never appears in the `--help` text of either script.

`HOOKS_DAEMON_UPGRADE_REF` is a different, pre-existing variable (it selects
which ref Layer 1 fetches ITS OWN helper library from). The two are never
overloaded onto each other.

## The banner

Printed by both layers, to stdout, before anything is changed and again in
the completion summary:

```
==========================================================================
  WARNING: NON-RELEASE INSTALL (guarded branch install)
  Tracking ref : <ref> @ <shortsha>
  Reason       : <HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE>
  This is not a release. No rollback guarantee, no upgrade-guide coverage
  until the release that contains it ships. status and every new session
  will flag this install until it is reinstalled from a release tag.
==========================================================================
```

## The stamp

A branch install records `vX.Y.Z+<ref>.<shortsha>` wherever a release install
records `vX.Y.Z`:

- `X.Y.Z` is the `[project].version` in `pyproject.toml` at the installed
  commit (the version the branch is heading towards).
- `<ref>` is the tracked ref with every `/` replaced by `-`.
- `<shortsha>` is `git rev-parse --short HEAD` at the installed commit.

Where it lives: the venv's `.daemon-version` stamp and `.daemon-metadata.json`
`daemon_version` (the metadata validator accepts the `+` suffix). The
`.daemon-version` file is what `status` and `version_check` read, via
`install_stamp.read_install_stamp()`, which resolves the stamp from the
running interpreter's `sys.prefix`.

`ensure_venv` compares stamps for freshness, so a re-run against the same
commit is a no-op and a re-run after the branch moves rebuilds the venv.

## What surfaces it every session

- `hooks-daemon status` prints an `Install:` line naming the stamp and telling
  the operator to reinstall from a release tag. A release install prints no
  such line, so existing byte-for-byte status expectations hold.
- The `version_check` session-start handler, on every NEW session, emits the
  non-release advisory and never consults the cache or the network for a
  branch install. It cannot say "up to date" because it never compares
  versions for one.

## UNRELEASED manifests (Task 2.3)

A branch install is, by definition, ahead of the last release, so the
migrations it is ahead on are the ones in `CLAUDE/UPGRADES/UNRELEASED/`. The
config-changes and truth-changes loaders take `include_unreleased`; when it
is unset the loader asks `read_install_stamp()` and includes the UNRELEASED
directory exactly when the running install is a branch install. Release
installs are unaffected. `check-config-migrations --include-unreleased` and
`check-truth-changes --include-unreleased` force it for tests and for
first-party use from a release install.

## Places that must NOT mention the gate

Pinned by `tests/unit/scripts/test_branch_install_gate_is_unadvertised.py`,
which fails if either variable name appears in any of:

- `CLAUDE/LLM-INSTALL.md`
- `CLAUDE/LLM-UPDATE.md`
- `README.md`
- `.claude/HOOKS-DAEMON.md` (generated: no handler's `get_claude_md` names it)
- `docs/` (the human tree)
- the `--help` output of `scripts/upgrade.sh`

The release-notes callout for this plan says only that a stamped,
first-party-only mechanism exists.

## The canary's standing route

The php-qa-ci canary (`untracked/repos/php-qa-ci`, delete-and-reclone, never
commit) upgrades through the documented Layer 1 route with the gate armed:

```bash
HOSTNAME=canary-php-qa-ci \
HOOKS_DAEMON_UNSAFE_TRACK_REF=<branch> \
HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE="Plan NNNNN canary run" \
bash scripts/upgrade.sh --project-root untracked/repos/php-qa-ci
```

That is the ONLY sanctioned way to put a branch on a client-shaped tree.

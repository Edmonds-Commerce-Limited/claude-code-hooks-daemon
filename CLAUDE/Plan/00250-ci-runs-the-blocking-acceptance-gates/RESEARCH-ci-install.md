# What a CI daemon install actually does

Evidence behind Phase 2, gathered by running the commands rather than reasoning
about them. PLAN.md links here instead of carrying the detail inline.

Everything below was measured on 2026-09-08 against v3.62.1.

## There is no existing CI step that starts a daemon

`.github/workflows/qa.yml`'s `daemon-load` job checks out, installs from the
lockfile, and imports every handler module. It starts no daemon, and says so in
its own comment:

> A real `hooks-daemon restart` needs an installed daemon, so asserting every
> handler module imports is the CI-safe equivalent.

Nothing in this workflow has ever installed or started one. The plan's
conclusion — that this is a provisioning gap rather than a platform limitation —
survives; the cheap route to it (reuse the existing step) does not exist.

## The blocker, from a real CI run

After Task 2.4a made the forwarders reachable, `ensure_daemon` refuses to
auto-start:

```
hooks_daemon_repo_detected — This is the hooks-daemon repository.
To install for development, run: python install.py --self-install
```

So the QA job does not merely lack a *running* daemon, it lacks the
**self-install step**, and starting a daemon cannot work until that runs.

## Regenerated tracked files: real, one line, inert

A self-install regenerates two tracked artefacts. This was written up as a
hazard before it was measured; measured, it is not one.

| Artefact                            | Regenerates as   | Why                              |
| ----------------------------------- | ---------------- | -------------------------------- |
| `CLAUDE.md` (`<hooksdaemon>` block) | byte-identical   | carries no date                  |
| `.claude/HOOKS-DAEMON.md`           | one line differs | header carries a generation date |

```
-> Generated on 2026-09-07 (v3.62.1) by `generate-docs`
+> Generated on 2026-09-08 (v3.62.1) by `generate-docs`
```

Neither file contains environment-specific content — `grep -c /workspace` is
`0` in both — so the generating machine does not leak in.

The differing line is inert:

- `qa.yml` has no `git diff --exit-code` or `git status --porcelain`
  cleanliness assertion anywhere.
- Its `black --check src/ tests/` does not cover `.claude/`.
- The three QA scripts that read the generated doc — `check_doc_truth.py`,
  `check_handler_reference.py`, `measure_instruction_footprint.py` — parse
  handler content, not the header.

If that ever changes, the remedy is a one-line exclusion, not a different CI
structure.

## The one hard constraint: do not pass `--force`

`--force` is the flag an unattended workflow step invites you to add. It is the
wrong one.

`create_settings_json` (`install.py:690`) and `create_daemon_config`
(`install.py:768`) both open with:

```python
if <file>.exists() and not force:
    return
```

The existence check is the *only* protection, and `--force` removes it. Both
files are tracked here, and both carry far more than the installer's template
writes:

| File                        | Template writes        | Tracked file also carries                                                                                                                                                   |
| --------------------------- | ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.claude/settings.json`     | `statusLine`, `hooks`  | `plansDirectory` (required by `R-MARKDOWN-PLAN-SYNC`), a `permissions.deny` block for `/tmp`, `/var/tmp`, `/dev/shm`, `enableArtifact: false`, statusLine `refreshInterval` |
| `.claude/hooks-daemon.yaml` | small default template | 1188 lines, 128 `enabled: true` handlers                                                                                                                                    |

**Why this lands on the plan's own thesis.** Plan 00250 exists to stop blocking
acceptance gates passing invisibly without a daemon. An install step carrying
`--force` would give them a daemon — running a *different handler set* from the
one the project ships. The gates would go green against a configuration nobody
uses. That is worse than the skip this plan is fixing, because a skip at least
leaves a trace in the output.

Without `--force`, both files already exist in a CI checkout, both writes are
skipped, and the tree stays clean.

## The install cannot be rehearsed from inside this repo

`validate_installation_target` walks `project_root.parents` and refuses if any
of them contains `.claude/hooks-daemon`:

```
Cannot install: <path> is inside an existing installation at /workspace
```

Every worktree under `/workspace` trips this. A runner checking out to
`/home/runner/work/X/X` has no such parent and passes, so this is a
local-probe artefact rather than a CI blocker — but it does mean a local
rehearsal is not available, and the refusal should not be misread as one.

## Write footprint

Every path `install.py` writes is under the project root, all within `.claude/`
plus one env file. There is no `expanduser`, no `Path.home()`, no `~/.claude`.
Its `subprocess` calls are all `cwd`-scoped to the project root and read-only
except `git update-index --chmod=+x`, which touches the git index and is
reached only when `core.fileMode` is `false`.

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

## The hard constraint: do not run the installer at all

**This section previously said the constraint was "do not pass `--force`", on
the reading that both writers skip an existing file unless forced. That was
wrong — I matched the `if <file>.exists() and not force:` condition without
reading its body — and the runner proved it wrong.** What both functions
actually do:

```python
if <file>.exists() and not force:
    backup_file = ...            # NOT a return
    <file>.rename(backup_file)   # move the real config aside
# ... then write the default template unconditionally
```

`create_settings_json` (`install.py:690`) and `create_daemon_config`
(`install.py:768`) are identical in shape. So **`force` only controls whether a
backup is taken — both paths overwrite.** There is no invocation of the
installer that preserves an existing config.

Observed on the runner, not inferred:

```
✅ Backed up existing hooks-daemon.yaml to .claude/hooks-daemon.yaml.bak
✅ Created .claude/hooks-daemon.yaml
```

Both files are tracked here, and both carry far more than the installer's
template writes:

| File                        | Template writes        | Tracked file also carries                                                                                                                                                   |
| --------------------------- | ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.claude/settings.json`     | `statusLine`, `hooks`  | `plansDirectory` (required by `R-MARKDOWN-PLAN-SYNC`), a `permissions.deny` block for `/tmp`, `/var/tmp`, `/dev/shm`, `enableArtifact: false`, statusLine `refreshInterval` |
| `.claude/hooks-daemon.yaml` | small default template | 1188 lines, 128 `enabled: true` handlers                                                                                                                                    |

**Why this lands on the plan's own thesis.** Plan 00250 exists to stop blocking
acceptance gates passing invisibly without a daemon. An install step gives them
a daemon running a *different handler set* from the one the project ships — the
gates would go green against a configuration nobody uses, which is worse than
the skip, because a skip at least leaves a trace.

In the event it did not even get that far: the template `create_daemon_config`
writes is **invalid against the current schema**, so the daemon refused to
start —

```
Config Error: Configuration validation failed.
  Unknown field 'min_confidence_score' at: handlers.session_start.min_confidence_score
  Valid fields: enabled, options, priority
```

— and the run went from 4 failures per interpreter to **31 failures + 7 errors**,
because every test that reads configuration was now reading the template. That
is a daemon defect in its own right, not merely a CI problem: `python install.py` writes a config the daemon cannot load, and the three offending keys
belong to `yolo_container_detection`, which no longer has a handler module at
all (`install.py:890-892`).

## What CI actually needs: no installer

A checkout already has the config, the forwarders and the package. The only
missing piece is `.claude/hooks-daemon.env`, which the repo guard accepts on
mere existence, and which is gitignored — so writing it leaves the tree clean:

```yaml
- name: Start daemon (for the acceptance gates)
  env:
    HOOKS_DAEMON_VENV_PATH: ${{ github.workspace }}/.venv
  run: |
    printf 'HOOKS_DAEMON_ROOT_DIR="%s"\n' "$GITHUB_WORKSPACE" > .claude/hooks-daemon.env
    ./bin/hooks-daemon restart
    ./bin/hooks-daemon status
```

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

## What the gates actually need: a *running* daemon, not an installed one

The skip is keyed on a live socket, not on installation
(`tests/acceptance/test_absolute_path_socket_deny.py:118`):

```python
sock_path = _discover_socket()
if sock_path is None:
    pytest.skip("Daemon not running — no live socket found under untracked/. ...")
```

The tests open that socket **directly**, not through a hook forwarder. That
matters because `init.sh` has a documented CI passthrough mode
(`tests/unit/test_ci_passthrough.py`): under `GITHUB_ACTIONS=true` the
forwarders deliberately no-op on the grounds that "the daemon is simply not
installed in this pipeline". Passthrough governs the forwarder path only, so it
does not interfere with tests that speak to the socket themselves.

## The three mechanisms that make it work

Each read out of the source rather than inferred:

1. **The repo guard** (`init.sh:246-264`) refuses to start a daemon in this
   repository unless `HOOKS_DAEMON_ROOT_DIR == PROJECT_PATH` **or**
   `.claude/hooks-daemon.env` merely *exists*. That file is gitignored
   (`.claude/.gitignore:16`), so a fresh checkout has neither — which is why CI
   reports `hooks_daemon_repo_detected`. `install.py` writes it
   (`create_daemon_env`, `install.py:1493`).

2. **`self_install_mode` is already tracked.** `.claude/hooks-daemon.yaml:7`
   carries `self_install_mode: true`, so a checkout already has it and the
   install does not need `--force` to set it. This is what makes the no-`--force`
   install sufficient rather than merely safe.

3. **The venv override.** `resolve_venv.sh:113-121` checks
   `$HOOKS_DAEMON_VENV_PATH/bin/python` *before* its
   `untracked/venv-*/bin/python` fingerprint glob. CI's `uv sync` builds `.venv`
   at the repo root, which that glob cannot see, so the override points the
   daemon at the toolchain CI already has instead of building a second one.

Which gives the workflow steps now in `qa.yml`:

```yaml
- name: Install daemon (for the acceptance gates)
  run: python install.py --self-install       # NO --force

- name: Start daemon
  env:
    HOOKS_DAEMON_VENV_PATH: ${{ github.workspace }}/.venv
  run: |
    ./bin/hooks-daemon restart
    ./bin/hooks-daemon status
```

## Socket collision across the matrix (Task 2.3)

Collision is impossible for a reason stronger than the hostname suffix the task
names. The socket lives under `daemon_dir / "untracked"` — **inside the
checkout** — and each matrix job runs on its own runner VM with its own
filesystem, so the three interpreters share nothing to collide over. The
hostname suffix is a second layer, not the mechanism.

Worth stating explicitly because Task 2.4b showed this resolution is subtler
than it looks: on a runner `$HOSTNAME` is unexported, so the suffix comes from
`socket.gethostname()`. If the suffix were the *only* isolation, the answer
would depend on how GitHub names runner VMs — which is not a property this
project controls or should rely on.

**Unverified until a runner executes it.** Every mechanism above is read from
source; none of it has been observed end-to-end, because the install cannot be
rehearsed inside this repo (see above). Two consequences to expect rather than
be surprised by: coverage moves when 16 skipped tests start running, and tests
that have only ever run *without* a daemon may fail — Plan 00250 Task 2.2 treats
those as long-standing, not as regressions from the workflow edit.

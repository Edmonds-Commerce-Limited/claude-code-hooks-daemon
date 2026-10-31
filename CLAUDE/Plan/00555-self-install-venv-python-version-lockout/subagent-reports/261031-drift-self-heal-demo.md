# Plan 00555: end-to-end drift self-heal demonstration

Success criterion under test: "Simulated drift on a scratch self-install
self-heals with no human command". Run on main at `60b78b057`, on
2026-10-31 between 12:02Z and 12:05Z.

## Verdict

**PASS for the incident's real shape (Variant B).** The scratch tree locked
itself out the way INCIDENT.md describes, then healed with no human command.
A SessionStart hook detected the drift, refused the drifted venv, and started
a detached build. The build created the venv keyed to the running Python,
succeeded in 4 s and wrote `.venv-bootstrap.result`. The next PreToolUse hook
started the daemon on the new venv, and the daemon enforced a deny.

**FAIL for a second shape (Variant A).** Here the venv already sits at the
CURRENT fingerprint key, but its `pyvenv.cfg` names another minor. The
self-heal build reuses that venv without rebuilding it, fails its own success
check, and records a `.failed` marker. After that, hooks stop retrying, and
`hooks-daemon repair` fails the same way. That is a lockout which only a human
`rm -rf` of the venv clears. The natural interpreter-upgrade path cannot
produce this shape, because the key changes with the minor version. It can
still arise (see Finding 1).

Evidence copies: `untracked/scratch/drift-demo-evidence/` in /workspace. This
directory holds the hook stdin JSON, each hook's stdout and stderr, the build
log, and the result file. It is untracked.

## Setup

Neither /workspace's own venvs nor its daemon were touched. Afterwards
`untracked/` still holds only `venv-workspace-py313-0d6d49c6` and `lsp-venv`.

```
git worktree add --detach /workspace/.claude/worktrees/drift-demo HEAD
cd /workspace/.claude/worktrees/drift-demo
timeout 900 bin/hooks-daemon repair      # rc=0
```

- There is no `.claude/hooks-daemon.env`, because it is gitignored. So
  `init.sh` takes the raw-self-install-clone branch (`init.sh:1323-1326`) with
  `HOOKS_DAEMON_ROOT_DIR` set to the worktree.
- The forwarder's relay block only matches `/workspace/.claude/hooks/*`, so the
  scratch hooks ran the full `init.sh` path.
- The build produced
  `untracked/venv-workspace_claude_worktrees_drift-demo-py313-0d6d49c6`, with
  `bin/python -> /usr/bin/python3.13` and `version_info = 3.13.5`.

**Baseline.** The command was:

```
bash .claude/hooks/pre-tool-use < pretool.json
```

The `pretool.json` input was a realistic PreToolUse payload for
`Bash: git status`. The daemon started in 2.5 s, and `status` reported
`RUNNING` with 31/31 listeners. `bin/hooks-daemon stop` then simulated the
restart that comes with a host or image change.

## Variant B: the incident's shape (PASS)

**Drift applied by hand.** No site-packages was deleted.

- The venv directory was renamed to `venv-…-py311-2a519198`.
- `lib/python3.13` became `lib/python3.11`.
- `bin/python` now points to `/usr/bin/python3`.
- `pyvenv.cfg` now records `version_info = 3.11.2`.
- `.daemon-metadata.json` and `.python-cmd-cache` were re-pointed at the py311
  path.

The incident probe reproduces INCIDENT.md item 3 exactly:

```
3.13.5 …  /  no_site 0  /  sys.path = /usr/lib/python313.zip, /usr/lib/python3.13, /usr/lib/python3.13/lib-dynload
```

**12:04:38. SessionStart hook** (`bash .claude/hooks/session-start < sessionstart.json`, source=startup), rc 0. On stderr:

- `resolve_venv`: the candidate failed with "interpreter drift: … pyvenv.cfg
  records Python 3.11 but … now runs 3.13, so the venv's site-packages is
  invisible -- skipping".
- `no usable venv found`.
- The Task 2.4 diagnosis printed the interpreter as 3.13.5, `version_info` as
  3.11, and site-packages on `sys.path` as "no". It reported the package as not
  importable, named the cause "interpreter changed under the venv (3.11 ->
  3.13)", and gave `bin/hooks-daemon repair` as the fix.

The `additionalContext` on stdout said: "clone present, venv missing … A BUILD
HAS STARTED — nothing to do but wait … Build log:
untracked/.venv-bootstrap-…-py313-0d6d49c6.log".

**12:04:42. Build finished.** The log contained:

```
venv bootstrap started 2026-10-31T12:04:38Z (python /usr/bin/python3.13, … bound 900s)
→ ensure_venv: creating venv at …/untracked/venv-…-py313-0d6d49c6
✓ venv bootstrap SUCCEEDED: …-py313-0d6d49c6/bin/python resolves for this path. The next hook starts the daemon.
```

`.venv-bootstrap.result` then read:

```
result=succeeded
finished_at=2026-10-31T12:04:42Z
exit=0
log=…/untracked/.venv-bootstrap-…-py313-0d6d49c6.log
```

The new `pyvenv.cfg` has `version_info = 3.13.5`, and `.python-cmd-cache` was
re-pointed at the py313 venv.

**12:04:50. Next PreToolUse hook**, rc 0, after 3 s. It returned a normal
daemon response, and `bin/hooks-daemon status` reported `Daemon: RUNNING`
with 31/31 listeners. The daemon process's `/proc/<pid>/cmdline` was:

```
…/untracked/venv-…-py313-0d6d49c6/bin/python -m claude_code_hooks_daemon.daemon.cli --project-root …/drift-demo start
```

To confirm the healed daemon guards, a PreToolUse for `git reset --hard HEAD~1` returned `"permissionDecision": "deny"` with rule `R-GIT-RESET-HARD`.

## Variant A: drift at the current key (FAIL)

**Drift applied.** Only `pyvenv.cfg` `version_info` was changed, from 3.13.5 to
3.11.2, in the py313-keyed venv. Site-packages stays at `lib/python3.13`.

**12:03:43. PreToolUse hook.** Drift was detected the same way and the build
started; the message read "A BUILD HAS STARTED".

**12:03:44. Build failed**, with `result=failed exit=1`. The log contained:

```
→ venv bootstrap: building the venv … (fingerprint …-py313-0d6d49c6)
resolve_venv: candidate …-py313-0d6d49c6/bin/python … interpreter drift … -- skipping
✗ venv bootstrap FAILED: no venv resolves for … after the build (ensure_venv exit 1).
✗   Hooks will not retry until pyproject.toml, uv.lock, the Python interpreter or the uv binary changes.
```

There is no "creating venv" or "stamp mismatch — rebuilding" line, so nothing
was rebuilt. A marker file `.venv-bootstrap-…-py313-0d6d49c6.failed` was
written (`inputs=1e563e9cb7042cab`).

**Next hook.** It reported "THE LAST AUTOMATIC BUILD OF THIS VENV FAILED. Its
log says why: <log> … retry in the foreground: bin/hooks-daemon repair". The
report itself is right: there is no loop, and the log path is named.

**`timeout 900 bin/hooks-daemon repair`.** rc=1, with the same "venv bootstrap
FAILED … ensure_venv exit 1" and then "❌ hooks-daemon repair: the venv for
this project path could not be built". After the repair, `pyvenv.cfg` still
said 3.11.2.

## Findings

1. **The reuse check in the venv build ignores interpreter drift**, which
   causes the Variant A lockout. `_ensure_venv_build`
   (`scripts/install/venv.sh:1390`) reuses the venv whenever `_venv_is_fresh`
   (`venv.sh:1196-1228`) returns 0. `_venv_is_fresh` trusts a `lock_hash`
   match (`venv.sh:1209-1213`) or a stamp match (`:1223`) and never asks
   `venv_python_usable`. As a result, a venv at the build's own target path
   that the version-aware resolver rejects is "reused". Then the success check
   (`scripts/venv_bootstrap.sh:284-334`) correctly fails, the build records
   `.failed`, and hooks stop retrying.

   `repair` runs the same path, so it cannot clear the state either. Only
   `_VENV_FORCE_REBUILD=1` (`venv.sh:1202`, set only by `repair --rebuild`)
   bypasses the reuse, and the wrapper takes `--rebuild` only for a venv that
   RESOLVES.

   This is an uncaught instance of the `venv_interpreter_trust` class. The DBF
   report item (f) covered the build's success check but not this reuse
   check. Two routes reach this shape:

   - a venv rebuilt in place by a different interpreter (for example a
     hand-run `pythonX.Y -m venv --clear`, as in the owner's incident fix);
   - a fingerprint computed from a different interpreter than the one
     `bin/python` links to.

   It was not fixed here, per the brief.

2. **`bin/hooks-daemon status` gives no information when no venv resolves.**
   It exits 5 with only the resolver's "could not resolve a usable venv"
   text, so it does not show the Task 2.7 "Last venv build / Build log"
   lines in exactly the daemon-down state where they matter. When the venv
   resolved and the daemon was stopped, `status` did print them. This is
   relevant to Task 2.5.

3. **Minor: one diagnosis contradicts itself in Variant A.** `diagnose-venv`
   built the site-packages path from the `pyvenv.cfg` minor
   (`lib/python3.11/site-packages`, reported as "not on sys.path"), yet it also
   reported `importable: yes`. Variant B was consistent.

4. **Minor: after self-heal, the drifted py311 venv is left in place as an
   orphan, and `untracked/lsp-venv` still points to it.** This is the same
   residue Task 3.1 pruned by hand.

## Cleanup

- `bin/hooks-daemon stop` in the scratch tree printed "Daemon stopped".
- `git worktree remove --force /workspace/.claude/worktrees/drift-demo`
  returned rc=0.
- `git worktree list` no longer lists the scratch tree.
- `pgrep -af '[d]rift-dem[o]'` found no processes.
- /workspace's working tree is unchanged apart from this report and the
  untracked evidence directory.

# Incident record: self-install daemon locked out by a Python version change

Dogfooding failure recorded at the owner's request on 2026-10-29, while the
context was still live. This is the evidence base for PLAN.md; the plan's
tasks cite it.

## What happened

1. The host or container image changed underneath the workspace. The system
   Python moved from **3.11.2** to **3.13.5**: `/usr/bin/python3` and
   `/usr/bin/python3.13` are the only interpreters left, and there is no 3.11.
2. The daemon venv `untracked/venv-workspace-py311-2a519198` was built by
   `uv 0.13.1` against 3.11.2. Its `pyvenv.cfg` said `home = /usr/bin`,
   `version_info = 3.11.2`.
3. The venv's `bin/python` resolves through `/usr/bin` and now **runs 3.13**.
   A 3.13 interpreter looks for `lib/python3.13/site-packages`, which did not
   exist. So the venv's own site-packages never reached `sys.path`. The owner's
   probe showed `no_site = 0` and a `sys.path` holding only the system paths:
   `/usr/lib/python313.zip`, `/usr/lib/python3.13` and
   `/usr/lib/python3.13/lib-dynload`.
4. Everything the daemon needs was still on disk, in
   `lib/python3.11/site-packages`. That included the correct editable link
   `__editable__.claude_code_hooks_daemon-3.71.0.pth`, whose content is
   `/workspace/src`, and the 3.71.0 dist-info. None of it was read.
5. Every daemon start therefore failed with:
   `Error while finding module specification for 'claude_code_hooks_daemon.daemon.cli' (ModuleNotFoundError: No module named 'claude_code_hooks_daemon')`.

## Why the session could not recover itself

- **The fail-closed guard denied every diagnostic.** While the daemon was
  unreachable, every tool call was refused: Read, `ls`, `git log`, `cat`, and
  sub-agents too, since they hit the same hooks. The only exceptions were the
  exact strings `.claude/hooks-daemon/bin/hooks-daemon restart` and `repair`.
  The agent could not inspect the venv, the config or the git history. Every
  fact above came from the owner running `!` commands by hand.

- **`restart` and `repair` run through the same broken interpreter.** Both
  failed with the identical `ModuleNotFoundError`. Plan 00456 ("missing venv
  self heals and repair runs without one") does not cover this case: here the
  venv EXISTS but its interpreter no longer matches it.

- **The background rebuild appeared to run, but never fixed anything.** Over many hours the
  stop hook alternated between:

  - "Hooks daemon not running"
  - "clone present but venv missing for this project path — a venv build is
    running in the background — do not install/force".

  At the time it looked as if each build finished and the restart still failed.
  The Phase 1 investigation found something different: no hook build ran
  during the drift at all. "Not recorded here" means the lock holder was not a
  hook build. Even a build that did run would have picked the py311 venv in its
  success check (`venv_bootstrap.sh:279`) and reported success. The "venv
  missing" text came from `init.sh:2901-2911`, which reports a venv that
  RESOLVES but will not START as "missing" whenever any process holds the build
  lock. That explains the alternation.

- **The resolvers disagree.** The wrapper, `init.sh`, `restart` and `repair`
  share one resolver. It finds venvs by lock hash first (`paths.py:1197-1243`)
  and only checks that `import sys` runs, so the drifted py311 venv kept
  resolving. The builder and the Python `repair` key on the Python fingerprint
  (Plan 00099). The wrapper takes its no-venv `repair` path only when
  resolution fails (`bin/hooks-daemon:270`), so `repair` ran the broken
  interpreter and the self-heal never triggered.

- **The stop hook blocked every stop.** With the daemon down, every stop was
  blocked with "Hooks daemon not running - protection not active". The
  `[awaiting-human]` declaration, the stand-in cron and the stop explanation
  all depend on the daemon, so none of them could take effect. The agent
  answered well over a hundred identical blocks over many hours. That is
  unbounded token burn with zero value, and it buried the owner's messages.

## Agent misdiagnoses (recorded so the guidance can prevent them)

1. **"The package is missing — please `pip install -e /workspace`".** This was
   technically the right command, but it was framed as installing the daemon.
   In self-install mode that is confusing: the owner replied "YOU ARE THE HOOKS
   DAEMON". The real question, whether the interpreter can see the venv's
   site-packages, was never asked.
2. **"Self mode was switched off".** This was the owner's hypothesis, and it was
   ruled out: `self_install_mode: true` is still set at
   `.claude/hooks-daemon.yaml:7`, and no recent commit touches it.
3. **"Plan 00554 (Rust relay default) broke the launcher".** The agent suggested
   this because every recent launcher and hook commit belonged to 00554. The
   owner reverted merge `654ec98e1` as `bce74f191`, and nothing changed. It was
   re-applied as `0bef7acaa`. That pair of local commits is net-zero on the
   tree.

The single probe that found the cause was:

```
<venv>/bin/python -c "import sys; print(sys.version); print(sys.flags.no_site); print(*sys.path, sep='\n')"
```

It should have been the first diagnostic, and the daemon should run it itself
when a start fails.

## The fix the owner applied

```
python3 -m venv --clear /workspace/untracked/venv-workspace-py311-2a519198 \
  && /workspace/untracked/venv-workspace-py311-2a519198/bin/python -m pip install -e /workspace \
  && /workspace/.claude/hooks-daemon/bin/hooks-daemon restart
```

Result: "Daemon started successfully (PID: 510367)", with 31/31 per-event
listeners active.

**Correction from the Phase 1 investigation** ([report](subagent-reports/261029-phase1-investigation.md)): the
owner's command is NOT what brought the daemon back. PID 510367 runs
`untracked/venv-workspace-py313-0d6d49c6/bin/python` (confirmed from
`/proc/510367/cmdline`). A hook-started build, logged at
`untracked/.venv-bootstrap-workspace-py313-0d6d49c6.log`, succeeded during
the fix. Probably `venv --clear` briefly left the py311 path unresolvable, so
the wrapper fell through to the build path. The real lesson: the self-heal
works the moment the drifted venv stops resolving. During the drift, the
resolver kept resolving it because its usability probe only checks that
`import sys` runs.

**Residue, to be cleaned up by this plan:**

- `untracked/venv-workspace-py311-2a519198` is an unused orphan. It was
  rebuilt by stdlib `venv` under 3.13 and has no `.daemon-metadata.json`.
  Prune it rather than re-key it.
- The live py313 venv was built without the `dev` extras, so QA, which uses the
  same resolved venv, had no pytest, mypy or black. They were installed by hand
  with `uv pip install --python <venv>/bin/python -e '.[dev]'`. A self-install
  bootstrap should install them itself.

## Related plans

- 00099 Python-fingerprint venv isolation: the keying that made the resolver
  call this venv "missing".
- 00313 venv resolver cross-view reuse.
- 00456 missing venv self-heals and repair runs without one: the closest
  precedent, but it does not handle interpreter drift.
- 00517 daemon version SSoT and no stale venvs: "stale" should include
  "built for a Python that no longer exists".
- 00100 venv SSoT consolidation (Dormant): the resolver disagreement above is
  exactly its subject.

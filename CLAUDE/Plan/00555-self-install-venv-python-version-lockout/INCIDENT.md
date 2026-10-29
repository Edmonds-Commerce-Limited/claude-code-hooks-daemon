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

- **The background rebuild never produced a usable venv.** Over many hours the
  stop hook alternated between:

  - "Hooks daemon not running"
  - "clone present but venv missing for this project path — a venv build is
    running in the background — do not install/force".

  Each build finished, yet the restart afterwards failed exactly the same way.
  After the incident `untracked/` held only `lsp-venv` and the py311 venv, so
  no 3.13 venv was ever left behind. The build log was "not recorded here
  (another process … holds the venv build lock)". Why the build failed, or
  where it wrote, is **unknown and must be investigated**.

- **Two venv resolvers disagree.** The hook-side health check decided the venv
  for this project path was MISSING, presumably because it keys or fingerprints
  on the running Python (Plan 00099). Yet the wrapper kept launching the old
  `py311` path. One component treated the venv as absent; the other used it
  regardless.

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

**Residue left by the fix, to be cleaned up by this plan:**

- The directory is still NAMED `py311` but now holds a **3.13.5** venv built by
  stdlib `venv` rather than uv. Its `pyvenv.cfg` now records `version = 3.13.5`
  and `executable = /usr/bin/python3.13`. The name is a lie.
- Only runtime dependencies were installed. The `dev` extras (pytest, mypy,
  black, ruff and so on) are not in this venv. QA may fail, or may fall back to
  a different environment.

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

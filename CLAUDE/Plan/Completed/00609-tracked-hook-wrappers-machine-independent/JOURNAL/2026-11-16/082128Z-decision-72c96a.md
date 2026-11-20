## 08:21 · decision · —

Is ignoring HOOKS_DAEMON_VENV_PATH in a worktree intended, and what is the trust model?

Read from the code (no behaviour changed by this entry).

What the code does. The wrapper does NOT ignore HOOKS_DAEMON_VENV_PATH in a worktree, and I found no worktree-specific branch that drops it. init.sh `_resolve_python_cmd` delegates to scripts/lib/resolve_venv.sh `resolve_venv_python`; `_rv_pick_python` tries HOOKS_DAEMON_PYTHON first, then `$HOOKS_DAEMON_VENV_PATH/bin/python(3)` if it is usable, and only then the ranked scan of `$HOOKS_DAEMON_ROOT_DIR/untracked/venv-*`. daemon/paths.py `resolve_existing_venv_python_with_diagnostics` has the same precedence (step 1 is the override; it is exempt from the slug and fingerprint checks that steps 2 and 4 apply). When either variable is set, the hot-path cache is neither read nor written (Plan 00466 N37), so an override cannot answer for a later call that sets none.

Where the "ignored" behaviour actually is. It is in my own test helper `_own_venv_not_ready` (tests/integration/test_forwarder_socket_stdin.py), which pops the variable before resolving. That is a deliberate test choice: the test asks "has THIS checkout built its own venv?", and a runner that exports HOOKS_DAEMON_VENV_PATH (this one points at the main checkout's venv) would otherwise make a worktree look ready while the wrapper under test, started without that variable, still fails closed. So the test ignores it; the wrapper honours it. A worktree separately lacks the gitignored .claude/hooks-daemon.env, so it can reach the "Not installed" answer (init.sh near line 1546) before venv resolution matters; that is a different cause.

Why per-checkout venvs are the default. The venv is keyed per project path (Plan 00099, slug Plan 00313), so a host view and a container view, or two worktrees, never share an interpreter whose installed source, lock hash or base Python belongs to another tree. The scan steps enforce that. Trust model: an operator who sets HOOKS_DAEMON_VENV_PATH is explicitly choosing, and is trusted; the guard against a stray variable is that the default resolution never reads it from anywhere but the process environment, and a shared override is not slug-checked.

What a shared venv trades away. Faster worktree start (no background build, no fail-closed window) against: the daemon running code installed from another tree (an editable install resolves to that tree's src, not the worktree's), no lock_hash match check, the stale-venv and wrong-Python detection of step 2 bypassed, and a stray variable silently pointing a project at another checkout's interpreter.

Open question. Should the integration tests honour HOOKS_DAEMON_VENV_PATH (so a runner with a shared venv exercises the wrapper as it would run), or keep judging the checkout's own venv as now? And is a slug check on the override wanted? Not decided here; behaviour is unchanged.

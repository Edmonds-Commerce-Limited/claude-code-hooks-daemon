# Why relay_binary_checker left no repair trace (aarch64 ccy box, 3.74.0)

Read-only code investigation. Each item: VERIFIED-IN-CODE (the route exists as described)
vs UNVERIFIED-ON-BOX (whether it happened there was not checked).

## Fixed facts from the code

- The only caller of `start_relay_repair` is the SessionStart handler
  (`handlers/session_start/relay_binary_checker.py:146`). No daemon-startup, CLI or
  `status` path starts a repair (grep across `src/`, `.claude/init.sh`, `.claude/provision.sh`).
- `status` WARNING is computed in the CLI process from the filesystem alone, not by the
  daemon or this handler: `daemon/cli.py:1602-1616` (`_print_transport_status_warnings` ->
  `missing_configured_relay_binary`), printed in both the RUNNING (`:1671`) and NOT RUNNING
  (`:1654`) branches. So the WARNING says nothing about whether SessionStart ever ran the checker.
- Path agreement: binary path = `get_untracked_dir(root)/bin/hooks-relay`
  (`install/relay_deploy.py:127-138`); state = `get_untracked_dir(root)/relay-repair/<key>.state`
  (`install/relay_repair.py:94-101`, called with `get_untracked_dir(root)` at
  `relay_binary_checker.py:150`). Same function (`daemon/paths.py:1582-1603` ->
  `daemon/install_layout.py:44-56`), which reads no environment variable
  (no `HOOKS_DAEMON_ROOT_DIR` or sibling-view override). The checker's root is
  `ProjectContext.project_root()` = parent of `.claude/` of the config
  (`core/project_context.py:252-253`), i.e. `/workspace`. For a client root (no
  `/workspace/src/claude_code_hooks_daemon`) both resolve to
  `/workspace/.claude/hooks-daemon/untracked`. **Route "state written elsewhere" is ruled out in code.**
- Once the handler reaches line 146, a file is created at every exit except one:
  `O_EXCL` claim is written (`relay_repair.py:209-217`) before spawn; spawn failure rewrites it
  as FAILED (`:230-236`); `FileExistsError` means one already exists (`:210-211`).
  The only no-file exit is `mkdir`/`open` OSError (`:212-213`), which is returned into the
  SessionStart context only and is **not logged** (no `logger` call on that branch).

## Candidates, ranked

1. **SessionStart was answered by init.sh's error path, never by the daemon (most likely).**
   VERIFIED-IN-CODE, UNVERIFIED-ON-BOX. On VENV_MISSING with a readable clone version,
   `ensure_daemon` calls `_venv_self_heal` (`.claude/init.sh:3609-3616`), which only starts a
   DETACHED build and returns (`init.sh:3045-3061`), then `ensure_daemon` `return 1`
   (`init.sh:3645`). The forwarder then emits `daemon_startup_failed` and `exit 0`
   (`.claude/hooks/session-start:78-82`) without `send_request_stdin`. The daemon is started
   later by some other event's `ensure_daemon` once the venv exists. Claude Code does not re-fire
   SessionStart, so no handler ran in that session; nothing re-runs the checker until the next
   startup/resume/clear/compact. This matches "the daemon was started by init.sh after a venv self-heal".
2. **State dir not creatable** (`relay_repair.py:212-213`). VERIFIED-IN-CODE, UNVERIFIED-ON-BOX,
   low likelihood: the daemon writes its own pid/logs under the same untracked dir, so it is
   normally writable. If it fired, the session's SessionStart context carried
   "the repair state file ... cannot be created", and nothing went to the daemon log.
3. **Handler excluded by the client config.** VERIFIED-IN-CODE, UNVERIFIED-ON-BOX, low.
   `default_enabled` is True (`core/handler.py:92`). An absent block is enabled
   (`handlers/registry.py:263`). The template ships it `enabled: true`
   (`.claude/hooks-daemon.yaml.example:834-836`, `daemon/init_config.py:490`). Only an explicit
   `relay_binary_checker: {enabled: false}` or a `session_start` `enable_tags` that names none of
   advisory/environment/non_terminal (`relay_binary_checker.py:94-98`), or a `disable_tags`
   that names one of them, would drop it (`registry.py:264-299`).
4. **Exception before line 146.** Low. Config errors are caught (`relay_binary_checker.py:125-136`).
   An uncaught YAML error would also make `status` print "transport config unreadable"
   (`cli.py:1598-1604`), and it did not. `relay_fix_subcommand` and
   `daemon_cli_command` cannot raise on aarch64 (`utils/relay_host.py:16-21,57-63`;
   `utils/cli_command.py:205-209`).
5. **`ProjectContext` uninitialised / config not a file.** Ruled out for a running daemon:
   `controller.py:353-356` initialises it from `workspace_root/.claude/hooks-daemon.yaml`.
   `initialize` raises (daemon would not start) rather than leaving it false
   (`project_context.py:225-232`).
6. **Resumed sessions skipped.** Ruled out: `matches` returns True for every source
   (`relay_binary_checker.py:113-115`), and nothing in `core/session_start_tiers.py` filters by source.
   (Note the acceptance-test text at `:183` says "new session only", which is stale relative to `matches`.)
7. **Version / once-per-cause gate.** Not a no-file route: the key only changes the filename
   (`relay_repair.py:88-91`), and an existing claim is itself a file. 3.74.0 contains the repair
   (introduced by a153ce94d, first tag v3.71.0).

## Read-only confirmation on the box (candidate 1)

```
grep -n "daemon_startup_failed\|venv is being built\|A BUILD HAS STARTED" ~/.claude/projects/*/<session-id>.jsonl
ps -eo pid,lstart,args | grep '[c]laude_code_hooks_daemon'
cat .claude/hooks-daemon/untracked/.venv-bootstrap.result
```

The first command is the decisive one: does the session transcript's SessionStart hook output show
the init.sh venv-missing/building message instead of daemon context? If it does, candidate 1 is
confirmed. The `ps` start time is later than the session's first transcript timestamp and close to
the bootstrap `finished` time, which corroborates it. For candidate 3:
`grep -n "relay_binary_checker\|enable_tags\|disable_tags" .claude/hooks-daemon.yaml`, or
`.claude/hooks-daemon/bin/hooks-daemon handlers`.

## Proposed fix location

- Primary (in scope for Plan 00608): provision the relay inside `.claude/provision.sh` so a fresh
  clone never depends on a later SessionStart to repair it.
- Defence: make the repair also start at daemon startup. Add a deferred startup step in
  `daemon/controller.py` (`initialise`'s `defer_nonessential_startup` set, `:478`, drained via
  `take_deferred_startup`, `:516`) that calls `start_relay_repair` with the same arguments as
  `relay_binary_checker.py:146-153`. The once-per-cause `O_EXCL` claim already makes a
  double trigger safe. The checker then keeps the reporting role.
- Small: log the `relay_repair.py:212-213` failure (it is the only silent no-file exit), and
  have `status` print the repair state path or "no repair attempted" next to its WARNING, so that
  "warned but never attempted" can be told apart on the box.

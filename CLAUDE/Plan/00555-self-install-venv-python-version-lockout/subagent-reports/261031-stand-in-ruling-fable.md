# Stand-in ruling: Plan 00555 Tasks 2.5 and 2.6

**This is the stand-in's ruling, not the owner's.** The owner did not answer
within the stand-in window, so a `model: fable` sub-agent chose between the
engineering options laid out in
`JOURNAL/2026-10-31/125627Z-blocker-de5068.md`. It decides nothing else:
DBF-REPORT decisions 1 to 3 remain with the owner. The owner may overturn
either choice below; the implementer should treat both as provisional until
the owner has seen them.

Evidence read: PLAN.md, INCIDENT.md, the blocker and action journal entries,
`init.sh` (recovery carve-out at 130-384, `emit_hook_error` standard branch at
708-733 and 1140-1153, the python transport's deny at 3467-3560,
`forward_stop_event` at 3848-3886), `bin/hooks-daemon` (`diagnose` arm at
315-369 and 418-423), `src/claude_code_hooks_daemon/utils/cli_command.py`
(`_RECOVERY_SUBCOMMANDS` at 280), `relay/hooks_relay.rs` (header: the relay
hands PreToolUse to init.sh's carve-out via `judge_via_fallback`, so there is
no third copy of the list), `handlers/stop/auto_continue_stop.py` (the
`[awaiting-human]` regex at 220-235), `utils/secret_file_matching.py`
(`DEFAULT_PROTECTED_PATTERNS` at 86-89) and
`scripts/qa/fail-open-boundaries.yaml`.

## Task 2.5 — ruling: option (b)

Widen the daemon-down fail-closed allow-list to read-only diagnostics AND the
`hooks-daemon diagnose` verb.

### Why (b) and not (a)

- `diagnose` is the only item that answers the incident's actual question
  ("can this interpreter see the venv's site-packages?"). Read/ls/cat/git let
  an agent gather facts; `diagnose` runs the probe INCIDENT.md says should
  have been the first diagnostic, and names the one-line fix. Without it,
  (a) leaves the agent reconstructing the diagnosis from `pyvenv.cfg` by
  hand, which is exactly what went wrong for hours.
- Its risk is lower than the rest of (a). It is already merged (`27fd1725f`)
  as a venv-free arm of the wrapper that runs stdlib-only `paths.py diagnose-venv` under each venv's own interpreter, bounded by `timeout $IMPORT_PROBE_TIMEOUT`, and only prints. It needs no new matcher: it is one
  more entry in a list whose exact-match, launcher-resolving shape
  (`_is_daemon_recovery_command`) has already been through Plan 00466's
  reviews. `cat`/`ls`/`git` by contrast need a NEW argument grammar.
- Cost of adding it to the list is one word in two files that already must
  stay in step: `_RECOVERY_SUBCOMMANDS` in `init.sh` (line 170) and in
  `cli_command.py` (line 280). The relay needs nothing.

### Allow-list boundaries the stand-in accepts

Scope: ONLY the STANDARD daemon-down branch — the same gate the current
carve-out uses (`emit_hook_error` 722-727: not CI_ENFORCED, not
REPO_UNCONFIGURED, not VENV_MISSING, not NOT_INSTALLED, not
VERSION_MISMATCH) and the python transport's `PreToolUse` deny (3496-3542).
`ci_enabled: true` stays a hard deny of everything but the recovery commands.
The provisioning deny (Plan 00477) is untouched.

Judgement must be ONE function, defined once, used by all three deny sites
(`emit_hook_error`, `send_request_stdin`'s python, and the relay's
fallback path which already lands in init.sh). The existing
`_hooks_daemon_recovery_py` string is the place: extend
`_is_daemon_recovery_command` into `_is_daemon_down_permitted(hi, ...)`, keep
the recovery check as its first clause. Keep `cli_command.py`'s copy in
parity and extend `tests/unit/utils/test_cli_command.py`'s parity test.

Permitted while the daemon is down, each as an exact-shape match:

1. **Recovery commands** — unchanged: the six existing subcommands plus
   `diagnose`, with the same launcher-resolution rule (the file the spelling
   runs must be THIS install's `bin/hooks-daemon`).

2. **Tool `Read`** — `tool_input.file_path` must be absolute, must resolve
   (realpath, following symlinks) to a regular file INSIDE the project root
   or the daemon root, and must NOT match the protected-path matcher below.
   No other tool is permitted: not `Grep` (a content oracle the daemon
   normally denies on protected paths, in every output mode), not `Glob`
   (not needed for the incident), never `Write`/`Edit`/`NotebookEdit`,
   and `Task`/`Agent` is pointless anyway (sub-agents hit the same hooks).

3. **Bash, read-only shapes.** The whole command, after stripping only
   spaces and tabs, must be printable and contain NONE of
   `| ; & $ \` > < ( ) { } * ? \[ ~ ' " \\ newline\`. That single rule removes
   pipes, chaining, substitution, redirection, globbing, tilde and quoting;
   arguments are then plain whitespace-split tokens. Permitted heads:

   - `ls` — flags from a fixed set only: `-l -a -A -h -t -r -1 -d -la -al -lh -lah -lt -ltr -ltra` (any order of those letters; NO `-R`, which is
     a tree walk, and no long options). Zero or more path arguments, each
     judged as in (2) except that a directory is allowed. `ls` reveals
     filenames only, so a protected file's NAME appearing in a listing is
     accepted (the daemon's own guard accepts `ls` of a parent today).
   - `cat` — NO flags at all (no `-`, no `--`). One or more path arguments,
     each must be absolute or cwd-relative, resolve to a REGULAR file (`-f`
     after realpath; a FIFO or device would hang the Bash tool), lie inside
     the project root or daemon root, and not match the protected matcher.
     Also permit `head -n N <path>` and `tail -n N <path>` with the same path
     rule, N a plain integer — the build log and daemon log are large, and
     the pipe blocker's own guidance says to take the path as an argument.
   - `git log` — permitted options: `--oneline`, `-n <int>`, `-<int>`,
     `--stat`, `--format=<...>`/`--pretty=<...>` (value contains no shell
     metacharacter, already guaranteed), `--no-pager`, `--all`,
     `--decorate`, `--graph`, `--since=<...>`, `--until=<...>`,
     `--author=<...>`, `--grep=<...>`, a revision range token, and `--`
     followed by path tokens. DENIED: `-p`/`--patch`/`-u` (would print the
     content of a tracked protected file), `--output=`, `-c`, `-C`,
     `--git-dir`, `--work-tree`, `--exec-path`, `--config-env`, any
     `KEY=value` env prefix, and any option not listed.
   - `git status` — options `-s`, `--short`, `-b`, `--branch`, `-sb`,
     `--porcelain`, `--porcelain=v1|v2`, `--untracked-files=<...>`,
     `--ignored`, `--no-pager`; path tokens after `--`. Same `-c`/`-C`/
     git-dir/env-prefix denial. No `git diff`, `git show`, `git blame`,
     `git grep` — not asked for, and `show`/`grep` are content oracles.
   - The `git` head must be bare `git` (no path, so PATH resolution is the
     same as the daemon's).

4. **Protected-path matcher (how `cat`/`Read` of a protected path stays
   refused).** A stdlib-only function inside the same python string, applied
   to every realpath'd path AND to every raw token (so `cat .claude/block-words.secret` and `cat ./x/../.claude/block-words.secret`
   both fail). It denies when the basename matches any of
   `DEFAULT_PROTECTED_PATTERNS` (`*.secret*`, `.vault-pass*`,
   `*.vault-password`), when the path is `.claude/hooks-daemon.env` or
   anything under `.claude/hooks-daemon/` other than `bin/`, when the path is
   under `untracked/events*/` or a `*.sock`, or when it matches the project's
   configured `protected_paths`. Bash cannot parse the YAML, so the
   configured list comes from a SNAPSHOT the healthy daemon writes at startup
   and on config reload: `untracked/.protected-paths.snapshot`, one glob per
   line, resolved by `secret_file_matching.resolve_protected_patterns`. If
   the snapshot is missing or unreadable, the matcher uses the defaults AND
   denies every `Read`/`cat` of anything under `.claude/` except
   `.claude/hooks-daemon.yaml` and `.claude/settings*.json`, and says in the
   deny reason that the snapshot is absent. Fail closed on any exception in
   the matcher: an unresolvable path is denied.

5. **The deny message** must name what IS permitted: the restart/repair
   lines it names today, plus `diagnose`, plus one line "read-only
   diagnostics (Read, ls, cat/head/tail of a project file, git log, git
   status) are allowed while the daemon is down; everything else is denied".
   `_recovery_advice` is the place.

Nothing in this list may write, exec, or leave the project tree; if the
implementer finds a permitted shape that can, remove the shape rather than
patch around it.

### Risks the implementer must test (red first, as the project requires)

- Parity: `init.sh`'s list and `cli_command.py`'s list differ by one entry
  → the parity test fails.
- Each metacharacter in the deny set, alone and inside an otherwise-valid
  command, is denied (`cat a; rm -rf x`, `cat $(x)`, `cat *`, `cat ~/x`,
  `cat 'a'`, a newline inside the command, `git log --output=/tmp/x`).
- Protected paths: direct, relative, `..`-traversal, via symlink inside the
  repo, basename-only match (`foo.secret.bak`), snapshot present with a
  custom glob, snapshot absent (defaults plus `.claude/` lockdown).
- Path outside the project root (`cat /etc/passwd`, `Read` of `/proc/...`)
  is denied; path to a FIFO/device is denied; a missing file is denied (do
  not let `cat` of a non-existent path through just because it is
  harmless).
- `ls -R` denied; `ls` of the project root allowed; `git log -p` denied;
  `git -c core.pager=... log` denied; `GIT_DIR=... git log` denied.
- `hooks-daemon diagnose` is allowed by the exact-spelling rule only, with
  the same launcher-resolution behaviour as `restart` (relative spelling
  resolved against `cwd`, planted `bin/hooks-daemon` rejected).
- The CI_ENFORCED, NOT_INSTALLED, VENV_MISSING and NEEDS_PROVISION branches
  are byte-for-byte unchanged (existing tests).
- python3 missing → `_hooks_daemon_static_deny` still fires; the new
  judgement never changes the shape of the python-less path.
- `scripts/qa/check_fail_open_inventory.py`: if the scanner flags the new
  branch, add a row to `fail-open-boundaries.yaml` with `verdict: fail-open`,
  `caller_controlled: true` (the agent can stop the daemon with the permitted
  `hooks-daemon stop`), and a `trace` naming the deny-reason text.
- Relay: with the relay binary present, a daemon-down PreToolUse still
  reaches init.sh with stdin intact (connect-fail path) so the new
  allow-list is judged; the relay's own `deny_pre_tool_use_json` is reached
  only mid-exchange and must stay a deny.

## Task 2.6 — ruling: option (a), N = 3

Bound the daemon-down stop block: allow the stop after 3 consecutive
daemon-down blocks in one session, and allow it immediately when the stop
message carries `STOPPING BECAUSE: [awaiting-human]`.

### Why (a) and why 3

- Unbounded (b) produced the incident's worst cost: well over a hundred
  identical blocks, zero information after the first, and the owner's
  messages buried. A block that cannot be acted on is not enforcement.
- The block exists to make the agent TRY to recover before it ends the turn.
  Block 1 tells it protection is down and names restart/repair. Block 2
  means its first recovery attempt failed and it should try `repair` /
  `diagnose`. Block 3 means the session cannot fix it. After that, every
  further block is pure token burn. N=1 would let the agent stop without
  trying; N=2 gives no room for restart-then-repair. 3 is the smallest N
  that still enforces "attempt recovery". Make it a constant in init.sh,
  not configurable: a configurable N invites "set it to 1".
- Liveness traded away: nothing of substance. With the daemon down,
  PreToolUse still denies every write and exec (Task 2.5 permits only
  read-only shapes), so an allowed stop ends a turn that could do nothing
  else. A stop is not a bypass of any guard that protects the tree.

### Design the stand-in accepts

- **What counts as "identical":** the CLASS of block, not its text. The
  incident alternated between "Hooks daemon not running" and "clone present
  but venv missing", and `_last_build_note` varies the text. Count every
  consecutive Stop/SubagentStop block whose cause is the daemon being
  unreachable: the STANDARD "not running" reason, VENV_MISSING, and
  NOT_INSTALLED, from both `emit_hook_error` and the python transport's
  connect-failure branch. EXCLUDED from the count: CI_ENFORCED (explicit
  policy, stays unbounded), `invalid_hook_input` (daemon healthy, must not
  be allowed through by counting), NEEDS_PROVISION (Plan 00477's own
  contract), and `socket_timeout` (already allows).
- **State:** a counter file beside the passthrough flag,
  `untracked/.daemon-down-stops.<session_id>` (session_id from hook_input;
  `_passthrough_flag_path` is the pattern), holding the count. Keyed by
  session so a stale count from a previous session never grants the first
  stop of a new one. Reset to zero (delete the file) on the `ensure_daemon`
  success path where the passthrough flag is already removed, and whenever
  `send_request_stdin` receives a parsable daemon response for any event.
  If the file cannot be written: keep blocking and say so on stderr (the
  pre-existing behaviour, honest about why).
- **Allowed stop shape:** exit 0 from `forward_stop_event` with
  `{"systemMessage": "..."}` saying: the daemon has been down for 3
  consecutive stops, the stop is allowed so the session is not wedged,
  protection was NOT active for this stop, and the fix line
  (`restart`/`repair`/`diagnose`). Also append one line to
  `untracked/.daemon-down-stops.log` (session_id, UTC time, count, reason
  class) so the daemon's next SessionStart / `status` can surface that
  unguarded stops happened. Never emit `decision: approve` — `{}` plus
  `systemMessage` is the universal shape.
- **`[awaiting-human]`:** Stop hook_input carries `transcript_path`. A
  stdlib-only reader (python3 is already the transport dependency) reads
  the LAST 256 KiB of the JSONL, walks lines from the end, takes the last
  `role == "assistant"` message's text blocks, and applies the SAME regex as
  `auto_continue_stop._AWAITING_HUMAN_DECLARATION`
  (`STOPPING BECAUSE:\s*\[awaiting-human\]`). A match allows the stop at any
  count, with a systemMessage saying the declaration was honoured but, with
  the daemon down, no awaiting-human marker was armed and no stand-in cron
  was scheduled. Any failure to read or parse the transcript means "no
  declaration" and the count rules. The token in a user message or tool
  result never counts.
- Apply the bound to `SubagentStop` with the same counter key (session_id
  plus event name), same N.

### Risks the implementer must test

- The first and second daemon-down blocks still block (exit 2, reason on
  stderr); the third allows (exit 0, valid JSON, systemMessage present).
  Existing assertions on the block text (e.g.
  `tests/integration/test_venv_build_last_result.py`) keep passing for
  blocks 1 and 2.
- Count resets: daemon comes back between blocks → next daemon-down block is
  count 1 again; new session_id → count 1; counter file deleted by hand →
  count 1.
- Alternating reasons (not running → venv missing → not running) count as
  three, matching the incident.
- `invalid_hook_input` and CI_ENFORCED never increment and never allow;
  `socket_timeout` still allows at any count without touching the counter.
- Unwritable `untracked/` → still blocks, stderr names the unwritable path.
- Transcript: missing path, empty file, truncated last line, a message whose
  content is a list of blocks, the token in a user message (must NOT allow),
  the token in the last assistant message (allows at count 1), a transcript
  larger than 256 KiB whose last assistant message is within the tail.
- Concurrent Stop and SubagentStop in one session do not share one count.
- A `fail-open-boundaries.yaml` row for the allow-after-N branch:
  `verdict: fail-open`, `caller_controlled: true` (the agent can run the
  permitted `hooks-daemon stop`, then stop freely after three blocks),
  `trace`: the systemMessage text plus the `.daemon-down-stops.log` line.
- Both deployed forwarders (`.claude/hooks/stop`, `subagent-stop`) still
  propagate `forward_stop_event`'s exit code unchanged; the change lives in
  init.sh and its template, so `repair-install` must deploy it
  (`deployed_artefact_drift` will say if the template and deployed copy
  diverge).
- Restart the daemon after the change and confirm a LIVE stop is still
  judged by the daemon's handlers (the bound applies only on the daemon-down
  paths; `forward_stop_event`'s parse of a real `decision: block` is
  untouched).

## Outside this ruling

- DBF-REPORT decisions 1 to 3 (partial defence of the class, the wider
  data-flow rule, the calibrations): owner only.
- Whether `ci_enabled: true` installs should ever get a bounded stop: not
  offered as an option; left unbounded here deliberately.

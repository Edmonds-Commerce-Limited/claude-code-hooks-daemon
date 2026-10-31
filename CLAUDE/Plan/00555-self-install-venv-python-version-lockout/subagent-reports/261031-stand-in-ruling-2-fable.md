# Stand-in ruling 2: Plan 00555 Task 2.8 open findings (S1, S2, S4, S5)

**This is the stand-in's ruling, not the owner's.** The owner did not answer
within the stand-in window, so a `model: fable` sub-agent chose between the
engineering options for the four findings the Task 2.5/2.6 review left open.
It decides nothing else: DBF-REPORT decisions 1 to 3, the client-install
daemon-log question (the I4 owner follow-up) and Plan 00556 remain with the
owner. The owner may overturn any choice below; the implementer should treat
them as provisional until the owner has seen them.

Evidence read: PLAN.md Task 2.6/2.8, INCIDENT.md, the review
(`261031-task-2.5-2.6-review.md` S1/S2/S4/S5), the re-review, the first
stand-in ruling, and `init.sh` by line range: constants 200-229,
`_snapshot_globs` 353-362, `_git_read_only` 524-561, `_safe_session` 636-644,
the stop counter 647-789, the transport's Stop arm 4043-4078, `daemon_reached`
at 3817/4280/4288 and the `connection_lost`/`malformed_response` framing at
3952-3980. Also `secret_file_matching.write_protected_paths_snapshot`
(276-301), `server.start` (1479-1483, the only snapshot write), the
SubagentStop contract (`contracts/claude-code-hooks/SubagentStop.json`:
`agent_id`, `agent_transcript_path`) and the test names in
`tests/integration/test_init_sh_daemon_down_stop_bound.py` and
`test_init_sh_daemon_down_read_only.py`.

## S2 — ruling: option (a), key the SubagentStop count by agent

- The current key is `session_id + event`. Three sub-agents stopping once each
  release the third on its first block, so it never tried recovery; and the
  `[awaiting-human]` check reads the PARENT transcript, so one parent
  declaration lets every sub-agent stop through. Both defeat the bound's
  purpose ("attempt recovery before you stop") for the sub-agent case.
- Liveness is unchanged: each agent still gets exactly N=3. Cost is small:
  one key function and one reset glob. The incident did not involve
  sub-agents, so this is correctness of the Task 2.6 design, not an incident
  fix.

Design: `_stop_counter_path` takes a third component for SubagentStop: the
payload's `agent_id`, cleaned by the same rule as `_safe_session` (ASCII
alnum, `-`, `_`; 100 chars; `unknown` when absent or not a string). When
`agent_id` is absent the key falls back to today's shared one, so the existing
tests stay green. For the declaration check, prefer `agent_transcript_path`
when present and a non-empty string; fall back to `transcript_path`. The
counter path is still under `<daemon root>/untracked`.

Boundary: `_reset_stop_bound` is called with the payload of whatever event the
daemon answered, which may carry no `agent_id`. It must remove every file
matching `.daemon-down-stops.<session>.*` (listdir plus prefix test; no shell
glob), not only the two fixed names, or an agent-keyed count survives a
recovery.

Red tests (write first, in `test_init_sh_daemon_down_stop_bound.py`):

1. Two SubagentStop payloads, same `session_id`, `agent_id` A and B,
   alternating: blocks 1 and 2 for A are blocks, as are 1 and 2 for B; A's
   third allows, B is still blocked until its own third.
2. A SubagentStop with `agent_id` and no prior count is block 1 even when the
   session's shared SubagentStop counter already reads 2 (the keys differ).
3. SubagentStop with no `agent_id` uses the shared key (existing behaviour,
   pinned).
4. A hostile `agent_id` (`../x`, a 300-char string, non-ASCII) cannot escape
   `untracked/`, via the same assertion shape as
   `test_a_hostile_session_id_cannot_escape_the_untracked_dir`.
5. `[awaiting-human]` in the parent transcript with `agent_transcript_path`
   present and NOT declaring: the sub-agent stop is still blocked. The same
   declaration in `agent_transcript_path`: allowed at count 1, no increment.
6. After a parsed daemon response for any event, every
   `.daemon-down-stops.<session>.*` file is gone, agent-keyed ones included.

## S5 — ruling: option (a), count the reached-but-broken classes too

- A daemon that binds, then crashes on every request, is the incident's loop
  in a second shape: identical blocks, no information after the first, no
  exit. The review's I2 already showed how a "reached" classification can make
  the bound unreachable; S5 is the remaining route to that.
- Risk is lower than the connect-failure case, not higher: while the daemon
  is reached-but-broken, PreToolUse denies everything except the exact
  recovery commands, so an allowed stop ends a turn that could do nothing
  else. Keeping it unbounded buys nothing.
- Cost: one condition change at `init.sh:4074` and a `reason_class` per
  error type. Shared counter key, so alternating unreachable/reached blocks
  count as consecutive, as Task 2.6 intends for alternating reasons.

Design: in the Stop/SubagentStop arm of the transport, every class that
produces `decision: block` counts, except `invalid_hook_input` (daemon
healthy; never counts, never allows). `socket_timeout` already allows and
must stay out of the counter. `reason_class` becomes the transport's
`error_type` (`connection_lost`, `connect_backlog_full`, `malformed_response`,
`socket_not_found`, `connection_refused`, ...) so the `.daemon-down-stops.log`
line distinguishes the shapes. The reset rule is unchanged: only a parsed
daemon response resets; a reached-but-broken daemon never resets.

Boundary the implementer must check before writing the test: for a Stop, a
daemon that accepts and then closes CLEANLY returns an empty response, and
`forward_stop_event` already allows an empty response (`init.sh:4464`). That
path is not this ruling's to change; document it in the test module. The
blocked reached-class for Stop is therefore produced by a connection RESET
(accept, then close with `SO_LINGER` zero, or close with unread data) giving
`connection_lost`, and by a listener that never accepts with a full backlog
giving `connect_backlog_full`. If `malformed_response` is unreachable on
Stop (it is raised at 4307-4317 for PreToolUse only), say so in a comment
rather than testing a shape that cannot occur.

Red tests:

1. A fake listener that accepts and resets every connection: Stop blocks
   twice with the "not running" reason text unchanged, allows on the third
   with the systemMessage, and the log line's class is `connection_lost`.
2. Alternating a dead socket (`connection_refused`) and the resetting
   listener counts as three.
3. `invalid_hook_input` still never increments (existing test extended with a
   prior count of 2: the malformed payload must not become the third).
4. `socket_timeout` still allows without touching the counter (existing
   `test_a_reached_but_slow_daemon_keeps_allowing_without_counting` stays).
5. A resetting listener on a PreToolUse is still a deny (no change to the
   PreToolUse arm), pinned so the counting change cannot leak.
6. `fail-open-boundaries.yaml`: the existing allow-after-N row's `trace` is
   extended to name the reached classes, if the inventory scanner reports the
   widened branch.

## S1 — ruling: option (a), with the union not the swap

- The snapshot is written once, at `server.start`. A config edit that breaks
  the restart is exactly the outage this set exists for, and a glob added in
  that edit is unenforced for the whole outage. The first ruling asked for a
  write "at startup and on config reload"; there is no config reload in the
  daemon, so the judge has to detect staleness itself.
- Liveness cost is nil for the incident's recovery path: the lockdown only
  touches `.claude/` (keeping `.claude/hooks-daemon.yaml` and
  `.claude/settings*.json` readable, which is what an agent needs to see the
  edit that broke the restart); the venv, logs and git history stay readable.
- The review's "treat as absent" would DROP the old snapshot's globs. Rule
  instead: when stale, keep enforcing the old snapshot globs AND apply the
  `.claude/` lockdown, so the result is stricter than either state alone.

Design: `_snapshot_globs` (or a sibling) also stats the project's
`.claude/hooks-daemon.yaml` under `project_path` (plus any local override
file the daemon's config loader reads, if one exists; the implementer confirms
the file list from the loader rather than guessing). Stale means any config
mtime is strictly greater than the snapshot's mtime, or any stat fails. Stale
enables the `parts[0] == ".claude"` lockdown branch at `init.sh:484` and the
deny reason says the snapshot is stale and names the newer file. The lockdown
is not applied when the config file does not exist at all (defaults-only
installs have nothing to go stale).

Red tests (in `test_init_sh_daemon_down_read_only.py`):

1. Snapshot older than `.claude/hooks-daemon.yaml`: `cat .claude/anything`
   and Read of it are denied, the reason names staleness;
   `cat .claude/hooks-daemon.yaml` and `.claude/settings.json` stay allowed.
2. Same setup: a glob from the OLD snapshot (`config/credentials.yml`) is
   still denied. This is the union, and it is the test that separates this
   ruling from the review's wording.
3. Snapshot newer than the config: no lockdown; `cat .claude/README.md` (a
   non-protected file) is allowed as today.
4. Equal mtimes: not stale (strictly greater).
5. Config file missing, snapshot present: not stale.
6. The daemon side is unchanged, but pin that a daemon restart rewrites the
   snapshot (mtime advances), since the whole mechanism depends on it.

## S4 — ruling: option (a), drop `git status`

- `git status` refreshes and may rewrite `.git/index`, and runs a repository's
  `core.fsmonitor` program if one is configured. The first ruling's rule was
  explicit: "Nothing in this list may write, exec, or leave the project tree;
  if the implementer finds a permitted shape that can, remove the shape
  rather than patch around it." The alternative, recording an accepted
  residual, is an owner decision, not a stand-in's.
- The incident did not need it. INCIDENT.md names Read, `ls`, `git log` and
  `cat` as the denied diagnostics; `git log`, `ls` and Read of `.git/HEAD`
  cover what `git status` would have told the agent about the tree.
- The mitigations are worse than removal: `--no-optional-locks` stops the
  index write but not fsmonitor, and `-c core.fsmonitor=false` is a `-c`
  the allow-list rightly denies.

Design: remove `status` from `_git_read_only`, delete `_GIT_STATUS_FLAGS` and
`_GIT_STATUS_PREFIXES`, and change the deny-message line at `init.sh:840`
("git log, git status") to name `git log` only. Grep the docs the Task 2.5
work touched (SELF_INSTALL.md, TROUBLESHOOTING, the release note under
`CLAUDE/UPGRADES/UNRELEASED/`) for "git status" and correct them in the same
change.

Red tests: move `git status`, `git status -sb` and
`git status --porcelain=v2 --untracked-files=no` from the allowed table
(`test_init_sh_daemon_down_read_only.py:134-136`) to the denied table; keep
`git status --bogus` denied; assert the deny reason no longer mentions
`git status`; `git log --oneline -n 5` stays allowed.

## Order and scope

Implement S4 first (smallest, pure removal), then S5, S2, S1. All four live in
`_hooks_daemon_recovery_py` and its template, so `repair-install` must deploy
the result and `deployed_artefact_drift` must be clean. Nothing in this
ruling touches the CI-enforced, needs-provision, unconfigured-repo or
version-mismatch branches, the N=3 constant, or the daemon's own handlers.

## Outside this ruling

- DBF-REPORT decisions 1 to 3: owner only.
- Whether a client install may read the daemon logs while the daemon is down
  (the I4 follow-up): owner only.
- Plan 00556: not considered.

# Plan 00487: live-test status, 2026-10-06 (desktop host agent)

This is the result of [OWNER-LIVE-TEST.md](OWNER-LIVE-TEST.md), run on the host in this repository. Times are UTC.

**What was deployed:**

- PR 66 was merged into F44 as `361b1cbb`, from a branch the owner re-created with signed commits.
- At the start, the host's `/var/local/claude-yolo` and `/opt/claude-yolo` files were byte-identical to `origin/F44`: ccy 3.79.1, container 2.42, Claude Code 2.1.291.
- ccy on the host moved to 3.81.0 during the run, from a deploy by another session. A's second relaunch and the malformed-request case ran under 3.81.0.

**How the sessions were run:** each test session ran on ccy's own tmux server (`lt-*` sessions), using the `ec_projects` token and the forwarded agent. A first prompt kept the inner agent from touching anything. Every session except the first refused attempt was started with `ccy --supervise`, because of F1.

## F1: session limits refuse in every daemon-armed project (FAIL, fixed on a branch)

`ccy --max-age 30m` in this repository gets through every prompt, the image rebuild and the Claude Code update. Then it refuses inside the container:

> ✗ CCY: --max-age/--run-for/--until need the hooks-daemon supervisor as the claude wrapper, but the wrapper is: /workspace/.claude/ccy/claude-supervise --arm --

The cause is a mismatch between the two sides:

- The daemon's deployed `ccy.env` arms the supervisor through its shell launcher, `.claude/ccy/claude-supervise --arm --` (`src/claude_code_hooks_daemon/install/ccy_supervisor.py:79`).
- The entrypoint's `ccy_lifecycle_extend_wrapper` accepts only a wrapper naming `claude-supervise.py`.
- The host preflight reads the `.py` file directly, so it passes.

The session limits therefore never work where the daemon armed the supervisor, which is every client. `ccy --supervise` works around it, because it sets a `.py` wrapper on the host.

The fix is on fedora-desktop branch `fix/ccy-lifecycle-daemon-launcher`, commit `3850bc28` (ccy 3.79.2, container 2.43), pushed as a backup. The entrypoint now accepts either form and reads the API major from the `.py` beside the launcher. It was written test-first: 2 new cases failed against the old entrypoint, and `test-ccy-lifecycle.bash` now passes 211 of 211. `qa-all.bash` passes, run with a dummy `ANSIBLE_VAULT_PASSWORD_FILE` for `ansible-syntax`.

There is no PR, merge or deploy. The branch is cut from F44 before 3.80/3.81, so its version numbers need moving above F44's before a merge. That decision is [OWNER-DECISIONS.md](OWNER-DECISIONS.md) D10.

## Results per step

| Step                                                                     | Result  | Evidence                                                                                                                                                                                                                                                                                                              |
| ------------------------------------------------------------------------ | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0. Check out the branch, run the play, `ccy --rebuild`                   | PASS    | Done by the owner (D1/D5). The deployed files matched `origin/F44`.                                                                                                                                                                                                                                                   |
| 0. `qa-all.bash` on the host                                             | PASS    | Exit 0 on the F1 branch. `ccy-relabel-preflight` now passes (D7 fixed on F44).                                                                                                                                                                                                                                        |
| 1. Plain `ccy`: no `--plugin` on the wrapper line                        | PASS    | Session D (no option) and plain launches carried no lifecycle plugin. With `--max-age` the line was `claude-supervise.py --arm --plugin ccy-lifecycle=/opt/claude-yolo/supervisor-plugins/ccy_lifecycle.py --`.                                                                                                       |
| 2. "Session limits" line printed at launch                               | PASS    | `Session limits: restart after 30m`.                                                                                                                                                                                                                                                                                  |
| 2. Status lists `ccy-lifecycle` as `loaded`                              | PASS    | `untracked/supervise/supervisor-status.json`: `ccy-lifecycle 1.0.0 loaded`.                                                                                                                                                                                                                                           |
| 2. Restart-soon notice once, before the restart                          | PASS    | Session A, 11:24:35, typed once.                                                                                                                                                                                                                                                                                      |
| 2. `/exit` at idle, exit status 75                                       | PASS    | 11:29:31: `typed /exit`; 11:29:32: `wrote … restart-request.json; exiting with status 75`.                                                                                                                                                                                                                            |
| 2. Image updated, relaunch with `--resume <same id>`, same token and key | PASS    | The image was updated first. The relaunch used `--resume` with the same session id, the forwarded agent and `ec_projects`, and asked nothing, even with other containers running in the project.                                                                                                                      |
| 2. `restart-request.json` gone after the relaunch                        | PASS    | It was absent after both relaunches.                                                                                                                                                                                                                                                                                  |
| 2. RESTARTED notice, once                                                | PASS    | "this session was restarted and is now on version 2.1.291", once after each relaunch (11:29:51, 12:00:04).                                                                                                                                                                                                            |
| 2. The age clock restarts with the new container                         | PASS    | Session A: clock 11:29:47 → warning 11:54:47 → restart 11:59:48. The second relaunch ran under ccy 3.81.0 and passed too.                                                                                                                                                                                             |
| 2. Unattended relaunch with a key FILE chosen at the menu                | NOT RUN | Needs a GitHub-registered key with no passphrase (owner). The only registered key, `github_ec`, asks for one. ccy rejects an unregistered key.                                                                                                                                                                        |
| 2. Relaunch with the agent passes `--ssh-agent`                          | PASS    | Session A chose the agent; both relaunches forwarded it with no prompt.                                                                                                                                                                                                                                               |
| 2. A key that needs a passphrase stops before the image update           | NOT RUN | Needs a GitHub-registered passphrase key the agent may unlock (owner).                                                                                                                                                                                                                                                |
| 2. Two sessions in one project keep separate ages                        | PASS    | A, B and E ran together, each with its own `lifecycle-<launch id>.json` and its own clock. A worker restart at 11:04 kept both clocks.                                                                                                                                                                                |
| 3. `--until`: deadline notice once, session keeps running                | PASS    | Session B, deadline 11:15:00, notice 11:15:03, once. The session carried on.                                                                                                                                                                                                                                          |
| 3. With `--max-age`: deadline unchanged after a restart, not repeated    | NOT RUN | B's deadline (11:15) came before its age limit (40m). By design (`ccy_lifecycle.py:19-22`) the max-age restart stands down once the deadline is announced, so B correctly never restarted. This step needs the restart BEFORE the deadline.                                                                           |
| 4. The four bad forms fail before any prompt, with the right form        | PASS    | Each exited 1 before any prompt. `3days` and `25:00` show an example. `--run-for … --until` and `--no-supervise` say what is wrong but give no example.                                                                                                                                                               |
| 4. A project whose supervisor predates the API                           | PASS    | A scratch repository with v3.68.0's supervisor: "this project's supervisor predates the plugin API … upgrade the hooks daemon", before any prompt.                                                                                                                                                                    |
| 4. Restart budget                                                        | PASS    | Session E with `CCY_RESTART_MAX=1`: "restart budget spent: 1 restart(s) in the last 3600s, the limit is 1", then `ccy --resume <id>`, exit 1.                                                                                                                                                                         |
| 4. Exit 75 with no request file                                          | PASS    | "exited with status 75 but left no restart request …, so this is not a restart". The launcher exited 75.                                                                                                                                                                                                              |
| 4. Exit 75 with a malformed request file                                 | PASS    | "is not valid JSON … unusable restart request (discarded), so this is not a restart". The file was removed (ccy 3.81.0).                                                                                                                                                                                              |
| 5. Raising, hanging and printing plugins                                 | PASS    | Session D: `lt-raise` was disabled (`exception in on_idle`) and `lt-hang` was disabled (`overrun in on_idle`, worker restarted without it), each with exactly one notice. `lt-print` stayed `loaded`: its output went only to the worker error log, and no bad reply was logged. The session kept working throughout. |

## Corrections to OWNER-LIVE-TEST.md

- **Status file:** it is at `untracked/supervise/supervisor-status.json`, not `.claude/ccy/supervisor-status.json`. All sessions in a project share it, so the last writer wins and it shows only one session's plugins.
- **Section 0 versions:** they are stale; the host now runs ccy 3.81.0 / container 2.42.
- **`ccy --supervise`:** until F1 is deployed, sections 2 and 3 need it.
- **Key menu:** it defaults to the push-capable key FILE, not the agent.
- **Step 3.2:** it needs `--until` set after the max-age restart, for example `--max-age 30m --until <now+40m>`.
- **Section 5:** a plugin that prints to stdout is not a failure. It stays `loaded` with no notice; that is the API's documented reply-channel isolation.
- **Budget step:** it is only reachable inside the 30-minute minimum age with `CCY_RESTART_MAX` lowered.
- **Leftover marker:** a refused relaunch (budget) leaves `restarted.json` behind. The supervisor clears it after a day; it does no harm.

## Commits and branches pushed today by this agent

- hooks-daemon `main`: `609ae6880` and `f4a802e8e`, niggle N364 in Plan 00474's ledger. These came before the coordinator ruled out ledger entries.
- hooks-daemon `main`: this file, the D10 entry and the plan, journal and PR-comment records (the commit that adds this file).
- fedora-desktop branch `fix/ccy-lifecycle-daemon-launcher`: `3850bc28` (F1 fix, signed). No PR.

## Other actions taken today

- #71 was re-assigned from `lts-bob` to `edmondscommerce`, on the owner's instruction. gh's active account is switched to `edmondscommerce` only while this plan's records are written, then back to `LTSCommerce`. The issue-assignment guard judges by the active account, and the daemon caches it until a restart, so the `gh-ec` alias alone does not satisfy it.
- Both declared crons were paused for this session with `cron-pause`, on the owner's instruction that desktop sessions run none.
- `.claude/ccy/.gitignore` was modified by the ccy 3.81.0 launcher (the `ccy.env.local.dist` exception). It is left uncommitted for the owner.

## Handler false positives met (one line each)

- `project_containment` resolved `../x` against the repository root, ignoring a same-command `cd` (known: N28/N338).
- `sensitive_content` scanned the whole command line, including a `cd` path, once a git metadata command was present: `git config --get-regexp` and `git switch -c` (N364).
- The "WRONG CLAUDE/ DIRECTORY" advisory fired on every read of this repository's own `CLAUDE/` (known: N340).
- `github_issue_assignment_guard` keys on gh's globally active account, cached until a daemon restart, so the per-command `gh-ec` alias cannot satisfy it.

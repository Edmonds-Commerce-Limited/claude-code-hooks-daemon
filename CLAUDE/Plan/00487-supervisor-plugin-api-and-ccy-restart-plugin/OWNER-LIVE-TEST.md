# Plan 00487: owner live test (Task 3.1)

Nothing in this checklist can run inside a ccy container: it needs the host, an image rebuild and real container exits. Both halves are written and unit-tested:

- **hooks-daemon:** the supervisor plugin API is merged to main (`14f2f11f8`, plus the test fix `4bb315985`). The live worker reload was verified on this session.
- **fedora-desktop:** branch `feature/ccy-hooks-daemon-plugin` (head `d9488a15`). It is pushed, and fedora-desktop PR 66 exists for it (owner decisions D1 and D6).

**First run: 2026-10-06.** Results are in [LIVE-TEST-STATUS-261006.md](LIVE-TEST-STATUS-261006.md); the corrections it found are folded in below. Three steps are still to run: the key-file relaunch, the passphrase key, and the deadline after a restart.

**Until F1 is deployed, start every session in sections 2 and 3 with `ccy --supervise`.** The daemon's `ccy.env` arms the supervisor through the `claude-supervise` launcher, and the deployed entrypoint accepts only a wrapper naming `claude-supervise.py`, so `--max-age`, `--run-for` and `--until` refuse without it. The fix is fedora-desktop branch `fix/ccy-lifecycle-daemon-launcher` ([OWNER-DECISIONS.md](OWNER-DECISIONS.md) D10).

**Which project to test in.** A project receives the supervisor (`.claude/ccy/claude-supervise.py`) from its hooks-daemon install, and no release carries the plugin API yet. Until one does, test in this repository, which runs the supervisor from main. Any other project needs a hooks-daemon release first.

## 0. Prepare (host)

- [ ] Check out `feature/ccy-hooks-daemon-plugin` in your fedora-desktop checkout and run the claude-yolo play. It copies `supervisor-plugins/` into the build context.
- [ ] `ccy --rebuild`. The image should report container version 2.42, and the launcher should report ccy 3.77.1 (fedora-desktop PR 66, merged by the owner). The branch is folded into that one release on top of F44's own 3.76.0 / 2.41; the branch head is in this plan's JOURNAL. If F44 has moved again by the time you deploy, merge it first, and move these two numbers above F44's. These numbers are now stale: at the first run the host moved to ccy 3.81.0 (container 2.42) mid-test, from another session's deploy.
- [ ] Run fedora-desktop's `./scripts/qa-all.bash` on the host. It cannot run in a container here, because ruff and semgrep are absent and shellcheck is not the pinned 0.11.0.

## 1. No options means no change

- [ ] Run plain `ccy`. `ps` inside the container shows the supervisor wrapper line with no `--plugin`, and the session behaves as before.

## 2. Maximum age

- [ ] Run `ccy --max-age <the smallest allowed value>`. For a faster test, lower `CCY_RESTART_WARN_MINUTES` first. Check that:
  - a "Session limits" line is printed at launch;
  - `untracked/supervise/supervisor-status.json` lists `ccy-lifecycle` as `loaded` (every session in the project writes this one file, so it shows the last writer's plugins);
  - the restart-soon notice arrives once, before the restart;
  - at the next idle point the supervisor types `/exit` and the container exits with status 75;
  - the launcher updates the image, then relaunches with `--resume <same session id>`, keeping the same token, keys and network;
  - `.claude/ccy/state/restart-request.json` is gone after the relaunch;
  - the resumed session gets the "restarted, now on Claude Code X" notice, once.
- [ ] The max-age clock restarts with the new container: the next restart waits for the full configured age again.
- [ ] Unattended relaunch: run `ccy --max-age 30m` with NO other flag, answering every prompt (token, key, network). At the key prompt pick a GitHub-registered key FILE with no passphrase, not the agent (the agent would skip the SELinux key-staging path). The menu defaults to the push-capable key file, and ccy rejects an unregistered key. At the restart the relaunch asks nothing, carries the choices made at the prompts, and stages the key again.
- [ ] Repeat once choosing the agent at the key prompt: the relaunch passes `--ssh-agent`.
- [ ] Repeat with an SSH key that needs a passphrase. The restart stops before any image update, with the reason and `ccy --resume <id>`, instead of waiting at a prompt.
- [ ] Two sessions in one project, both with `--max-age`: restarting or reloading one does not reset the other's age.

## 3. Deadlines

- [ ] `ccy --until <a clock time shortly ahead>`: the deadline notice arrives once, and the session keeps running.
- [ ] Combine with `--max-age`, with the deadline set AFTER the first restart, for example `--max-age 30m --until <now + 40m>`. The max-age restart stands down once the deadline has been announced, so a deadline before the restart never exercises this. After the restart the deadline is still the same absolute time, and it is not announced a second time.

## 4. Refusals and limits

- [ ] Each of these fails before any prompt, with an example of the right form: `--max-age 3days`, `--until 25:00`, `--run-for 2h --until 17:30` and `--max-age 3d --no-supervise`.
- [ ] `ccy --max-age 3d` in a project whose hooks daemon predates the plugin API (any project other than this one, until a release carries it) fails before any prompt and says to upgrade the hooks daemon. It must not reach the container's argparse error.
- [ ] Restart budget: force more restart requests than `CCY_RESTART_MAX` allows inside `CCY_RESTART_WINDOW_SECONDS`, for example with a short `--max-age`. It is only reachable inside the 30-minute minimum age with `CCY_RESTART_MAX` lowered (for example to 1). The request over the budget stops with the budget message and the manual `ccy --resume <id>` command. The refused relaunch leaves `restarted.json` behind; the supervisor clears it after a day, and it does no harm.
- [ ] Hand-written requests: an exit 75 with no request file, or with a malformed one, behaves as before and says so on stderr. A malformed file is discarded.

## 5. A plugin cannot take the session down (supervisor side)

- [ ] Point `--plugin` at a deliberately broken worker file: one that raises, one that hangs and one that prints to stdout. Each time the session starts and keeps working. The raising and hanging plugins each give the agent exactly one plugin notice naming the plugin, and `supervisor-status.json` shows them `disabled`. The printing plugin is not a failure: its output goes only to the worker error log, it stays `loaded`, and no notice is given (the API's reply-channel isolation).

When all of this passes, Task 3.1 is done. Open the fedora-desktop PR (your call), and Task 3.2 comments the outcome on #71 and fedora-desktop#61.

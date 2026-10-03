# Plan 00487: hand-over to a desktop (host) agent

Read this first, then [PLAN.md](PLAN.md), [DECISIONS.md](DECISIONS.md) and [OWNER-LIVE-TEST.md](OWNER-LIVE-TEST.md). Everything in this plan was built inside a ccy container, where the restart path cannot be exercised. A real restart needs a container exit, an image update and a relaunch on the host. A host-side agent therefore finishes the plan. It works on both repositories, and it tracks everything in THIS plan, including the fedora-desktop work (owner ruling).

## Where things stand

| Side                                                  | State                                                                                                                                                                    |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| hooks-daemon (this repo), the supervisor plugin API   | Merged to `main`: `14f2f11f8` (Phase 1) and `4bb315985` (skew-test baseline pinned to `v3.68.0`). Not in any release yet. Review round 3 approved.                       |
| fedora-desktop, the ccy plugin and launcher           | Branch `feature/ccy-hooks-daemon-plugin`, head `3a1aa635` (ccy 3.76.0, container 2.42, after the host review fixes), pushed. No PR, nothing merged. Based on `3597b29e`. |
| Live test                                             | Not run. This is the remaining critical-path work (Task 3.1).                                                                                                            |
| Tasks 1.4 and 1.5 (in-container `Restart`, host half) | Open. They serve the credential-switch case, not this plan's goals. They may be split out to fedora-desktop Plan 00146 or a new plan; the owner decides.                 |
| Task 3.2 (comments on #71 and fedora-desktop#61)      | After the live test.                                                                                                                                                     |

## The contract between the two sides

- **Wrapper line.** The ccy launcher adds `--plugin ccy-lifecycle=<path to ccy_lifecycle.py>` to the supervisor's wrapper line only when `--max-age`, `--run-for` or `--until` (or `CCY_MAX_AGE`) is given. Plain `ccy` passes no plugin flag.
- **Worker hook.** `ccy_lifecycle.py` implements `on_start` and `on_idle(tick)`. It returns `Notify("restart-soon", minutes)`, `Notify("deadline-reached")`, `ExitForRestart(reason)` or `None`. Plugins supply no text: the supervisor renders every chat line from its own fixed templates.
- **Exit for restart.** At an idle point the supervisor types `/exit`, waits up to 30 s for the child, then writes `.claude/ccy/state/restart-request.json` (mode 0600; `session_id`, `reason`, `plugin`, `requested_at`) and exits with status **75**. It also writes `.claude/ccy/state/restarted.json` (`session_id`, `requested_at`).
- **Launcher.** On status 75 with a fresh, valid request file, the launcher consumes (deletes) the request file, forces the image update (`update_claude_inplace`) and relaunches with `--resume <session_id>`. The budget is 3 relaunches per hour per project (`CCY_RESTART_MAX`, `CCY_RESTART_WINDOW_SECONDS`). Status 75 with no file, or with a malformed one, behaves as an ordinary exit, says so on stderr, and discards a malformed file. The launcher must leave `restarted.json` alone.
- **RESTARTED notice.** The resumed supervisor consumes `restarted.json` once and types "restarted, now on Claude Code X.Y.Z". The version comes from a bounded `claude --version`, else "the installed version".

## File map

**hooks-daemon:**

- `.claude/ccy/claude-supervise.py`: the plugin loader, worker hooks, notices and exit-for-restart (search for "Plan 00487").
- `CLAUDE/development/CcySupervisor.md`: the API documentation and the hot-reload verification procedure.
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/001-ccy-supervisor-plugin-api.md`: the release callout.
- Tests: `tests/unit/supervise/test_plugin_*.py`, `test_session_notices.py` and `_plugin_helpers.py`. Run them with `pytest tests/unit/supervise`.

**fedora-desktop** (`git diff --stat 3597b29e..d9488a15`):

- `files/var/local/claude-yolo/supervisor-plugins/ccy_lifecycle.py`: the worker plugin.
- `files/var/local/claude-yolo/lib/restart-request.bash`: exit-75 handling and the relaunch budget.
- `files/var/local/claude-yolo/lib/session-lifecycle.bash`: option parsing for `--max-age`, `--run-for` and `--until`.
- `files/var/local/claude-yolo/claude-yolo`, `entrypoint.sh` and `Dockerfile`: the launcher wiring, which copies `supervisor-plugins/` into the image.
- `playbooks/imports/play-claude-yolo.yml`: deploys the plugin directory.
- Tests: `scripts/test-ccy-lifecycle.bash`, `scripts/test-ccy-restart-request.bash` and `tests/helpers/ccy_lifecycle/test_plugin.py`, wired into `scripts/qa-all.bash`.
- Versions: ccy 3.75.0, container 2.41 (`docs/ccy-changelog.md`).

Reports for each step are in [subagent-reports/](subagent-reports/). The round-3 approval is recorded in the merge commit message only; no round-3 report file exists.

## Steps for the desktop agent

1. **Sync both repositories.** Pull hooks-daemon `main`. Check out `feature/ccy-hooks-daemon-plugin` in fedora-desktop.
2. **Run fedora-desktop QA on the host.** Run `./scripts/qa-all.bash` and that repository's `qa-reviewer`. They never ran in the container: ruff and semgrep were absent, and shellcheck was 0.9.0 instead of the pinned 0.11.0. Fix any findings on the branch. Known leftovers: pyright `Optional` notes in `tests/helpers/ccy_lifecycle/test_plugin.py`.
3. **Deploy and run the live test.** Run the claude-yolo play, then `ccy --rebuild`, then work through [OWNER-LIVE-TEST.md](OWNER-LIVE-TEST.md) sections 1 to 5, in a ccy session on THIS repository. No release carries the API yet, so other projects do not have it. Tick each box in that file as it passes.
4. **Fix what fails, on the side where the fault is.** A supervisor fault is fixed in a hooks-daemon worktree, TDD, under this repo's merge discipline (below). A launcher or plugin fault is fixed on the fedora-desktop branch, under that repository's rules (below). Re-run the failed section afterwards.
5. **Record everything here.** Write journal entries with `CLAUDE/Plan/mkplan.bash --journal 00487 <category> <body-file>`, tick Task 3.1 in PLAN.md, and commit and push after each unit.
6. **Task 3.2.** Comment the outcome on hooks-daemon #71 and fedora-desktop#61. Write "Addresses #N" and never a closing keyword.
7. **Owner decisions live in [OWNER-DECISIONS.md](OWNER-DECISIONS.md).** That file lists each decision that is the owner's, not an agent's, with its options, a recommendation and the evidence. When the live test produces something new, add it there, then commit and push. Every session (this one and the container one) works from that file after a `git pull`, so no decision is passed by chat. Record the owner's answer in the same file, against its item. Nothing listed there is acted on until it has an answer.
8. **Close the plan** (once the owner settles item 7) per the Plan Completion Checklist in `CLAUDE/PlanWorkflow.md`: Status Complete, `git mv` into `Completed/`, and the README row and statistics, all in one commit.

## Rules that bind the desktop agent

**Both repositories:**

- Never release, tag or publish. A hooks-daemon release starts only when the owner types `/release`.
- Never attribute an agent ruling to the owner.

**fedora-desktop:**

- It is a PUBLIC repository. Nothing install-specific goes into it or its issues: no hostnames, home paths, session ids or client names.
- Changes are IaC only, so tools are installed through the playbooks, never by hand.
- Any change to ccy files bumps the ccy version and its changelog.
- Fail fast.

**hooks-daemon:**

- Work happens in worktrees made with `./scripts/setup_worktree.sh worktree-<name>`.
- A branch merges only when `./scripts/qa/llm_qa.py changed` is green at its head.
- When `changed` reports too-broad files, run `tests/integration`, `tests/acceptance` and `llm_qa.py semgrep` on main after the merge. Restart the daemon before acceptance, and never during a running test.
- The live supervisor's worker hot-reloads, so verify the reload as `CcySupervisor.md` describes instead of restarting a session to pick up a supervisor change.

**Harness:** under the Claude Code Bash tool a top-level `set -e` does not stop on a failing step (ledger 00474 N328). Gate dependent steps with `&&`.

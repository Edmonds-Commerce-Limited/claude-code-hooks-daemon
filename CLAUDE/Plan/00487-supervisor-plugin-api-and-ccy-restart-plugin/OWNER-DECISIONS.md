# Plan 00487: decisions for the owner

Each item here is the owner's call. An agent adds the item, with its options, a recommendation and the evidence, then commits and pushes. The owner answers in the **Answer** line, or tells any session the answer, and that session records it. No agent acts on an item until it has an answer.

## D1. The fedora-desktop PR

`feature/ccy-hooks-daemon-plugin` holds the ccy plugin and the launcher changes. Should a PR be opened, and should it be merged?

- **Recommendation:** open the PR once `qa-all.bash` and the live test pass on the host. Merging is a separate step.
- **Evidence:** the OWNER-LIVE-TEST.md results and the qa-all output, recorded in this plan's JOURNAL.
- **Answer (owner, 2026-10-03, by voice in the host session):** open the PR now, before the live test. The owner merges it and runs the rebuild; the agent does not touch the owner's fedora-desktop checkout, which is in active development.

## D2. Tasks 1.4 and 1.5 (in-container `Restart` and the host half)

These serve the credential switch (fedora-desktop Plan 00146), not this plan's goals. Should they stay here, move to fedora-desktop Plan 00146, or move to a new hooks-daemon plan?

- **Recommendation:** move them to a new hooks-daemon plan, so that 00487 can close when the live test passes. The API code lives in this repository.
- **Answer (owner, 2026-10-03):** "whatever you think makes sense; no strong opinion." The agent therefore follows its recommendation: Tasks 1.4 and 1.5 move to a new hooks-daemon plan.

## D3. The agent rulings in [DECISIONS.md](DECISIONS.md)

The rulings in DECISIONS.md were made by an agent while the owner was away. Should each one be confirmed or reversed?

1. Release first. This is done, so nothing is left to decide.
2. Push the fedora-desktop branch, but open no PR. D1 supersedes this.
3. ccy keeps its plugin in its own repository and names it with `--plugin`.
4. Restart policy:
   - maximum age is off unless set;
   - a warning goes out 10 minutes before the restart;
   - there is no forced restart of a busy session;
   - at most 3 restarts per hour.
5. An update restarts through a host relaunch on exit 75.

- **Answer (owner, 2026-10-03):** confirmed. The ccy plugin belongs in the fedora-desktop repository: plugins exist so that third-party systems can bring their own and plug them into the hooks daemon. Maximum age off by default and at most 3 restarts an hour are both fine. Rulings 1, 2 and 5 drew no objection; 2 is superseded by D1.

## D4. A hooks-daemon release carrying the API

Other projects get the plugin API only from a release. A release starts only when the owner types `/release`.

- **Recommendation:** release after the live test passes, so that the release carries a tested API.
- **Answer (owner, 2026-10-03):** a hooks-daemon release is needed, and the owner makes it. The agent's part is only to get the functionality merged, which it is (on `main` since `14f2f11f8`). `--max-age` and the other options working only where the hooks daemon provides the plugin API is the intended behaviour.

## D6. Round-3 review items F and G: before or after the merge? (raised by the host agent)

The third fedora-desktop review ([report](subagent-reports/261003-task-3.1-fedora-desktop-qa-reviewer-round-3-opus.md)) fixed everything from round 2 and left two "should fix" items.

- **F:** the docs and the refusal message do not say that a key unlocked through F44 3.76.0's askpass route cannot restart unattended, and they still recommend `--ssh-agent`, which 3.76.0 labels as exposing every key. This is a docs fix.
- **G:** the forwarded-agent GitHub probe (`ssh-handling.bash:729-739`) has no timeout. If an agent asks before it signs (a key added with `ssh-add -c`, or gpg-agent once its cache expires), the relaunch waits. This is not new on the branch, but the unattended relaunch makes it matter. The fix is a `timeout` on that probe when relaunching.
- **Recommendation:** fix both on the branch before merging. They are small, and G is the last known way a restart can wait.
- **Answer (owner, 2026-10-03):** fix them before the merge. Done in fedora-desktop `dc12846e` (ccy 3.77.1), with a comment on PR 66.

## D7. `util-linux-script` on the host (raised by the host agent)

`ccy-relabel-preflight` fails 36 cases on this host because the `script` command (package `util-linux-script`) is not installed, and no playbook installs it. This is on F44, not on the branch.

- **Recommendation:** add `util-linux-script` to the QA toolchain in `play-python.yml` on F44.
- **Answer (owner, 2026-10-03):** already handed to a fedora-desktop session, which is adding it. Nothing for this plan to do.

## D5. How the branch gets deployed for the live test (raised by the host agent)

The claude-yolo play can only run from the owner's own fedora-desktop checkout. The inventory `host_vars` and the vault password file are gitignored and exist only there, so a clone or worktree of the branch cannot run it. That checkout is on `F44`, and another session was committing in it while the host agent worked, so the agent will not switch its branch on its own.

- **Option A (recommended):** the owner runs the play from a checkout of `feature/ccy-hooks-daemon-plugin`, for example `git switch feature/ccy-hooks-daemon-plugin && ./playbooks/imports/play-claude-yolo.yml && git switch F44` once no other session is using that checkout, then `ccy --rebuild`. The agent then drives the live test.
- **Option B:** the agent switches the owner's checkout to the branch, runs the play, and switches back to `F44`, at a time the owner names when no other session is using it.
- **Option C:** merge `origin/F44` into the branch first, so that a deploy carries the 15 newer F44 commits too. None of them touch ccy files, so this is optional for the test.
- **Evidence:** the 15 commits on `origin/F44` that the branch lacks change no file under `files/var/local/claude-yolo`, `playbooks/imports/play-claude-yolo.yml` or `docs/ccy-changelog.md`, so deploying the claude-yolo play from the branch rolls back no ccy change. The JOURNAL entry "fedora-desktop qa-all on the host" has the details.
- **Answer (owner, 2026-10-03):** neither A nor B. The branch goes in as a PR (see D1). The owner merges it into F44 and then deploys and rebuilds from their own checkout. The branch has since merged F44, which settles option C.

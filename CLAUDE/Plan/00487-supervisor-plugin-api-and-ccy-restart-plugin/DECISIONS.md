# Plan 00487 decisions

These are agent rulings, made while the owner was away. Each is open to reversal and is marked as an agent ruling, not an owner ruling. The owner asked for questions before leaving, and these are the defaults that apply until the owner answers.

1. **Ordering.** The release comes first: nothing from this plan merges to main until v3.68.0 is tagged and published. All work happens on worktree branches.

2. **fedora-desktop.** The feature branch is pushed as a backup (the repository's own "always push" rule). No PR is opened and nothing is merged there.

3. **Plugin location.** ccy keeps its plugin in its own repository and names it on the wrapper line through `--plugin` flags, as the draft specifies. Projects never carry a copy.

4. **Restart policy.** These are configuration defaults, not schedule estimates:

   - The maximum session age is 3 days, set per session.
   - The restart warning goes out 10 minutes before the restart.
   - The restart happens at the first idle point after the warning, never in the middle of a turn.
   - If the session is still busy 30 minutes after the warning, the restart is forced.
   - After the restart, the session gets a "restarted, now on Claude Code X.Y.Z, carry on" message.

5. **What gets restarted: the container, through ccy on the host.** Task 2.1 found ([report](subagent-reports/261003-task-2.1-ccy-update-path-explore-sonnet.md)) that Claude Code is baked into the ccy image (`npm install -g` in the Dockerfile). The host updates the image (`update_claude_inplace`, at most daily per image), and containers run with `--rm`, so the install is image-only. Respawning `claude` inside a running container re-runs the same binary. An update restart therefore works like this:

   1. The worker plugin warns the session.
   2. At an idle point, the supervisor sends `/exit` and exits with a dedicated "restart requested" exit status. It records the session id in a state file on the persistent mount.
   3. The ccy launcher on the host sees that status, updates the image, and relaunches with `--resume <id>`.
   4. The new supervisor's first idle point sends the "restarted, now on Claude Code X.Y.Z" notice.

   This is the draft's "outer wrapper loop plus a built-in exit at idle" alternative, which it accepted as a fallback. It sits alongside the plugin API rather than replacing it. The draft's in-container `Restart` primitive stays in scope for the credential-switch case, which needs no new binary. It is not on the critical path for this plan, and can be deferred to Plan 00146 if it grows.

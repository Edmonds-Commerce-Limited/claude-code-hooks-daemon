# Plan 00487 decisions

These are agent rulings, made while the owner was away. Each is open to reversal and is marked as an agent ruling, not an owner ruling. The owner asked for questions before leaving, and these are the defaults that apply until the owner answers.

1. **Ordering.** The release comes first: nothing from this plan merges to main until v3.68.0 is tagged and published. All work happens on worktree branches. Held: v3.68.0 was published before the Phase 1 merge (`14f2f11f8`).

2. **fedora-desktop.** The feature branch is pushed as a backup (the repository's own "always push" rule). No PR is opened and nothing is merged there.

3. **Plugin location.** ccy keeps its plugin in its own repository and names it on the wrapper line through `--plugin` flags, as the draft specifies. Projects never carry a copy.

4. **Restart policy.** These are configuration defaults, not schedule estimates:

   - The maximum session age is OFF unless `--max-age` (or the host's `CCY_MAX_AGE`) sets it. 3 days is the documented example, not a default. This is more conservative than the first draft of this ruling, because a restart the operator did not ask for is the riskier mistake.
   - The restart warning goes out 10 minutes before the restart (`CCY_RESTART_WARN_MINUTES`).
   - The restart happens at the first idle point after the maximum age, never in the middle of a turn.
   - **Revised:** there is no forced restart for a busy session. The first draft promised one 30 minutes after the warning. The supervisor only calls plugins at an idle point, and forcing `/exit` into a busy turn is the mid-turn interruption this policy forbids. A session that never goes idle therefore restarts at its first idle point after its maximum age.
   - After the restart, the session gets a "restarted, now on Claude Code X.Y.Z, carry on" message. The supervisor's wording is neutral about why the restart happened.
   - At most 3 restarts per hour per project (`CCY_RESTART_MAX`, `CCY_RESTART_WINDOW_SECONDS`), so a crash loop cannot relaunch forever.

5. **What gets restarted: the container, through ccy on the host.** Task 2.1 found ([report](subagent-reports/261003-task-2.1-ccy-update-path-explore-sonnet.md)) that Claude Code is baked into the ccy image (`npm install -g` in the Dockerfile). The host updates the image (`update_claude_inplace`, at most daily per image), and containers run with `--rm`, so the install is image-only. Respawning `claude` inside a running container re-runs the same binary. An update restart therefore works like this:

   1. The worker plugin warns the session.
   2. At an idle point, the supervisor sends `/exit` and exits with a dedicated "restart requested" exit status. It records the session id in a state file on the persistent mount.
   3. The ccy launcher on the host sees that status, updates the image, and relaunches with `--resume <id>`.
   4. The new supervisor's first idle point sends the "restarted, now on Claude Code X.Y.Z" notice.

   A relaunch inherits the first launch's record of compose services it started (`CCY_COMPOSE_WAS_STARTED`, `CCY_COMPOSE_CMD`), so the resumed session is the one that offers to stop them when it ends. That is the single-session behaviour. It does not inherit the key staging directory or the token values (host agent, Task 3.1, review round 2 finding A).

   This is the draft's "outer wrapper loop plus a built-in exit at idle" alternative, which it accepted as a fallback. It sits alongside the plugin API rather than replacing it. The draft's in-container `Restart` primitive stays in scope for the credential-switch case, which needs no new binary. It is not on the critical path for this plan, and can be deferred to Plan 00146 if it grows.

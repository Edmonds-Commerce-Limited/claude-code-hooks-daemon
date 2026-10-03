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
5. **What gets restarted.** Whichever restart actually picks up a new Claude Code version: `claude` inside the container, or the container itself. This is established from the fedora-desktop source in Task 2.1 and recorded here.

## 13:25 · finding · —

Phases 1 to 7 built on the branch, in this worktree, by four sub-agents. One lock agent ran out of context twice, and the work was continued from its handoffs.

Findings while studying the existing flow:

- Layer 2 deliberately keeps the new code when the daemon does not start (Step 15) or validation fails (Step 16). Unattended runs now roll back there instead. Attended behaviour is unchanged.
- `provision.sh --background` judged its lock holder with `kill -0`, so a holder in another container's PID namespace read as dead and could be taken over mid-sync. Its lock also lived inside the clone the switch moves. Both are replaced by the shared lock.
- Release tags are SSH-signed, but nothing verifies a signature. This is recorded as an owner decision, not built.

Coordinator review of the lock found a takeover race: when the re-judge under the takeover file saw the lock vanish, it still removed the lock path and could delete a fresh lock. It now creates without removing, and removes a stale lock only if its token is unchanged. A residual window remains when two takers both see a takeover file older than 60 s, which needs a crash inside the takeover.

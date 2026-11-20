# Callout: worktree creation no longer loses its creator record to a held git config lock, and its branch checks follow host load

**Plan**: 00474
**Audience**: client projects

When a session creates a worktree, the daemon checks the branch cap and then records which session created the branch in the repository's git config. Both steps used a fixed 5 second budget, so on a heavily loaded host a timed-out check was read as a failed judgement, and a creator record written while another git process held `.git/config.lock` was silently lost. The branch checks now scale their budget with host load (up to 10 seconds each), and each creator-record write waits for the lock for up to 10 seconds, then logs and carries on without blocking the worktree. The WorktreeCreate event budget grows from 440 to 500 seconds to cover this, and the shell client's default wait for that event grows from 450 to 510 seconds. A client project that overrides the wait in its own `init.sh` copy should refresh it by upgrading the daemon.

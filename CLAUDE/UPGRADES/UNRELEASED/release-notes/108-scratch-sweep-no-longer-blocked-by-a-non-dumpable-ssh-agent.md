### Scratch sweep and worktree evacuation are no longer blocked by a running ssh-agent

In a container without `CAP_SYS_PTRACE`, a running `ssh-agent` or `gpg-agent`
marks itself non-dumpable, so the kernel refuses even root its
`/proc/<pid>/cwd`. The scratch sweep counted that as a process whose working
directory could not be read, reported the classification as incomplete, and
refused every evacuation and sweep for as long as the agent ran
(`classification incomplete: 1 process(es) whose working directory could not be read`). A merged branch whose agent worktree held scratch could then never be
reaped.

`read_process_cwds` now skips a process whose cwd is unreadable only when its
world-readable `comm` names `ssh-agent` or `gpg-agent`. Any other unreadable
process still makes the classification incomplete, so the fail-closed rule is
unchanged for everything else.

No action is needed on upgrade.

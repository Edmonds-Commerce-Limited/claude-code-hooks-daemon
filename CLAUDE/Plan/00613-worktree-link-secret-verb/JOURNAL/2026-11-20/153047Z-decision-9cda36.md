## 15:30 · decision · —

Owner decision on Q0 to Q3 (supersedes the delegated ruling of 2026-11-19 for Q0 to Q2).

The owner typed, in the coordinating session, relayed verbatim in the coordinator's brief to this sub-agent: "A linking vault files is essential if worktrees are to be able to work. there's no security issue here - the file already exists on the file system we're just making worktrees actually work". The sub-agent did not see the human line itself; the citation is that session's line, through the brief.

- Q0: yes, the owner typed it.
- Q1: yes. Linking a protected file into an agent's own worktree is allowed and needed. Decided with it: LINK mode only; COPY mode for a protected file stays forbidden (a copy makes a second file, a link does not).
- Q2: B + D as recommended. The route is owned by the project config or a human, never invocable by an agent to link an arbitrary protected path.
- Q3: forbid (unchanged).
- Constraint from the brief: the secret guard's read protections stay intact; a linked path is still refused for Read/Bash content access. Only the worktree creation/link route changes.

Small points settled on best practice by the building sub-agent:

1. The human-run step for a hand-made worktree is a command, `hooks-daemon seed-worktree <worktree>`, not a documented hand-typed `ln -s`. Reason: a hand `ln -s` naming the protected path is denied to an agent by R-SECRET-BASH-MENTION (pinned, Task 2.3), and a human typing it bypasses the audit log and the copy refusal. The command re-applies the CONFIGURED list only and takes no path, so an agent running it can link nothing the config does not already grant at creation. It is agent-runnable; that is deliberate, because the authority is the config, not the invoker.
2. Its argument surface is one positional and no options, pinned by a parser test.
3. The worktree must be a non-main, non-prunable worktree in git's own list, matched by realpath; a subdirectory, the main checkout, an unlisted directory and a path with a control character refuse. The main checkout (and so the config) is found from the worktree's own git listing, so a worktree of another repository is judged by that repository's config.
4. The config is read strictly (missing, malformed or schema-invalid refuses), as at creation's copy check.
5. The audit line gains the route: LinkAudit.verb, `worktree-seed` for the hook, `seed-worktree` for the command. Keys unchanged.
6. The copy refusal now says to seed the file with mode: symlink; callout 009 and pre-upgrade task 01 say move to symlink mode (or remove).
7. The config-edit route: an agent can Edit the seed list, as it can any config. A PreToolUse deny on config writes is circular (guard_config_drift docstring), so the answer is visibility: an added seed entry is counted by the session-start drift report. Pinned; left as a residual risk for the security review.

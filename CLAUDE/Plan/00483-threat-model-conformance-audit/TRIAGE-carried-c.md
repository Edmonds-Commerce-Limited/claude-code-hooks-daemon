# Plan 00483 Task 2.1: triage of carried entries, branch `worktree-p422-close`

Scope: `CLAUDE/Plan/00474-niggles-ledger-seventeen/CARRIED-REFIX-BRANCHES.md`, lines 1130-1527
(15 entries). Each was reproduced on current main with `bin/hooks-daemon probe PreToolUse`.
Payloads and outputs are in `untracked/scratch/p483-c/`. The test applied is the two-part test in
`CLAUDE/ARCHITECTURE.md`, "Threat model: the agent is careless, not hostile".

Probe note: `$m` and `$N` in a payload are literal text to the daemon, as they are in a real call.

| Entry | Verdict                           | Shape / limb or repro                                                                                                                                                                                                                   | Evidence                                                                                                                                                                                                                                                                                                                                                                        |
| ----- | --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| N134  | FIXED-ON-MAIN                     | Read-only `ls` with several unanchored globs no longer crashes the secret guard                                                                                                                                                         | `ls /workspace/CLAUDE/*/release-notes* /workspace/release-notes* /workspace/CHANGELOG*` and a `/workspace/CLAUDE/*/*/release-notes*` variant: allow, no `TooManyToEnumerateError`. A `python3 - <<'EOF'` heredoc with no protected path: allow. The entry's exact `ls CLAUDE/Plan/*/release-notes*` is now denied by `R-PLAN-NUMBER-DISCOVERY` (a different guard, see note 1). |
| N141  | IN-SCOPE DEFECT                   | SH1 and the `cd` form of SH3 reproduce. SH2 (quoted space) and SH4 (`ln -s` then mkdir) are dismissed: limb 2                                                                                                                           | See section N141.                                                                                                                                                                                                                                                                                                                                                               |
| N178  | DISMISSED (threat model)          | `m=mkdir; $m CLAUDE/Plan/00999-x`: command word from a variable. Limb 1                                                                                                                                                                 | Probe allows it; the text `mkdir` is not visible.                                                                                                                                                                                                                                                                                                                               |
| N179  | IN-SCOPE DEFECT                   | Literal `mkdir 2>&1 CLAUDE/Plan/00999-x`                                                                                                                                                                                                | See section N179.                                                                                                                                                                                                                                                                                                                                                               |
| N180  | DISMISSED (threat model)          | `sudo $m CLAUDE/Plan/00999-x`: variable command word after a wrapper. Limb 1. The `00999''-x` quoting spelling is limb 2                                                                                                                | Literal `sudo mkdir CLAUDE/Plan/00999-x` is denied (`R-PLAN-FOLDER-MKDIR`).                                                                                                                                                                                                                                                                                                     |
| N185  | DISMISSED (threat model)          | `setsid $m CLAUDE/Plan/00999-x`: variable command word. Limb 1                                                                                                                                                                          | Literal `setsid mkdir CLAUDE/Plan/00999-x` is denied on main, so the in-scope form is covered.                                                                                                                                                                                                                                                                                  |
| N186  | IN-SCOPE DEFECT (brace form only) | `mkdir CLAUDE/Plan/0{0999,1000}-x` is allowed. The `$'00999-x'` and `$"…"` spellings and `$m` forms are dismissed: limb 2 (ANSI-C quoting of a folder name) and limb 1                                                                  | See section N186.                                                                                                                                                                                                                                                                                                                                                               |
| N187  | DISMISSED (threat model)          | `eval "$m CLAUDE/Plan/00999-x"`, `bash -c "$m …"`: command word from a variable inside a string. Limb 1                                                                                                                                 | Literal `bash -c 'mkdir CLAUDE/Plan/00999-x'` is denied (`R-PLAN-FOLDER-MKDIR`).                                                                                                                                                                                                                                                                                                |
| N188  | DISMISSED (threat model)          | `$m CLAUDE/Plan/$N`: command word and folder name both from variables. Limb 1                                                                                                                                                           | Probe allows it; nothing the daemon can read names a plan folder.                                                                                                                                                                                                                                                                                                               |
| N198  | DISMISSED (threat model)          | `chronic $m …`, `coproc $m …`, `strace -f $m …`, `env -S '$m …'`: variable command word. Limb 1                                                                                                                                         | Probe allows `chronic $m CLAUDE/Plan/00999-x`. Literal wrapper forms are denied (see N180, N185).                                                                                                                                                                                                                                                                               |
| N199  | DISMISSED (threat model)          | `$m CLAUDE/Plan//$N`, `$m CLAUDE/Plan$N`, `/bin/mkdi?`, `{mkdir,<pd>/00999-x}`, `mk$d`. Limb 1 for the variable forms, limb 2 for a glob or brace command word                                                                          | `cd CLAUDE/Plan && $m $N` is limb 1. The literal `cd … && mkdir …` part is a real defect, filed under N141.                                                                                                                                                                                                                                                                     |
| N200  | IN-SCOPE DEFECT                   | `git stash list; git stash` is allowed on main. The apostrophe-comment plus `git 'stash'` and `git "reset" --hard` shapes are dismissed: limb 2                                                                                         | See section N200.                                                                                                                                                                                                                                                                                                                                                               |
| N239  | DISMISSED (threat model)          | `bash -c "git \$'stash'"`: ANSI-C quoting of a git subcommand. Limb 2                                                                                                                                                                   | Probe allows it. `git $'stash'` is also allowed. No working purpose except defeating a parser.                                                                                                                                                                                                                                                                                  |
| N240  | NEEDS-OWNER                       | `script -q /tmp/typescript.log -c ls` and `script -O /tmp/out.log` are allowed. The shape is literal and has a working purpose, but the outcome is an out-of-root log file, which is not one of the protected outcomes the ruling lists | Owner to say whether an out-of-root `script` log needs a guard. Probe allows both.                                                                                                                                                                                                                                                                                              |
| N241  | IN-SCOPE DEFECT                   | False positives: git guards deny ordinary commands that only mention `git stash` or `git reset --hard`                                                                                                                                  | See section N241.                                                                                                                                                                                                                                                                                                                                                               |

Counts: FIXED-ON-MAIN 1, IN-SCOPE DEFECT 5, DISMISSED 8, KEEP-FAIL-CLOSED 0, NEEDS-OWNER 1.

Note 1: `ls /workspace/CLAUDE/Plan/*/PLAN.md` is also denied by `R-PLAN-NUMBER-DISCOVERY`
on main (a listing of plan files, not a number scan). This is not an entry from this scope and
is not counted. It may be worth a look by whoever owns that guard.

## N141: the mkdir guard misses real plan-folder creation (SH1, and `cd` form of SH3)

Outcome at risk: a hand-made plan folder claims a number the counter never recorded, so two
agents get the same number (the collision the guard exists to stop).

Each of these is allowed on main. The plain form is denied, so the guard is on:

- `mkdir -p CLAUDE/Plan/00999-x CLAUDE/Plan/Completed` (an archive path in the same command
  lets the creation through; `mkdir CLAUDE/Plan/00999-x` alone is denied).
- `mkdir CLAUDE/Plan/00999-x; echo done | wc -c` (a later `| wc`).
- `mkdir CLAUDE/Plan/00999-x # see CLAUDE/Plan/Completed/` (a trailing comment).
- `cd CLAUDE/Plan && mkdir 00999-x` and `cd CLAUDE && mkdir Plan/00999-x`. `cd sub && cmd`
  is named in the ruling as in scope. The ledger's `CDPATH` form is not; the plain `cd` is.

Dismissed parts: SH2 (`mkdir -p 'x /../CLAUDE/Plan/00999-x'`) and SH4 (`ln -s … && mkdir p/…`)
have no working purpose other than defeating the parser (limb 2).

## N179: a redirection before the operand hides the folder

Reproduction: `mkdir 2>&1 CLAUDE/Plan/00999-x` is allowed on main. The same command with the
redirection last (`mkdir CLAUDE/Plan/00999-x 2>&1`) is denied. The words after `2>&1` are read
as a new command. Outcome at risk: the same number collision as N141. A literal, visible shape,
rare but in scope.

## N186: a brace in the folder name after a literal `mkdir`

Reproduction: `mkdir CLAUDE/Plan/0{0999,1000}-x` is allowed on main. Brace lists are ordinary
shell (`mkdir -p Plan/{a,b}`), and the text is visible, so this is in scope. Outcome at risk: the
same number collision as N141. The ANSI-C and `$"…"` spellings in the same entry are dismissed.

## N200: a real `git stash` after a recovery form

Reproduction: `git stash list; git stash` and `git stash list && git stash push` are both
allowed on main. A plain `git stash` is denied (`R-GIT-STASH-PUSH`). The guard allows the whole
command when a recovery word such as `list` appears. Outcome at risk: stashed work that gets
forgotten or lost, the reason the rule exists. Looking at the list and then stashing is an
ordinary sequence. Dismissed from the same entry: `# it's` plus `git 'stash'` and
`git "reset" --hard` (quoting a subcommand has no working purpose, limb 2).

## N241: false positives from text that only mentions a guarded command

All of these are denied on main and none runs a stash, reset or amend:

- `git commit -m 'document the git stash guard'` denied (`R-GIT-STASH-PUSH`).
- `grep -n 'git stash' CLAUDE/ARCHITECTURE.md` denied (`R-GIT-STASH-PUSH`).
- `cat > notes.md <<'EOF'` with the line `never run git stash` denied (`R-GIT-STASH-PUSH`).
- `echo 'do not run git reset --hard'` denied (`R-GIT-RESET-HARD`).
- `gh pr create --title x --body 'we ban git stash and git reset --hard'` denied
  (`R-GIT-RESET-HARD`).
- `bash -c 'git commit -m "document --amend"'` denied (`R-GIT-COMMIT-AMEND`), while the same
  commit without `bash -c` is allowed.

The ledger says the `echo` and `grep` denials are by design (Plan 00228 Decision 2). The ruling
says a guard that denies ordinary commands fails the agents it helps, and a false positive is
fixed by narrowing. That points to a defect, but reversing Decision 2 is a coordinator call.

One real command is also hidden, on main: `git commit -m 'x\' ; git reset --hard ; echo 'y'` is
allowed. Bash ends the message at `\'`, so `git reset --hard` runs. A message ending in a
backslash is a plausible mistake. Outcome at risk: uncommitted work lost.

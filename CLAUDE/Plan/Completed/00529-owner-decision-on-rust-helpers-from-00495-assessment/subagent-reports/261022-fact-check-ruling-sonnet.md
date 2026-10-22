# Fact check: Plan 00529 ruling diff (Task 2 "Ruled" bullet, Task 2c, new Success Criterion)

Diff: untracked/scratch is not used for the diff; source is /workspace/untracked/plan-fact-check/00529-...diff.
Experiment files: /workspace/untracked/scratch/execfail/ (t.sh, t2.sh, t3.sh, t4.sh, bad = ELF-magic garbage, bad2 = text garbage).

## REFUTED (most consequential first)

**R1. "the failed `exec` exits 126 with nothing on stdout" (PLAN.md Ruled bullet; also report lines 54-56).**
In the deployed forwarder `set -euo pipefail` (pre-tool-use:15) precedes the guard. Under `set -e`, a failed exec of a
corrupt executable exits **1**, not 126. With `set -e` off it is 126. Measured:

| file                    | set -e | execfail | exit                               | stdout |
| ----------------------- | ------ | -------- | ---------------------------------- | ------ |
| bad (ELF-magic garbage) | no     | no       | 126                                | empty  |
| bad (ELF-magic garbage) | yes    | no       | **1**                              | empty  |
| bad2 (text, no shebang) | any    | any      | **127** (bash runs it as a script) | empty  |

The report's own evidence command used `/etc/hostname`, which is not executable (Permission denied, 126). That is not
a corrupt executable. Effect on the plan: the fail-open conclusion SURVIVES, because hooks.md:813-821 says any exit
other than 0 or 2 with empty stdout is a non-blocking error and the action goes ahead. Only the number is wrong. Reword
to "exits non-zero (1 under the generated `set -e`, 127 for a script-like file) with nothing on stdout". The regression
test must not assert 126.

**R2. Task 2c: "close the fail-open with `shopt -s execfail`" (implied sufficient; report task 1: "bash then survives a
failed exec instead of dying with 126").**
Under the forwarder's `set -e`, `execfail` alone does NOT survive: t3/t4 with set -e + execfail exit 1 and never reach
the next line (no "FELL THROUGH", no "REACHED AFTER EXEC"). It falls through only when `set -e` is off (rc 0, reaches
after-exec). Also `execfail` does nothing for the text-garbage case (127 either way, the file runs as a script).
Effect: Task 2c must also guard the exec (for example `exec ... || true`, or `set +e` around it and restore after), and
must decide how to treat a garbage file that is a text script (it is not an exec failure at all, so a marker cannot see
it). A red-first test with a real ELF-magic file would catch the first gap; the garbage-bytes test the plan names needs
both shapes.

## Claims table

| #   | Claim                                                                                                                         | Verdict                                | Evidence                                                                                                                                |
| --- | ----------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Today a missing relay binary falls through to the bash path                                                                   | VERIFIED                               | forwarder_generator.py:350 and pre-tool-use:25-30: the `if [[ -x ... && -S ... ]]` has no else; falls to `source init.sh` at line 32    |
| 2   | The bash path "still enforces every rule"                                                                                     | VERIFIED (by inspection)               | pre-tool-use:32-46 sources init.sh, ensure_daemon, send_request_stdin "PreToolUse"                                                      |
| 3   | The fall-through is "silent at the moment of the call"                                                                        | VERIFIED                               | no echo or marker in the guard (lines 348-358)                                                                                          |
| 4   | A broken (executable but corrupt) binary fails OPEN today                                                                     | VERIFIED (mechanism corrected, see R1) | exits 1/127, empty stdout; hooks.md:813-821 non-blocking for other exits                                                                |
| 5   | The failed exec exits 126                                                                                                     | REFUTED                                | R1                                                                                                                                      |
| 6   | `shopt -s execfail` closes the hole                                                                                           | REFUTED as sufficient                  | R2                                                                                                                                      |
| 7   | Guard sits at forwarder_generator.py ~348-357                                                                                 | VERIFIED                               | lines 348-357                                                                                                                           |
| 8   | `transport on` reports a provisioned binary (N525); `status` and SessionStart `relay_binary_checker` name path and fix (N523) | VERIFIED                               | handlers/session_start/relay_binary_checker.py exists; release note 011-relay-binary-problems-are-reported-not-silent.md; PLAN.md:49,64 |
| 9   | Merged `376612d38`                                                                                                            | VERIFIED                               | `git log -1 376612d38`: "Merge worktree-529-relay-loud ... (N523, N525)"                                                                |
| 10  | Evidence report subagent-reports/261022-forwarder-failure-advice-fable.md exists                                              | VERIFIED                               | in directory listing                                                                                                                    |
| 11  | The report has tasks 1-6 matching Task 2c's list                                                                              | VERIFIED                               | report lines 82-118 numbered 1-6 (item 7 is a coordinator follow-up, correctly excluded)                                                |
| 12  | Report's marker is carried through `init.sh`; daemon adds a warning line                                                      | UNVERIFIABLE-HERE (future work)        | no `execfail` or relay-unused marker anywhere in src or .claude/hooks (grep empty), so none of it exists yet, consistent with "[ ]"     |
| 13  | "Denying every tool call would also deny the commands that rebuild the relay"                                                 | UNVERIFIABLE-HERE (reasoning)          | report line 22 cites a carve-out `restart status logs stop start repair`; not checked against the handler                               |
| 14  | Release-notes directory `CLAUDE/UPGRADES/UNRELEASED/release-notes/` exists                                                    | VERIFIED                               | directory lists 011-..., 013-...                                                                                                        |

## Extra note

`HOOKS_DAEMON_RELAY_BINARY` can point anywhere, so a guard that sets the marker only on exec-return still misses a
binary that starts and then exits non-zero or hangs; Task 2c does not claim to cover that.

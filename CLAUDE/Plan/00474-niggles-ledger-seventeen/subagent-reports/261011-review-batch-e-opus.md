# Code Review: batch E (N400, N401, N402 part (a)), branch agent-a8b2dfbb8ae318a8c-68c99312 at ca9768e44

## Summary

The three fixes are sound in shape: N400 reuses the one message reader rather than adding a parser, N401 steps over
`-c k=v` inside the existing global-option reader, and N402(a) shares path judgement's reading through a new
`expand_cwd_references`. Targeted tests pass (234 passed: heredoc sinks, invocation directory, conflict marker gate).
One regression is introduced by the change (a crash on `cd ~user`), and several smaller defects follow.

Reviewed: 14 files, +504/-28. Issues: 0 critical, 3 important, 4 suggestions.

Probe: `untracked/scratch/review-batch-e/probe.py` (output in `probe-output.txt` beside it). Run from /workspace with
`PYTHONPATH=<worktree>/src <venv>/bin/python <worktree>/untracked/scratch/review-batch-e/probe.py`. The probe splices
the destructive reset command in at run time (`@R@`) so the file could be authored through the guards.

## Important Issues

### 1. `placement_problem(run, cwd)` now raises on `cd ~otheruser` (Confidence: 90%)

**Location:** `src/claude_code_hooks_daemon/utils/git_invocation_directory.py:56-58` (`_steps`)

**Problem:** `_steps` advances `here` with `here / Path(step).expanduser()` for every `cd` step that has no `$`,
backtick or glob character. A `~name` step is not excluded there, and `Path("~name").expanduser()` raises
`RuntimeError: Could not determine home directory` for an unknown user (also for bash's `~-` / `~+`, which Python reads
as user names). `_steps` runs at the top of `placement_problem`, BEFORE the loop that reports `~name` as "needs an
expansion", so the screen that used to protect `invocation_directory` from this input no longer runs first.

**Evidence (probe output):**

```
'cd ~nosuchuser_review && git commit -m x' -> RAISED RuntimeError: Could not determine home directory.
same, cwd=None -> the directory `~nosuchuser_review` needs an expansion the daemon cannot perform
```

On main the same command returns the readable problem. On the branch every caller that passes a cwd crashes:
`conflict_marker_commit_gate.handle`, `destructive_git` branch-delete and remote-delete notes, `merge_qa_advisor`,
and the PostToolUse `daemon_sync_after_merge`. The chain turns the SAFETY ones into "evaluation error, denied for
safety (RuntimeError ...)", so the verdict is still a deny, but with a crash reason instead of the remediation text,
and the non-safety handlers log a crash.

**Fix:** in `_steps`, end the chain (`here = None`) when the step fails the same predicate `placement_problem` uses
(`_EXPANSION.search(step) or (step.startswith("~") and not _HOME_PATH.match(step))`); extract that predicate into one
helper used by both so they cannot drift. Add a parametrised test in `tests/unit/utils/test_git_invocation_directory.py`
(`TestCwdExpansionsAreSteps`) for `cd ~nosuchuser && git commit -m x` and `cd ~- && git commit -m x` with a start
directory, asserting a problem string and no raise.

### 2. Test that cannot fail: `git checkout -b ...` row (Confidence: 85%)

**Location:** `tests/unit/handlers/pre_tool_use/test_git_guards_heredoc_sinks.py:97-98`

**Problem:** The row is commented "`-b` is a body flag only for gh; another command's `-b` value is not blanked", but
the command ends in `&& <reset-hard>` OUTSIDE the `-b` value. It is denied whether or not the `-b` value is blanked,
so it does not pin the `elif ... match.group("flag") in _GH_BODY_FLAGS` branch at
`src/claude_code_hooks_daemon/utils/shell_segmentation.py:1276`. Deleting that clause leaves this test green (the
value `x` is harmless either way).

**Fix:** replace it with a direct unit assertion on `strip_message_bodies`: for
`git checkout -b "$(cat <<'EOF'\nx\nEOF\n)"` the returned string equals the input (value not replaced by
`<REDACTED>`), and add the gh counterpart asserting it IS replaced. Those two pin the branch.

### 3. Comments describing the message reader now under-state what it reads (Confidence: 80%)

**Location:** `src/claude_code_hooks_daemon/utils/shell_segmentation.py:730` (pattern header "Matches a
`-m`/`--message`/`-F`/`--file` flag"), `:1240` (`strip_message_bodies` docstring "Blank every
`-m`/`--message`/`-F`/`--file` VALUE"), `:1251` ("the owning command must actually TAKE a message",
with `_MESSAGE_TAKING_COMMANDS` at `:766-771` not naming `gh`).

**Problem:** The pattern now also matches `-b`/`--body`, and `gh` is now an owning command that is not in
`_MESSAGE_TAKING_COMMANDS`. A reader of the docstring would not know `gh pr create --body '...'` is blanked, nor that
`-b` is deliberately never a message for git/hg/svn/jj (hg's `-b` is `--branch`). The only explanation of the new rule
is the inline comment at `:1272-1273`.

**Fix:** update the three comments to name `-b`/`--body` and the gh-only scoping (body flags only for `gh` in the
`_GH_DATA_SUBCOMMANDS` groups; never a message for the VCS commands).

## Suggestions (non-blocking; each is a plan task)

### S1. The executing-key deny-list is incomplete against its own stated contract (Confidence: 75%)

**Location:** `src/claude_code_hooks_daemon/utils/shell_segmentation.py:399-427` (`_GIT_COMMAND_CONFIG_KEYS`,
`_GIT_COMMAND_CONFIG_SUFFIXES`)

The comment says these are the "config keys whose value is a command git runs". The probe shows these are read as
inert and the body is then treated as data:

```
gpg.ssh.defaultKeyCommand=x inert= True   (suffix is "keycommand", not ".command")
core.gitProxy=x              inert= True
core.alternateRefsCommand=x  inert= True
merge.x.driver=x             inert= True
pager.commit=x               inert= True   (core.pager is listed, pager.<cmd> is not)
interactive.diffFilter=x     inert= True
remote.o.receivepack=x       inert= True
include.path=x               inert= True   (an included file can set core.fsmonitor)
```

Practical exposure is low and this is why it is not blocking: the body can only run if git spawns a command that
inherits stdin BEFORE it consumes the `-F -` message (core.fsmonitor during index refresh is the real one, and it is
covered, including mixed case `Core.FSMonitor`); hooks get /dev/null as stdin; signing and pager run after the read or
on a pipe. And under the threat model, an agent writing `-c gpg.ssh.defaultKeyCommand=sh` before a commit is not a
careless shape. `alias.*` is correctly absent: git never lets an alias shadow a built-in, and the subcommand must be a
built-in in `_GIT_DATA_SUBCOMMANDS`. Still, the most plausible hole is `include.path` / `includeIf.<cond>.path`,
because it imports any key.

Remediation: add `include.path`, `core.gitproxy`, `core.alternaterefscommand`, `gpg.ssh.defaultkeycommand`,
`interactive.difffilter`, `uploadpack.packobjectshook`; add suffixes `.driver`, `.receivepack`, `.uploadpack`, `.path`
(covers `includeif.*.path`, already-listed `core.hookspath`) and treat any `pager.` prefix as executing; or reword the
comment to say the list targets commands that may run before git reads stdin, naming `core.fsmonitor` as the vector.
Add `include.path` and `gpg.ssh.defaultKeyCommand` rows to `_DESTRUCTIVE_STILL_DENIED`.

### S2. Attached `-ckey=value` branch models a form git rejects (Confidence: 80%)

**Location:** `src/claude_code_hooks_daemon/utils/shell_segmentation.py:1977-1981`; ledger N401 status text
("separate or attached").

`git -cuser.name=x version` exits 129 with "unknown option" (git 2.39.5, checked here); git's option parser only
accepts `-c` followed by a separate argument. The branch is harmless (git exits before reading stdin) but it is code
for a shape that does not exist and the ledger documents it as supported. Remove the branch (an attached `-c...` then
falls to "not a data subcommand", the old conservative verdict), and drop "(separate or attached)" from N401. No test
covers the branch either way, which is consistent with it being dead.

### S3. `placement_problem`'s `cwd=None` default is used only by tests (Confidence: 70%)

**Location:** `src/claude_code_hooks_daemon/utils/git_invocation_directory.py:62`

All five production callers now pass `cwd`; the `None` path exists only for
`tests/unit/utils/test_git_invocation_directory.py:96,135,151`. Make `cwd` required and have those tests pass a
relative or non-repository path explicitly (the `relative` case is already a test). That removes a second, dead
behaviour mode from a guard helper.

### S4. `_steps` drops the `PWD=` guard its sister function keeps (Confidence: 70%)

**Location:** `src/claude_code_hooks_daemon/utils/git_invocation_directory.py:36-58` vs
`src/claude_code_hooks_daemon/core/utils.py:471,496`

`substitute_cwd_expansions` refuses to read `$PWD` when the command assigns `PWD=`; `_steps` does not, so
`PWD=/elsewhere; cd "$PWD" && git commit -m x` is placed in the hook cwd (probe line 35). Out-of-threat-model as an
evasion, so not blocking, but the docstring claims "the resolution path judgement applies", which it is not quite.
Remediation: when `run.assignments` or the command carries a `PWD=` assignment, leave the expansion unresolved (or
state the divergence in the `_steps` docstring).

## Positive Observations

- N400 extends the existing `_MESSAGE_BODY_PATTERN`/`value_can_substitute` path rather than inventing a second reader,
  and the still-denied list covers the right escapes: unquoted delimiter, bare substitution, non-`cat` receiver,
  `cat ... | bash`, trailing `&&`, a non-body gh flag. The probe confirms a trailing `$(...)` glued after the heredoc
  substitution inside the same `--body` value stays judged.
- `_steps` reads `-C` values in the directory the last `cd` reached, which is exactly the shell semantics, and has a
  test for it.
- `--config-env` and an unresolved `-c "$X"` stay non-inert; both checked.
- Gate rows were added in both corpora, and the conflict-marker gate tests show a marker is still found after the
  newly placeable `cd`.

## Verdict

CHANGES REQUIRED: Important 1 (a crash regression introduced by this branch), 2 (a test that cannot fail) and
3 (comments now wrong). The suggestions are non-blocking and should be filed.

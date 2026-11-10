# Code Review: Plan 00478 Task 2.2e (branch worktree-478-2e-contested-rows, 6bba54cc7..f1a8f6d8b)

## Summary

Three critical safety regressions. pipe_blocker only judges the FIRST non-whitelisted pipe, so
an unknown producer placed earlier now launders a blacklisted one later in the same command,
and wrapped blacklisted producers (env/timeout/sudo/nice/uv run/poetry run/xargs/bash -c) now
fall through to the "unknown" tier and are allowed. write_protected_paths now allows an awk
program writing to FILENAME/$1 over a LITERALLY NAMED protected file under a `dir/**` glob,
which contradicts the stated policy and the release note. destructive_git 2.2b is test-only
and passes. The deleted pipe_blocker tests were genuinely unknown-tier pins, but they leave
no compound or wrapper coverage at handle() level.

Reviewed: 16 files, +524/-433. Issues: 3 Critical, 2 Important, 3 Minor.

Probes (kept as evidence, run with the worktree venv, no -n):
- untracked/scratch/review-2e/test_probe_pipe_launder.py (branch: 13 fail; base: all 16 deny)
- untracked/scratch/review-2e/test_probe_wpp.py (branch: 6 fail; base: 1 fail, which is pre-existing)
- base results: untracked/scratch/review-2e/base_pipe.txt, base_wpp.txt (base src extracted to
  untracked/scratch/review-2e/base/src and run via PYTHONPATH)

Run:
  P=untracked/venv-workspace_untracked_worktrees_worktr-53b6-py313-0d6d49c6/bin/python
  $P -m pytest untracked/scratch/review-2e/test_probe_pipe_launder.py -o addopts="" -s -q
  PYTHONPATH=untracked/scratch/review-2e/base/src $P -m pytest ... (same files) for the base

## Critical Issues

### C1. An unknown pipe earlier in the command launders a blacklisted pipe (Confidence: 98%)

**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/pipe_blocker.py:479-502`
(`_find_offending_match` returns the FIRST non-whitelisted pipe) combined with `:1138-1147`
(the new early `return self._unknown_producer_verdict(...)`).

**Problem:** handle() classifies only the first offending pipe. Before this branch every
non-whitelisted pipe denied, so "first" was enough. Now, if the first non-whitelisted pipe is
unknown, the whole command is ALLOWED, and nothing ever examines a later blacklisted pipe.
This revives the exact bypass class the method's own docstring (lines 461-463) records as
fixed ("a cheap first pipe shadowed an expensive second one"), now with an unknown first
pipe instead of a cheap one.

**Evidence (branch → allow; base → deny):**
- `docker ps | tail -1 && pytest tests/ | tail -5`
- `docker ps | tail -1; npm test | tail -5`
- `foo | head -1 && cargo test | tail -3`
- `echo $(docker ps | head -1) $(pytest | tail -1)`

This also falsifies the deployed guidance ("EVERY pipe in the command is judged, on its own
producer ... `git log | head -2 && pytest | head -1` is blocked on the pytest half"). That
guidance still holds when the first pipe is whitelisted, but not when it is unknown.

**Fix:** iterate ALL offending pipes. Deny if ANY is prose, a compound closer or blacklisted,
and report that pipe's producer and rule. Only when every offending pipe is unknown, return
the advisory (one advisory naming each unknown producer). Add handle()-level regression
tests for the four commands above, with an unknown pipe before a blacklisted one in `&&`,
`;`, `||`, newline and `$( )` positions.

### C2. Wrapped blacklisted producers are now allowed as "unknown" (Confidence: 92%)

**Location:** `pipe_blocker.py:750-759` (`_matches_blacklist` searches the raw segment with
`^pytest\b`-style anchors), reached through the new unknown branch at `:1146`.

**Problem:** the blacklist never saw through wrappers, because the unknown tier denied them
anyway. Converting unknown to allow turns every wrapper spelling of a known expensive command
into an allow. The ruling keeps "a positively recognised danger" denying, and a wrapped pytest
is a recognised pytest. Plan 00412 removed `env` from the whitelist specifically so that
`env pytest tests/ | head -20` is judged on pytest (see the comment in
`strategies/pipe_blocker/common.py:56-64`). That fix is now silently undone: the command is
allowed. Its test
(`tests/unit/handlers/pre_tool_use/test_pipe_blocker_wrapper_commands.py:36-48`) only asserts
`matches() is True`, so it still passes. That test is now theatre.

**Evidence (branch → allow; base → deny):** `env pytest tests/ | tail -5`,
`timeout 60 pytest tests/ | tail -5` (a very common agent idiom), `sudo npm test | tail -5`,
`nice pytest | tail -5`, `bash -c 'pytest' | tail -5`, `uv run pytest | tail -5`,
`poetry run pytest | tail -5`, `xargs pytest < f | tail -5`,
`./scripts/qa/run_all.sh | tail -5`. (`python -m pytest` and `make test` still deny.)

**Fix:** before the blacklist check, strip wrappers with the shared `COMMAND_WRAPPERS` /
shell_segmentation unwrapping that the other guards use (env with assignments and -u, timeout
with its duration, nice -n, sudo, xargs, `uv run`, `poetry run`, `bash -c '<body>'`, judged on
its body), then match the wrapped command. Extend `test_pipe_blocker_wrapper_commands.py` to
assert `handle(...).decision == DENY`, not just `matches()`.

### C3 (graded Critical against the stated policy). write_protected_paths allows awk writing to a literally named protected file (Confidence: 90%)

**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/write_protected_paths.py:764-775`
(the new `elif computed_destination and name is None: self._note_unknown(cause)`) and the
awk call site at `:1259-1263`, which passes only the PROGRAM text, not the operands.

**Problem:** for a `dir/**` glob, the old code made a computed-destination awk program deny
whatever it mentioned. The new code denies only if the PROGRAM text names the directory. The
file operands, where the protected path is literally named, are never consulted. awk is on
READ_ONLY_VERBS, so the operand reads as a read. The policy says "deny stays wherever a listed
protected path is LITERALLY named in the command", and the release note says "Wherever a
listed path IS named in the command ... still denies". Both are false for this case.

**Evidence (glob `protected/**` unless noted; branch → allow+advisory, base → deny):**
- `awk '{print > FILENAME}' protected/x`  (rewrites the protected file in place)
- `awk '{print > FILENAME}' ./protected/x`
- `cd protected && awk '{print > FILENAME}' x`
- `awk '{print > $1}' protected/list`
- globs `["**", ".claude/ccy/ccy.env.local"]`: `awk '{print > FILENAME}' .claude/ccy/ccy.env.local`

(Pre-existing and unchanged: with only the literal-file glob, the same awk command is
`nomatch` on base and branch alike. File it separately; it is not a regression.)

**Fix:** when the awk program writes to a computed destination, judge its operand files
(resolved through roots/cd like any token) against every glob, and deny if any names a listed
path. Fall back to the unknown verdict only when neither the program nor any operand names
one. Add the five commands above as deny tests.

## Important Issues

### I1. The deleted and rewritten tests leave the compound and wrapper cases unpinned at handle() level (Confidence: 85%)

**Location:** `tests/unit/handlers/pre_tool_use/test_pipe_blocker.py`,
`test_pipe_blocker_comprehensive.py`, `test_pipe_blocker_unknown_verdict.py`.

Each deleted assertion I checked was genuinely an unknown-tier pin: docker, find, mymodule,
some_unknown_tool and unknown_input fixtures. None covered a blacklisted producer. But the
conversion never added the one test it needed most: "unknown pipe + blacklisted pipe in one
command still denies". It also never upgraded the wrapper and evasion tests that relied on
"unknown ⇒ deny" from `matches()`-only assertions to `handle()` decisions.
**Fix:** grep the pipe_blocker suites for `matches(...) is True` assertions on blacklisted
producers and add a `handle().decision == DENY` twin to each. Add C1's compound cases.

### I2. The release note, guidance and HANDLER_REFERENCE overstate what still denies (Confidence: 88%)

**Location:**
`CLAUDE/UPGRADES/UNRELEASED/release-notes/031-unknown-pipe-producer-and-unnamed-protected-glob-warn.md`,
`docs/guides/HANDLER_REFERENCE.md:744` and `:1289`, and `pipe_blocker.py:1230-1236`
(get_claude_md).

"Known expensive producers (pytest, npm, cargo, ...) ... still deny" is false for wrapped and
compound forms (C1, C2). "Wherever a listed path IS named in the command ... still denies" is
false for the awk case (C3). The release-note advice "add the producer to extra_blacklist"
does not help C1. **Fix:** correct the code, then keep the text. If any part of the gap is
accepted instead, state it explicitly in the note.

## Minor

- `pipe_blocker.py:471-472`: the docstring still says an empty producer is "deliberately NOT
  whitelisted, preserving the pre-existing 'unknown ⇒ block' tier". An empty producer now
  ALLOWS with an advisory naming an empty label. Update the comment and decide whether an
  empty or unextractable producer should be a cause of its own.
- `tests/unit/handlers/pre_tool_use/test_pipe_blocker.py` (TestHandleUnknown):
  `find . | tail -n 20` is the "unknown" fixture, but `^find\b` is on the WHITELIST
  (`strategies/pipe_blocker/common.py:66`). matches() is False for it, so these tests call
  handle() on a command the daemon would never dispatch. They pass through the fallback
  segment path and do not exercise the real unknown tier. Switch the fixture to
  `docker ps` or `mytool`.
- `write_protected_paths.py:395-402` `_REPHRASE` tells the agent to "name the protected path
  literally" to get a verdict. That is fine, but it also invites rewriting unreadable text.
  No action is needed beyond C3.

## Verified OK

- destructive_git 2.2b: no src change in the range (diff touches only
  `tests/.../test_destructive_git_force_removal.py`). The 45 tests in that file plus the
  wrapper suite pass on the branch.
- write_protected_paths: redirect, tee, cp, mv, rm, truncate, ./ paths, `..`, quoting, a
  same-command variable, brace expansion, literal-prefix globs, brace-cap overflow and an
  unclosed quote all still deny when the path is literally named (21 probe cases).
- A terminal handler's ALLOW does not end the PreToolUse chain (`core/chain.py:8-16`,
  `:1087-1093`), so the new advisory allows do not short-circuit other guards.
- The prose and compound-closer denies are preserved for the offending segment.
- VERDICT_LOG.md `rule` row edit is accurate.

## Verdict

REQUEST CHANGES. C1 and C2 let known-expensive commands through pipe_blocker, and C3 lets a
literally named protected file be rewritten. All three are regressions against base.

# Plan 00556: secret guard bare dotted token mentions

**Status**: In Progress
**Created**: 2026-10-31
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #145, #146, #141, #142, #143, #144

## Overview

`secret_file_guard` refuses a Bash command (R-SECRET-BASH-MENTION) and refuses
authoring a script (R-SECRET-SCRIPT-AUTHOR) whenever a single word matches a
protected glob. That holds even when the word is not a path and names no file.
Issue #145 reports this for a NetworkManager setting key whose name ends in
`.secrets`, used as a positional argument to `nmcli`. No file is read, but the
default `*.secret*` glob matches the word. The reporter's client worked around
it by building the key from its parts at runtime.

This is a safety control, and its breadth is a recorded project decision. The
handler's guidance (`secret_file_guard.py:1814-1819`) says "`*.secret*` is
intentionally broad (a deliberate project decision) … That is the accepted
cost". Plan 00356's Non-Goals likewise keep "the deliberate breadth of
`*.secret*`". Narrowing which tokens count as a mention therefore reopens an
owner ruling. This plan records the question and the options. Building starts
only after the owner decides.

Prior art: Plan 00306 (plain words containing "secret" stop matching), Plan
00356 (bracket-glob false positives) and Plan 00478 (UNKNOWN verdicts become
advisories). Read Plan 00478 before choosing an advisory option, because it
owns the deny/advisory verdict policy.

## Owner decision required

Should a bare dotted word count as a protected-file mention, and if not, which
words? Options:

- **(a) Keep as is.** The breadth stays the accepted cost. Close #145 with the
  rationale, and document the split-name workaround or a `mode: replace`
  narrowing.
- **(b) Path-like tokens only.** A token is a mention only when it is
  path-like: it contains `/`, or starts with `.`, `~` or `$`. A token also
  counts when it resolves to an existing file or one in the protected-file
  index, or when it is the operand of a file-opening command. Every other
  match is allowed.
- **(c) As (b), but advise rather than allow.** A bare-word match that names no
  file becomes an advisory instead of a deny. This sits inside Plan 00478's
  verdict policy.
- **(d) Opt-in option.** A handler option, default off, gives (b) or (c)
  per project, and the default stays fail-closed.

Risk to weigh for (b) and (c): a relative filename with no `/` (`cat app.secret`) is a bare dotted token. It is protected only if the existence or
index check catches it. A file that is created later, or one outside the index,
would then pass.

## Goals

- Record the owner's ruling on #145 and implement it with TDD. The reported
  token shape gets a red test first, and the real-file shapes get tests that
  must stay denied.

## Non-Goals

- Changing the default `protected_paths` globs.
- Adding any agent-typed escape hatch (`MUST_..._BECAUSE`).

## Tasks

### Phase 1: Decide

- [x] ✅ **Task 1.1**: The owner approved fixing every secret-guard false
  positive (#141–#146). The condition: every existing true-positive test
  still denies (journal `122834Z-decision-0dbcad.md`). The owner did not name
  an option for #145. The coordinator reads that approval as option **(b)**,
  the narrowest option that removes the false positive: a mention is a token that is path-like, or that exists or is
  indexed, or that is a file-opening operand. Option (b) allows the false
  positive. The existence/index/operand conditions keep `cat app.secret`
  denied.

### Phase 3: The rest of the secret-guard false-positive cluster

Issues #141–#146 now share this plan, because all of them are false positives
in a guard over protected paths. Every issue except #141 lands in
`secret_file_matching.py` / `secret_file_guard.py`. #141 lands in
`handlers/pre_tool_use/write_protected_paths.py`. They are worked in turn on
one worktree branch, with one commit per issue and a red test first each
time.

- [ ] ⬜ **Task 3.1** (#146): a trusted consumer command that redirects with
  `2>&1` is denied, while a plain `>` is allowed.
- [ ] ⬜ **Task 3.2** (#141): read-only awk is denied under a wildcard-only
  `write_protected_paths` glob. In `write_protected_paths.py`,
  `_AWK_WRITING_PROGRAM_RE` reads `>=` and the regex `|` as a redirect or a
  pipe. The issue also reports a second fault feeding the same fallback, in
  `_text_naming`.
- [ ] ⬜ **Task 3.3** (#142): a bare `**` is judged as a recursive globstar
  that matches dot-files. `*` and `**/*` get inconsistent verdicts.
- [ ] ⬜ **Task 3.4** (#143): a dotted module path in a Python string literal
  is treated as a file mention.
- [ ] ⬜ **Task 3.5** (#144): the grep-pattern-only exemption is lost on a
  compound command. Judge each statement separately; `grep 'id_rsa' d; cat id_rsa` must stay denied.

### Phase 2: Build (#145)

- [ ] ⬜ **Task 2.1**: Write red tests. Cover the reported setting-key shape in
  a Bash command and in an authored script. Also cover the real-file shapes
  that must stay denied: a relative bare name, a path, a glob, a variable and
  a file-opening operand.
- [ ] ⬜ **Task 2.2**: Implement the choice in `find_protected_mention` and the
  script-content route. Update the handler guidance's "accepted cost"
  paragraph to match.
- [ ] ⬜ **Task 2.3**: Write a release note in the pending-release holding area.

## Success Criteria

- [ ] The owner's ruling is recorded, and #145 is answered and closed.
- [ ] If behaviour changes, the reported shape is allowed (or advised) and
  every real-file shape is still denied, each proven by a test.
- [ ] If behaviour changes, a release note is in `CLAUDE/UPGRADES/UNRELEASED/`
  (the pending-release holding area). If it does not, the plan records that it
  has no release-bound consequences.

## Delivery & Milestones

- Plan filed from issue #145 and parked as `agent-needs-human`.

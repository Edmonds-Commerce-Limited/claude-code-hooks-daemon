# Plan 00347: handlers raise on unstattable paths

**Status**: Not Started
**Created**: 2026-09-08
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

Python's `pathlib` treats a small set of stat failures as "the answer is no":
`ENOENT`, `ENOTDIR`, `EBADF` and `ELOOP` are swallowed and the predicate returns
`False`. **`EACCES` is not in that set.** So `Path.exists()`, `Path.is_file()`
and `Path.is_dir()` all raise `PermissionError` when any directory in the parent
chain lacks `+x` for the daemon's user.

Handlers call those predicates on paths taken straight from a user's tool input.
The daemon has no say in whether it can stat them.

Measured on an unprivileged process against a mode-000 parent, not reasoned
about:

```
exists()  RAISES PermissionError: errno=13
is_file() RAISES PermissionError: errno=13
is_dir()  RAISES PermissionError: errno=13
```

`core/utils.py:_written_paths` had this defect and is fixed at `f17fabcd`. This
plan is the remaining class: roughly a dozen more call sites in `handlers/` that
judge a path supplied by the caller.

## What it actually does — the chain catches it

`chain.py:291` catches a raising handler, so this is not a daemon crash. It
becomes one of two things, decided by a single setting, and both are wrong:

| `daemon.strict_mode`  | Result                                                    |
| --------------------- | --------------------------------------------------------- |
| `true` (this repo)    | Spurious DENY — "Handler X crashed - blocking for safety" |
| `false` (**default**) | Fail-open — that handler's guard silently stops applying  |

A client project runs the default. For a DENY handler — `write_clobber_guard`,
the untracked-memory policy — an unreadable parent directory is therefore a
silent exemption, which is the direction a guard must never fail in. In this
repository the same defect inverts into blocking legitimate work instead.

## This class has already been paid for once

`comment_size.py:227` carries this comment:

> `errors="replace"`, never a bare decode. This reads a file the daemon did not
> write and has no encoding contract with [...] An unguarded decode raised
> `UnicodeDecodeError` straight out of `handle()`.

Same shape, different exception: an unhandled error escaping a handler because
the input came from outside the daemon's control. That one was fixed in place.
`PermissionError` is the unfixed sibling, spread across many call sites rather
than one.

## How it was found, and why testing it is not obvious

The `_written_paths` instance made GitHub CI red: 39 assertions in
`test_markdown_organization.py` died with `PermissionError`, because they name
`/root/.claude/...` and a runner's `runner` user cannot traverse `/root`. Every
one passed locally the whole time, because this container runs as root.

**A permissions-based test fixture is worthless here.** Running as root defeats
mode bits entirely, which is exactly how this reached CI unnoticed. Tests must
force the error — `f17fabcd` does it by patching the predicate to raise.

## Goals

- A handler judging a path it cannot stat returns a decision instead of raising.
- The fallback each site chooses is explicit and reviewable, not incidental.
- A new call site cannot silently reintroduce it.

## Non-Goals

- Converting all 73 stat calls under `handlers/`. Most read daemon-controlled
  paths — config files, install directories, caches — where `EACCES` is
  genuinely exceptional and should surface. Blanket-guarding them would hide
  real failures, which is the antipattern `audit_error_hiding.py` exists to
  catch.
- Changing `chain.py`'s catch. Converting a crash into a decision at the
  boundary is a backstop, not a fix: it cannot know what the handler meant.
- Changing the `strict_mode` default.

## Tasks

### Phase 1: One canonical answer

- [ ] ⬜ **Task 1.1**: Add EACCES-safe path predicates with an explicit contract
  for what an unstattable path means. `f17fabcd` establishes the reasoning to
  reuse: an unstattable path is not KNOWN to be a directory, so it is treated as
  not one — the same answer pathlib already gives for every stat failure it
  ignores. Each must LOG; a silent fallback fails `audit_error_hiding.py`, and
  rightly, because "the guard decided" and "the guard could not look" are
  otherwise indistinguishable to whoever asks why a policy did not fire.

### Phase 2: Convert the sites that judge caller-supplied paths

- [ ] ⬜ **Task 2.1**: Convert the confirmed tool-input call sites:
  `write_clobber_guard.py:155`, `lint_on_edit.py:265`, `comment_size.py:226`,
  `plan_qa_edit.py:165`, `docs_qa_edit.py:140`,
  `validate_eslint_on_write.py:229`, `markdown_table_formatter.py:224`,
  `plan_number_helper.py:201`, `staged_lint_gate.py:240`. Each needs its own RED
  first: the correct fallback VALUE differs by site, and a wrong fallback on a
  DENY handler is a bypass rather than a crash.
- [ ] ⬜ **Task 2.2**: Classify every remaining predicate in `handlers/` as
  caller-supplied or daemon-controlled. The classification IS the deliverable —
  daemon-controlled sites stay exactly as they are, with the reason recorded.

### Phase 3: Stop it coming back

- [ ] ⬜ **Task 3.1**: A static QA gate over `handlers/`, modelled on
  `scripts/qa/check_canonical_callers.sh`, which already enforces "go through
  the canonical helper, or carry an inline `# canonical-resolver-exempt: <reason>` marker" for venv resolution. The same shape applies here, so a
  daemon-controlled site records its reason in place instead of being
  indistinguishable from an oversight.

## Success Criteria

- [ ] A handler given a path behind an unreadable directory returns a decision,
  proved by a test that FORCES `EACCES` rather than relying on mode bits.
- [ ] Every remaining raw predicate under `handlers/` is either
  daemon-controlled or carries an in-place exemption reason.
- [ ] A newly added raw predicate on a caller-supplied path fails a check.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00347-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not yet started. The originating instance (`core/utils.py:_written_paths`) is
  fixed at `f17fabcd`, which is where both the reasoning and the test technique
  come from.

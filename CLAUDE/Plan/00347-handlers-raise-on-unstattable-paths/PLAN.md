# Plan 00347: handlers raise on unstattable paths

**Status**: In Progress
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

### Phase 1: Make the caller choose

**This phase was originally written as "one canonical answer", reusing
`f17fabcd`'s rule that an unstattable path is treated as not-a-directory —
the same answer pathlib gives for the stat failures it already ignores. Task
2.2's classification pass falsified that.** In `write_clobber_guard.matches()`
the code is `if not Path(path).is_file(): return False`, meaning "creating a
new file destroys nothing", so a `False` fallback makes the guard decline to
fire and the clobber it exists to prevent is silently allowed. There, the safe
fallback is `True`.

A single canonical fallback is therefore not merely unhelpful, it is dangerous:
it looks principled while inverting the guard at some sites. The helper must
make the decision explicit at the call site instead of supplying a default.

- [ ] ⬜ **Task 1.1**: Add EACCES-safe path predicates whose signature REQUIRES
  the caller to state the value an unstattable path yields — no default. The
  parameter name should carry the reasoning (what this site means by "I could
  not look"), so review sees the choice rather than an omission.
- [ ] ⬜ **Task 1.2**: Every predicate LOGS on the EACCES path. A silent
  fallback fails `audit_error_hiding.py` — correctly, because "the guard
  decided" and "the guard could not look" are otherwise indistinguishable to
  whoever asks why a policy did not fire. `f17fabcd` was rejected by that
  auditor on its first draft for exactly this.

### Phase 2: Convert the sites that judge caller-supplied paths

- [ ] ⬜ **Task 2.1**: Convert the 14 caller-supplied sites Task 2.2 identified.
  Each needs its own RED first: the correct fallback VALUE differs by site, and
  a wrong fallback on a DENY handler is a bypass rather than a crash. Three
  shapes to expect, all evidenced in the report:
  - **Inverted** — `write_clobber_guard.py:155` needs `True`; `False` exempts
    the clobber guard.
  - **Naive-safe** — `comment_size.py:226` is fine with `False`, because its
    consumer reads "no prior content" as growth and so biases toward the DENY.
  - **No single safe boolean** — `plan_qa_edit.py:165` and `docs_qa_edit.py:140`
    feed `file_exists_before` to three different consumers. One of them,
    `plan_qa/checks/archive_immutability.py:30`, tests `is not True`, so both
    `False` and `None` silently disable it. (It is `Level.ADVISE`, so the cost
    there is a lost advisory rather than a lost block — but the shape is the
    warning: a value consumed by several checks cannot be defaulted once.)
- [x] ✅ **Task 2.2**: Classify every predicate in `handlers/` as
  caller-supplied or daemon-controlled. **74 predicate calls across 73 sites:
  14 caller-supplied, 59 daemon-controlled, none left uncertain.** Full trace
  per site in
  [subagent-reports/260908-eacces-site-classification-sonnet.md](subagent-reports/260908-eacces-site-classification-sonnet.md).
  The pass found four caller-supplied sites the hand-curated list had missed —
  `markdown_table_formatter.py:233` (sibling of the listed `:224`),
  `github_auto_close_keywords.py:242`, `tdd_enforcement.py:358` and
  `worktree_remove_handler.py:57` — which is the argument against converting
  from a list someone wrote by eye.

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

- **Task 2.2 complete** — all 73 sites classified (14 caller-supplied, 59
  daemon-controlled), and the pass falsified Phase 1's original "one canonical
  fallback" design before any code was written to it.
- The originating instance (`core/utils.py:_written_paths`) is fixed at
  `f17fabcd`, which is where the test technique comes from — force the
  `EACCES`, never rely on mode bits.

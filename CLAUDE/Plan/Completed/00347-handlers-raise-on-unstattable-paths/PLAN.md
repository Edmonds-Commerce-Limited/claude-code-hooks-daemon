# Plan 00347: handlers raise on unstattable paths

**Status**: Complete
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

- [x] ✅ **Task 1.1**: `utils/path_predicates.py` — `path_exists`,
  `path_is_file`, `path_is_dir`. The fallback is a **keyword-only argument with
  no default**, named `unreadable_means`, so the value is always read together
  with what it means at that site: `path_is_file(p, unreadable_means=True)`
  states the answer, where a positional `True` would state nothing. The return
  type is `bool | _Fallback`, not `bool` — `None` has to survive as itself for
  the tri-state `file_exists_before` consumers.
- [x] ✅ **Task 1.2**: The EACCES path logs a warning naming the path, the
  predicate, the errno and the substituted answer. A silent fallback fails
  `audit_error_hiding.py` — correctly, because "the guard decided" and "the
  guard could not look" are otherwise indistinguishable to whoever asks why a
  policy did not fire. `f17fabcd` was rejected by that auditor on its first
  draft for exactly this. A successful stat logs nothing: the warning marks an
  abstention, and noise is how a real one gets missed.

The fallback covers **only** the failures pathlib itself raises on. A missing
path still answers `False` through the normal return, never through the
fallback — "not there" and "could not look" are different facts, and conflating
them would be a louder lie than the one this fixes.

### Phase 2: Convert the sites that judge caller-supplied paths

- [x] ✅ **Task 2.1**: All 14 caller-supplied sites converted, each RED first.
  The three shapes the report predicted all appeared, and the split was
  **11 / 1 / 2**:
  - **Inverted** — `write_clobber_guard.py:155` takes `True`; `False` exempts
    the clobber guard. The handler already held the answer one method away:
    `_count_lines` degrades to `0` on an unreadable file because "a file that
    cannot be read is still worth blocking". Line 155 was standing the write
    down before that reasoning was reached.
  - **Naive-safe** — the other 11 take `False`, each for its own consumer's
    reason rather than by rule. `comment_size.py:226` is the one where `False`
    is right *positively*: its consumer reads "no prior content" as growth, so
    the naive fallback biases toward the DENY.
  - **No single safe boolean** — `plan_qa_edit.py:165` / `docs_qa_edit.py:140`
    take `None`. `CheckContext` already types `file_exists_before` as
    `bool | None`, and its three consumers disagree about `False`
    (`archive_immutability` tests `is not True`, `task_grammar` `is False`,
    `template_metadata` `is not False`).

**The report recommended `True` for that last pair, and it is wrong.**
`archive_immutability` tests `is not True`, so its author already decided that
uncertainty should not raise the advisory — forcing `True` from the producer
overrides a choice the consumer made deliberately, and sends `read_text()`
into the same `PermissionError` one line later. Passing `None` also changed a
branch that was safe while the value was boolean: `if not exists_before` is
true for `None`, which would have recorded a plan-number allocation for a file
that may well exist. Narrowed to `is False`.

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

- [x] ✅ **Task 3.1**: `scripts/qa/check_eacces_safe_predicates.py`, the 26th
  QA gate, modelled on `check_canonical_callers.sh`: go through the canonical
  helper, or carry an inline `# eacces-safe-exempt: <reason>` marker. A marker
  with no reason does not exempt — an empty one is a silencer, not a record.

**Scope was the real decision.** Only some handler families can receive a path
the daemon did not choose: a `PreToolUse`/`PostToolUse` handler reads
`tool_input.file_path`, a worktree handler reads one from its event payload. A
`SessionStart` or `status_line` handler has no such input, so its paths are
daemon-built by construction — requiring markers there would mean 33 comments
asserting something already guaranteed, and noise is how a real marker stops
being read. An **unrecognised** family is scanned, not skipped: a gate that
defaults to "skip" silently stops covering whatever is added after it was
written, which is this plan's own failure mode.

That left 26 sites needing a recorded reason, each written from what the path
actually is — the daemon's own source tree, a configured plan directory, a
linter binary, an entry of a directory just traversed.

## Success Criteria

- [x] A handler given a path behind an unreadable directory returns a decision,
  proved by a test that FORCES `EACCES` rather than relying on mode bits — 80
  tests across four files, each opening with a vacuity guard.
- [x] Every remaining raw predicate under `handlers/` is either in a family that
  cannot receive a caller-supplied path, or carries an in-place exemption
  reason.
- [x] A newly added raw predicate on a caller-supplied path fails a check —
  `eacces_safe`, verified against fixtures for all three predicate names, all
  three tool-input-bearing families, and an unrecognised family.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00347-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- **Task 2.2 complete** — all 73 sites classified (14 caller-supplied, 59
  daemon-controlled), and the pass falsified Phase 1's original "one canonical
  fallback" design before any code was written to it.
- **Phase 1** — `utils/path_predicates.py`, whose signature is the deliverable:
  the fallback is keyword-only with **no default**, so the answer is chosen at
  each site rather than inherited.
- **Phase 2** — 14 sites, split 11 `False` / 1 `True` / 2 `None`. The one
  `True` (`write_clobber_guard`) is the proof that a single canonical fallback
  would have been dangerous rather than merely unhelpful.
- **Phase 3** — the `eacces_safe` QA gate, plus 26 in-place exemption reasons.
- The originating instance (`core/utils.py:_written_paths`) is fixed at
  `f17fabcd`, which is where the test technique comes from — force the
  `EACCES`, never rely on mode bits.

## What this plan got wrong, twice

Both times the error was **trusting a conclusion instead of its evidence**, and
both times the repository caught it rather than a review.

Phase 1 was written as "one canonical answer" and was falsified by the
classification pass it had itself commissioned. The delegated report then
recommended `True` for `plan_qa_edit`, and that was wrong too — its mechanism
was exact, its recommendation did not follow from it, and reading
`archive_immutability` directly showed the consumer had already decided what
uncertainty should mean.

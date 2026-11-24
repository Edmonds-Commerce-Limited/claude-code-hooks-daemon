# PR #246 review fixes (ledger cap, temp cleanup, real-runner tests)

This dispatch was not plan work. It was made for Plan 00634, on branch
`plan-00634-human-approval-check`, in worktree
`/workspace/.claude/worktrees/agent-a6328547e60968275-2a1ab764`. The cross-worktree
write guard blocked this report at the main-checkout path, so it is committed on the
PR branch instead.

## 1. Ledger cap (LOW, real)

- **Root cause:** confirmed. `CiteLedger._load` used `decode_json_document`. That
  function's fixed 64 KiB cap (`MAX_OUTPUT_BYTES`) refused the ledger long before the
  documented 256 KiB.
- **Fix:** `decode_json_document` now takes a keyword-only `max_bytes`, which defaults
  to `MAX_OUTPUT_BYTES`, so CLI callers are unchanged.
  - The ledger passes `MAX_LEDGER_BYTES`.
  - The duplicate-key and depth checks still apply, without being copied.
- **Bounded size:** the ledger now keeps entries in use order, oldest first. The
  version `v` and the row format are unchanged.
  - Before each save, `_bounded_body` evicts the oldest rows until the document fits
    in `MAX_LEDGER_BYTES`.
  - If even the use being recorded cannot fit, the save refuses with `UNAVAILABLE`.
  - Files written by the old code are sorted. They load as they are, with file order
    taken as age.
- **Trade-off (please weigh):** an evicted cite becomes usable again. Eviction starts
  only after about 3,900 recorded uses. The `CiteLedger` docstring says so and
  recommends pairing single use with `max_line_age_seconds` for a hard bound.
- **Tests, written to fail first:**
  - A valid ledger padded to exactly the cap is read.
  - One byte over the cap refuses. This replaces the whitespace-only test, which never
    reached the limit.
  - A ledger seeded near the cap accepts 10 more uses. All are recorded, the file never
    passes the cap, the oldest seeded entry is evicted and the newest is kept.
  - Use order is kept, not sorted.
  - Two tests of `decode_json_document(max_bytes=...)` are in `test_teamchat_seat.py`.

## 2. Temp file left after a failed rename (LOW)

- After any `OSError`, `_save` now removes the temp file through `_discard`. If the
  unlink also fails, `_discard` logs it with `log_and_continue`. That happens in the
  existing test where the temp file's parent is a regular file.
- New test, written to fail first: `test_a_failed_rename_leaves_no_temporary_file`
  patches `Path.replace` to fail.
- The comment at `_LEDGER_LOCK` documents the known limit. There is no cross-process
  lock, because a single daemon is the only writer.

## 3. Real-runner tests (LOW, test gap)

- Each test builds a fake kit at `tmp_path/kit/bin/teamchat`: a `/bin/sh` script with
  mode 0755. It runs through `TeamchatVerifyCli()` with the real
  `default_command_runner`.
  - `exit 23` gives `LINE_NOT_FOUND`.
  - Invalid UTF-8 output gives `ANSWER_UNREADABLE`.
  - A control test shows a valid answer from the same fake kit passes. So the refusals
    come from the output, not from the kit being rejected as untrusted.
- These tests passed on their first run, which is expected when filling a test gap.
- **Finding, not changed:** an otherwise valid record with an invalid byte inside
  `text` **passes**.
  - Why: the runner decodes with `errors="replace"`, and `text` is never used. The
    probe is at `/workspace/untracked/scratch/pr246-fix/probe_badbyte.py`.

  - Why not fixed here: a strict runner would also change `whoami`, which shares it,
    and would break the runner's never-raises contract.

  - Options:

    1. Make strict decoding a runner parameter.
    2. Refuse in `parse_verify_answer` when U+FFFD appears.
    3. Accept it, since the text is ignored.

    The coordinator decides.

## QA (targeted)

- **Formatting and lint:** black and ruff are clean on the 4 changed files.
- **Types:** `mypy --strict` is clean on `human_approval.py` and `teamchat_seat.py`.
- **Tests:** `test_human_approval.py`, `test_teamchat_seat.py`,
  `test_human_approval_check.py` and `test_human_approval_detector_seams.py` all pass.
  With `tests/unit/qa` added the run was 2930 passed, 27 failed, 4 skipped. All 27
  failures are environmental and unrelated: `VenvResolutionError` / `MainMovedError`
  ("no QA interpreter for" this venv-less worktree) in the llm_qa main-moved,
  interpreter-resolution and plugin-coverage tests. None touch the changed files.
- **bandit** (`-s B101`, as CI runs it) is clean on the changed files; **deptry** is clean.

## Follow-up commit (after b07200442)

- Docs updated for the eviction semantics, so the "once per act class" statements stay
  true: `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.77.0.yaml` (`single_use_cites`
  description) and `docs/guides/HANDLER_REFERENCE.md` (the `human_approval_check` options
  line; `check_handler_reference.py` is clean). Neither release note gave a ledger size
  figure, so neither was changed.
- Added a test for the refusal branch: a single use too large to fit gives `UNAVAILABLE`
  and writes no file.
- Added a discriminating test for the decode path: a real-runner answer that is otherwise
  valid but has `\377` inside `id` gives `ANSWER_MISMATCH`. This sharpens the finding
  above: an invalid byte is let through only when it sits in a field the decision never
  reads, such as `text` or `headline`.

## CI "QA static" failure (3.11/3.12/3.13), found at 7bf7e1415

- Cause: bandit B404 (Low) on the bare `import subprocess` in `utils/human_approval.py`
  (the import exists only for `subprocess.TimeoutExpired`). Every other static step
  before bandit passed; deptry, which runs after it, was never reached and passes locally.
- Fix: annotated the import with `# nosec B404` and a reason, matching the project
  convention (`core/release_slate.py`, `utils/teamchat_seat.py`).
- **Not needed:**
  - No handler text changed, so `HOOKS-DAEMON.md` was not regenerated.
  - The release note gives no ledger size figure.
  - No `return None` was added inside an `except`.

## Attribution note

The dispatch asked for a `Claude Sonnet 5.5` co-author line. The session's attribution
reminder specifies `Claude Opus 5.5`, and only the user's own instructions override
that reminder. The commit uses the Opus line.

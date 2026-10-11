# Plan 00500 follow-up: the `changed` tier selects shards, not the suite

Branch: `agent-ac60dcdb33334a059-ef11a181` (worktree branch). Commit: see the
final reply (the hash cannot be written into the commit that carries this file).

## What was asked

Owner: tests for things that have not been touched should be skipped during
WIP lifecycle QA. Replace the whole-suite fallback of `llm_qa.py changed` with
the narrowest set of declared shards a change can reach, never under-testing,
and report which shards were chosen and why.

## What the old fallback actually was

`changed` never ran the whole suite. A changed file with no covering test
(`uncovered`) or a reach over 40 test files (`too-broad`) was recorded as
UNMAPPED and FAILED the run unless `--allow-unmapped` said the coordinator's
full gate would cover it. So for the agent, "fallback to the whole suite" meant
"fail, or hand the file to the full gate". The fix turns most of those files
into a bounded shard run.

## Design of the rule

New: `scripts/qa/changed_shard_reach.yaml` (the one declaration),
`src/claude_code_hooks_daemon/qa/shard_reach.py` (loader, glob matcher, shard
targets), `select_tests(..., shards=, reach=)` in
`scripts/qa/run_changed_tests.py`, flags `--shards` / `--reach` (default to the
repo's files).

Applies only to a file the named-test mapping could not cover (`uncovered` or
`too-broad`). A mapped file is untouched, so every previously narrow selection
is unchanged. A changed test file still selects itself only.

For such a Python file under `src/`, `scripts/` or `tests/`, the shards are the
UNION of:

1. its FLOOR, declared by glob in `changed_shard_reach.yaml`:
   - `src/**/*.py` -> `integration`, `acceptance-and-other` (these spawn the
     daemon and load the package dynamically, so no import names the code);
   - `src/claude_code_hooks_daemon/handlers/**` -> also `unit-handlers`;
   - `src/claude_code_hooks_daemon/daemon/**` -> also `unit-daemon`;
   - `scripts/**/*.py` -> `unit-tooling`, `integration`;
2. the shards owning every test that statically refers to the file (mirror,
   path/import references, conftest subtree) and one hop of dependents'
   tests, counted WITHOUT the 40-file cap (the cap only decides what is worth
   naming; for soundness the whole reach is wanted).

The union is only ever wider than what can reach the file. Shards without an
`ignore` run as directories; remainder shards (`unit-tooling`,
`acceptance-and-other`) run as explicit file lists, so nothing runs twice and
no `--ignore` sits beside explicit selections. The run's `selected` list is the
mapped tests plus those targets, pruned of duplicates.

Reporting: `changed_tests.json` gains `shards` (shard -> `file: why` lines);
each mapping entry gets `rules: [..., "shard-reach"]` and `shards`; the
`run_changed_tests.py` text and the `llm_qa.py changed` summary print a
`shards chosen:` block, and print `whole suite kept for: <file>: <why>` for the
files below.

## What still needs the whole suite, and why

Kept as an unmapped file with reason `whole-suite` and its why (it still fails
the run unless `--allow-unmapped`, exactly as before, because the full gate
covers it):

- declared triggers in `changed_shard_reach.yaml`: `pyproject.toml`, `uv.lock`
  (settings and dependencies every shard uses), root `tests/conftest.py`
  (loaded by every test), `tests/support/**` (helpers imported dynamically by
  fixtures), `scripts/qa/**` (the tooling that decides what runs; no shard is
  narrower than what it gates);
- any file that is not Python source and has no declared rule in
  `changed_tests_map.yaml` (nothing statically connects it to a test);
- a reach through the root conftest;
- a Python file with no reference and no floor (e.g. a helper under `tests/`
  nothing imports);
- a reach whose shards are all of them (the shards are then the suite).

Unchanged: `deleted-but-referenced` stays unmapped (a dangling reference is
not narrowed); declared-rule (`changed_tests_map.yaml`) files keep their
mapping.

Note: `scripts/qa/**` being whole-suite only bites when the file is otherwise
unmapped. `run_changed_tests.py` itself maps to its own unit tests, so this
very change is not whole-suite.

## Tests (TDD, tests written first)

- `tests/unit/qa/test_shard_reach.py` (new, 19 tests): loader validation,
  glob semantics, floors, whole-suite triggers, shard targets, and the shipped
  YAML loading against the shipped `test_shards.yaml`.
- `tests/unit/qa/test_run_changed_tests.py`: new `TestShardFallback` (13
  tests: floor only, referrer shards, remainder shard explicit files, handler
  floor, all-shards -> whole suite, triggers, non-Python, root conftest,
  nested conftest subtree, changed test never widened, deleted-but-referenced
  kept, no-shards old behaviour, report and description). One existing test
  (`select_only`) changed: its orphan source now selects the `integration`
  floor; a `Makefile` stands in for the unmapped case.
- `tests/unit/qa/test_llm_qa_changed.py`: two tests for the summary lines.

## Docs

`CLAUDE/QA.md`, the `changed` tier section: the shard rule, floors, the
whole-suite list, and the revised unmapped reasons.

## Targeted QA results

- `ruff check scripts/qa src/claude_code_hooks_daemon/qa tests/unit/qa`: pass.
- `black --check` on the same trees: pass (112 files unchanged).
- `mypy` on `shard_reach.py`, `run_changed_tests.py`, `llm_qa.py`: no issues.
- pytest `tests/unit/qa` + `tests/unit/scripts/test_classify_changes.py`:
  1648 passed, 25 failed. The 25 are all in `test_llm_qa_main_moved.py` and
  `test_llm_qa_venv_resolution.py`; those two files plus `test_llm_qa_changed`,
  `test_run_changed_tests`, `test_shard_reach` and `test_suite_shards` run
  together pass (359 passed), and the failures are order-dependent in the whole
  directory run. I did not run a baseline on main to prove they pre-exist;
  the coordinator should treat that as unverified. The worktree has no venv
  of its own, so tests were run with the main venv and `PYTHONPATH=src` to
  satisfy `source_tree_guard`.
- Full gate (`llm_qa.py all`) not run, per instructions.

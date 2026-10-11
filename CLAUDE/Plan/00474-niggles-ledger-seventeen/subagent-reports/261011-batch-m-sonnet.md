# Batch M: N361 and N360 (Sonnet)

Branch `agent-a96662d45657fac9f-f9ac030c`. Both entries fixed; no owner question needed (owner rulings C6 and C7 are in
`CLAUDE/Plan/Completed/00483-threat-model-conformance-audit/OWNER-RULINGS-261006.md`). The plan folder holds no
`TRIAGE-*.md`; the triage report is `subagent-reports/261011-open-entry-triage-sonnet.md` (group I).

## N361 (fake-values registry)

- Header comment existed but was small: replaced by a large STOP banner (any change must be a clear fake).
- Pre-filled six more kinds in `.claude/fake-values.yaml`, values all contain `fake` or a repeated character, no
  `fake_looking` regex so swap/sweep behaviour is unchanged.
- `FakeValuesRegistry.not_visibly_fake()` plus a registry finding in the `unlisted-fake-value` SWEEP check (ADVISE).
- Red: 10 failed (9 in `test_fake_values.py`, 1 in `test_unlisted_fake_value.py`), then green; 863 passed across unit
  utils, docs_qa, remote_docs and the sensitive-content tests.

## N360 (upgrade keeps opt-in handlers)

- `check-effective-handlers --apply` (passed by `scripts/upgrade.sh`); `apply_restore` edits text, verifies by
  re-parsing, writes only on success; falls back to the snippet with an explanation. First attempt failed on
  `init minimal` (`pre_tool_use: {}` inline); the editor now opens empty inline mappings.
- Red: new test module failed at import (18 tests uncollectable) and the CLI forwarding test failed (KeyError).
- Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/018-…`.
- No guard false-positive work, so no corpus rows.

## QA

ruff, black (py311), mypy on touched sources clean; targeted tests green (the wide run's result is in the reply).
Pre-existing: `tests/unit/install/test_bin_wrapper_project_anchoring.py::...test_a_global_anchor_selects_the_tree_the_command_reads` fails in this
worktree environment (not touched by this batch).

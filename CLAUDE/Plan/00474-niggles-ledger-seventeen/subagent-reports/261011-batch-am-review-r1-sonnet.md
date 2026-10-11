# Review r1: batch AM (N330 spend_limit chip, N361 option A registry block)

Branch `worktree-batch-am-usage-registry`, commits 06217b0f0 and a437d7518, `main...HEAD`. Read only; I read the diff and the consumers but did not run the suites.

Verdict: **CHANGES** (two must-fix).

## Must fix

### 1. The documentation table now lies about the check (confidence 95)

`CLAUDE/core/DocumentationStrategy.core.md:684` and its install template `src/claude_code_hooks_daemon/install/templates/core/DocumentationStrategy.core.md` (the diff touches neither):

`| unlisted-fake-value | R1 | edit, sweep | **Never** - advisory; the registry is the fix |`

The check now runs at `staged` and can BLOCK. The row must read `edit, staged, sweep` and say it blocks a commit that adds or changes a not-visibly-fake registry entry once `check_modes` sets it to `block` (compare the `unenforced-approval-gate` row). Edit the template, then regenerate or copy to `CLAUDE/core/` the way the project does. The implementer's "generated_doc_drift green" only shows the two copies agree, not that either is true.

### 2. The over-100 parse path is not bounded (confidence 80)

`core/usage_snapshot.py` `_parse_window` with `may_exceed_max=True`: the only guards are `isfinite` and `>= 0`. `1e308` is accepted, persisted, and `_chip` does `math.floor(1e308)`, rendering a 309-digit chip in the status line. Add a named cap constant (for example 1000) and reject above it, so garbage degrades silently like other malformed data. Add parametrised tests for `1e308` and just above the cap, for both the live payload and the persisted file. No test currently pins any upper bound; the malformed list covers `inf` but no huge finite value.

## Checked and fine

- spend_limit cannot feed the ceiling or pause. `highest_used_percentage` still iterates only five_hour and seven_day; `usage_pause_gate.py:135-136`, `host_usage_ceiling.py` and the indicator ceiling text name those two fields explicitly. Spend-only gives `None`, already treated as no data. Pinned by `test_spend_limit_does_not_feed_the_subscription_ceiling_figure`.
- Malformed spend is dropped at parse time and keeps the good windows, for payload and file.
- Persist key reordering is harmless (equality only).
- N361 blames only added or changed entries: HEAD's failing (kind, value) pairs are subtracted; unparseable HEAD judges every entry (fails safe); deletion and untouched registry are silent; unparseable staged registry blocks; pathspec commits read `recorded_text`. Tests cover each, and the gate-level block versus advise split.
- EDIT and SWEEP findings stay ADVISE, so the project-wide `check_modes` entry cannot make `docs_qa_edit` deny.
- Config key: `documentation.qa.check_modes` is `dict[str, Literal["warn","block"]]` (`config/models.py:1156`), so the value is validated and `block` is valid; same precedent as `unenforced-approval-gate`.

## Important (file as plan tasks, not blocking)

### A. check_modes keys are not validated against known check ids (confidence 70)

`config/models.py:1156`: a typo like `unlisted-fake-values: block` loads cleanly and enforces nothing. Pre-existing, but this branch adds a security-relevant use. Remediation: validate every key against registered `CheckSpec.check_id`s (validator or doctor check), or at least a unit test that every key in this project's `.claude/hooks-daemon.yaml` is a real id.

### B. Block via project config only: right, but a release note is missing (confidence 75)

Do not change the handler default. Default `commit_gate_mode` is `warn`, and flipping a check to block by default is an owner decision (the added-only blame makes a later flip safe). But other projects with a `.claude/fake-values.yaml` now get a STAGED advisory they did not before and a new opt-in key. Add `CLAUDE/UPGRADES/UNRELEASED/release-notes/019-*.md` covering the `$` spend chip and the registry commit check with its `check_modes: unlisted-fake-value: block` opt-in (plus a `config-changes/` entry if that folder's convention covers an optional key). The branch adds neither.

### C. Heuristic weakness (confidence 60, informational)

`fake` anywhere, or an 8-times repeated character, still passes `not_visibly_fake`. Already accepted in N361; keep the residual visible in NIGGLES.

## Tests

Red-first evidence in the report is specific (named AttributeError, TypeError, ImportError; counts 7 and 5) and plausible; I did not reproduce it. Quality is good: behavioural, covers the non-blame and parse-failure paths, and the old contradictory test was rewritten. Gaps: the upper bound (must-fix 2).

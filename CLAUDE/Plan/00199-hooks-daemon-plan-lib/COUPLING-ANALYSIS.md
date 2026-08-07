# Coupling Analysis — the plan subsystem as it stands

Supporting evidence for Plan 00199. Every structural claim below was verified
against the tree at the commit that created this plan folder. Line references
are `file:line`.

## 1. Inventory — what "the plan subsystem" actually is

The subsystem is not one thing. It is four layers with very different
coupling profiles, and conflating them is what makes it look tangled.

| Layer                | Location                                          | Size                             | Daemon coupling                              |
| -------------------- | ------------------------------------------------- | -------------------------------- | -------------------------------------------- |
| **A. Rule engine**   | `src/claude_code_hooks_daemon/plan_qa/`           | 42 modules, 4,406 LOC, 30 checks | **2 imports** (see §2)                       |
| **B. Hook adapters** | 9 handlers + `recovery_cron_advisor`              | ~2,079 LOC                       | Total — `Handler`/`HookResult` by definition |
| **C. CLI surface**   | `daemon/cli.py:3357-3452`                         | ~96 LOC                          | 2 call sites (see §5)                        |
| **D. Provisioning**  | `install/plan_workflow.py` + `install/templates/` | 388 LOC + 4 assets               | Config model + installer                     |

For scale: layer A is 4,406 of the daemon's 63,765 `src/` LOC — about 7%.

Handler sizes (layer B), for reference:

```
124  handlers/pre_tool_use/plan_workflow.py
238  handlers/pre_tool_use/plan_number_helper.py
197  handlers/pre_tool_use/plan_time_estimates.py
141  handlers/pre_tool_use/plan_completion_advisor.py
259  handlers/pre_tool_use/validate_plan_number.py
229  handlers/pre_tool_use/plan_qa_commit_gate.py
163  handlers/session_start/plan_qa_sweep.py
173  handlers/session_start/plan_workflow_asset_checker.py
555  handlers/post_tool_use/recovery_cron_advisor.py
```

## 2. The rule engine is already decoupled — this is the headline finding

`plan_qa/` imports **nothing** from the daemon except two symbols, both in
one file:

- `plan_qa/gitfacts.py:23` — `from claude_code_hooks_daemon.constants.timeout import Timeout`
- `plan_qa/gitfacts.py:24` — `from claude_code_hooks_daemon.handlers.utils.plan_numbering import read_plan_counter`

Everything else in the package is stdlib only: `re`, `pathlib`, `dataclasses`,
`enum`, `datetime`, `calendar`, `collections`, `typing`, and `subprocess`
(`gitfacts.py:17`, guarded `# nosec B404`).

Notably absent: **no pydantic, no yaml, no `core.Handler`, no `HookResult`,
no `ProjectContext`**. The package does not know the daemon exists.

### 2a. Why that is true by design, not by accident

Config decoupling was solved with structural typing rather than imports.
`plan_qa/context.py:29-107` declares three `Protocol`s — `JournalPolicy`,
`PlanDocSizePolicy`, `QaPolicy` — that mirror the pydantic config models
field-for-field without importing them. The module docstring states the
intent outright (`context.py:3-6`):

> The daemon config model (`PlanWorkflowQaConfig`) is duck-typed here via
> `QaPolicy` so this package keeps zero pydantic/daemon coupling — any object
> carrying the policy field names works.

The package also carries its own policy defaults so it needs no config source
at all (`plan_qa/types.py:38-59`), with the intent recorded at `types.py:43`:

> The daemon config model overrides these via QaPolicy; the package-level
> defaults keep `plan_qa` usable standalone.

### 2b. The two coupling points, assessed

**`Timeout`** (`gitfacts.py:23`) is a trivial constant import — an integer
timeout for the `git` subprocess. Removing it is a one-line change to a
module-level `Final[int]`, or a constructor default.

**`read_plan_counter`** (`gitfacts.py:24`) is the real defect. It is a
**layering inversion**: the rule engine reaches *upward* into the handlers
package. The transitive chain is:

```
plan_qa/gitfacts.py
  -> handlers/utils/plan_numbering.py:126  (read_plan_counter)
    -> utils/git_repo.py                   (GitRepo.read_config)
```

`plan_numbering.py:126-139` is 14 lines that shell out to
`git config --local hooksdaemon.latestPlanNumber` and parse an int. It sits
in `handlers/utils/` for historical reasons only — nothing about it is
handler-specific, and `plan_qa` is arguably its most natural home.

This is worth fixing **regardless of any extraction**, because a library
importing from `handlers/` inverts the dependency direction the rest of the
architecture follows.

## 3. The adapters are genuinely thin

`plan_qa_edit.py` is representative. Its `handle()` (`plan_qa_edit.py:95-124`)
does exactly four things: resolve would-be content, build a context, run the
stage, format the result.

```python
context = edit_context(...)                 # plan_qa_edit.py:107-116
findings = run_stage(Stage.EDIT, context)   # plan_qa_edit.py:117
if blockers and self._plan_qa.edit_mode == _EDIT_MODE_BLOCK:
    return HookResult(decision=Decision.DENY, reason=format_block_reason(blockers))
```

There is **zero rule logic** in the handler. This matches the stated
architecture in `plan_qa/types.py:5-7`:

> Handlers and the CLI never contain rule logic: they build a `CheckContext`,
> call `plan_qa.runner.run_stage`, and render the findings.

The one genuinely daemon-shaped concern in the adapter is
`ProjectContext.project_root()` (`plan_qa_edit.py:108`) — and `edit_context`
already takes `project_root` as a plain `Path` parameter, so even that is
passed in, not reached for.

The `runner` itself is 29 lines (`plan_qa/runner.py`), and the checks are pure
`CheckContext -> list[Finding]` functions — `status_line_present.py:29-41` is a
typical whole check, 13 lines including the `Finding`.

## 4. Config binding is generic, not plan-specific

Handlers receive plan config through the registry's tag-based injection at
`handlers/registry.py:392-414`. Any handler tagged `planning` gets
`_track_plans_in_project`, `_plan_workflow_docs`, `_enforce_claude_code_sync`
and `_plan_qa` set via `setattr`.

This matters two ways:

- The binding mechanism is **not** part of the plan subsystem — it is the
  same generic `setattr` option-injection every handler uses
  (`registry.py:379-380`).
- Consequently the handlers depend on the *shape* of `PlanWorkflowQaConfig`
  (`config/models.py:519-600`), not on plan_qa. The Protocols in
  `context.py` are what keep those two in sync without an import edge.

## 5. The CLI is already a near-standalone entry point

`cmd_plan_qa` (`daemon/cli.py:3357-3452`) touches the daemon exactly twice:

- `Config.load_or_default(...)` (`cli.py:3400`) — to read `plan_workflow`
- `get_project_path(None)` (`cli.py:3399`) — only when `--project-root` is
  absent; an explicit `--project-root` is trusted as-is and bypasses all
  daemon installation validation (`cli.py:3390-3397`, comment included)

Everything after that is plan_qa (`cli.py:3418-3432`) plus rendering
(`format_cli_report`, or `--json` at `cli.py:3437-3448`). It already exits 1
on findings and 2 on operational errors — i.e. **it is already a CI-usable,
pre-commit-usable command**. Anyone wanting "plan QA in CI" can run
`hooks-daemon plan-qa --sweep --project-root X` today.

## 6. Peripheral consumers want only a path predicate

Two non-plan handlers import from `plan_qa`, and both take the same single
pure function:

- `handlers/pre_tool_use/plan_time_estimates.py:16` — `from ...plan_qa.paths import is_journal_file`
- `handlers/post_tool_use/markdown_table_formatter.py:31` — same import

Both use it to exempt journal files from a rule. `paths.py:105-120`
(`is_journal_file`) is deliberately config-independent, documented at
`paths.py:15-19`. This is a healthy dependency shape, not a coupling problem.

## 7. Tests are as decoupled as the package

The 527 tests across `tests/unit/plan_qa/` and the three adapter test files
import only `plan_qa` symbols, plus two incidental daemon imports:
`constants.timeout.Timeout` and `utils.markdown_format.format_markdown_text`
(test-only, for fixture formatting).

No test constructs a pydantic `Config` to exercise a check — they pass
`CheckContext` directly. This means the suite would move with the package
essentially unchanged, which is a strong signal the seam is real.

## 8. Where duplication actually lives

The one genuine DRY violation in the subsystem is **not** in `plan_qa` — it is
between Python and bash.

`CLAUDE/Plan/mkplan.bash` (384 lines, deployed from
`install/templates/mkplan.bash`) reimplements the plan-numbering algorithm in
bash:

- `mkplan.bash:49` — `readonly COUNTER_KEY="hooksdaemon.latestPlanNumber"`
- `mkplan.bash:116` — filesystem high-water scan, "Mirrors the daemon's scan"
- `mkplan.bash:359` — high-water write, "mirrors the daemon's max() semantics"

The Python originals are `handlers/utils/plan_numbering.py:73-112`
(`highest_plan_number`) and `:185-198` (`record_plan_allocation`).

This duplication is **deliberate** and documented at `mkplan.bash:44`: the
script must work when the daemon never sees the write, because `mkplan.bash`
creates folders via shell rather than the Write tool. The script is also
explicitly designed to be droppable into any project (`mkplan.bash:4`).

An extraction that did not also address this would leave the subsystem's only
real duplication untouched — worth stating plainly, because it means
"extract plan_qa" and "de-duplicate the plan subsystem" are different projects.

## 9. Provisioning is installer-shaped, not library-shaped

`install/plan_workflow.py:348-387` (`deploy_plan_workflow_if_enabled`) is the
single deployment decision site, gated on `config.plan_workflow.enabled`. It
seeds four assets with a deliberate ownership contract
(`install/plan_workflow.py:295-345`):

- **daemon-owned, overwritten every upgrade**: `mkplan.bash`,
  `.plan-template-default.md`
- **client-owned, never overwritten**: `_TEMPLATE_.md`,
  `_JOURNAL_TEMPLATE_.md`, `PlanJournalling.md`, `README.md`, `CLAUDE.md`

This layer is the *least* extractable and the least worth extracting: it is
installer plumbing whose whole purpose is to put files into a project that has
the daemon installed. A standalone library would need its own, different
provisioning story.

## 10. Demand evidence

No prior art or stated demand for extraction exists in the repo. A search
across `CLAUDE/Plan/`, `docs/` and `CLAUDE/*.md` for extraction/standalone/
reusable-library intent returns no plan proposing it. The single "standalone"
reference in the subsystem is the design note at `plan_qa/types.py:43`, which
describes the package keeping its defaults usable without daemon config — a
decoupling discipline, not a distribution plan.

`pyproject.toml:28-35` shows the daemon's runtime dependencies
(`pyyaml`, `pydantic`, `jsonschema`, `psutil`, `mdformat`, `mdformat-gfm`).
An extracted `plan_qa` would need **none** of them — further confirming the
package is already independent, and simultaneously confirming that the cost a
consumer avoids by getting a separate package is small: `pip install` of the
daemon pulls six wheels, none of them heavy or exotic.

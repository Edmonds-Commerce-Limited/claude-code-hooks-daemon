# Plan 00395 implementation report — daemon-upgrade-detector

**Agent**: python-developer (Sonnet 5)
**Scope**: implement the `daemon_upgrade_detector` UserPromptSubmit handler per PLAN.md's owner-ruled design, TDD-first, plus the dormancy-exemption generalisation the plan flagged as a known trap.

## Summary of what was built

A new built-in handler, `DaemonUpgradeDetectorHandler`
(`src/claude_code_hooks_daemon/handlers/user_prompt_submit/daemon_upgrade_detector.py`),
registered as `HandlerID.DAEMON_UPGRADE_DETECTOR` / `Priority.DAEMON_UPGRADE_DETECTOR`
(58, next free UserPromptSubmit-advisory slot after `standing_authorisations`).

- On every UserPromptSubmit, re-resolves the current venv via
  `daemon.paths.resolve_existing_venv_python()` (never `sys.prefix`, never a
  path cached at construction), reads `.daemon-metadata.json` via the
  existing `daemon.metadata.read_daemon_metadata()` (no second reader), and
  compares its `daemon_version` (normalised through the existing
  `install.install_stamp.parse_install_stamp()` — reused rather than a third
  regex) against `claude_code_hooks_daemon.version.__version__`.
- Matching → completely silent (`context=[]`). Differing → one ALLOW-only
  advisory naming both versions and `bin/hooks-daemon restart`
  (`utils.cli_command.daemon_cli_command`/`..._for_docs`); the handler never
  restarts, reloads or upgrades anything.
- `is_dormant()` (the `CanBeDormant` protocol from `core/claude_md_injector.py`)
  returns `self.self_install_reader()` (default `ProjectContext.self_install_mode`),
  failing toward **dormant** on `RuntimeError`. `matches()` is `not is_dormant()`. Both `self_install_reader`, `daemon_root_reader` and
  `running_version_reader` are public injectable callables — the same DI
  idiom `ContractStalenessHandler` already uses — so every test substitutes
  a fake rather than touching global state.
- Fail-open everywhere: missing/malformed/empty metadata, no resolvable venv,
  a `ProjectContext` not yet initialised, or a `daemon_version` that fails
  the stamp parser's stricter shape — all collapse to silent ALLOW, never a
  block.

### Why `ProjectContext.self_install_mode()` rather than reading `daemon.self_install_mode` off the parsed `DaemonConfig` directly

The plan's design section names `config/models.py:1576` (the Pydantic field)
as the thing to read. I used `ProjectContext.self_install_mode()` instead,
for a reason worth being explicit about since it's a deviation from the
literal text:

- No existing handler-injection channel carries an arbitrary top-level
  `DaemonConfig` field onto a handler instance — `HandlerRegistry.register_all`
  only special-cases `worktree`, `plan_workflow` and `documentation` this way.
  Adding a fourth would mean touching `register_all`'s signature and its
  `DaemonController.initialise()` call site, which the plan's own design
  section rules out ("No controller change is required").
- `ProjectContext.self_install_mode()` is already the sanctioned in-handler
  read of exactly this fact (`ContractStalenessHandler.self_install_reader`
  is the precedent), and it cannot drift from the config flag in a daemon
  that started successfully: `daemon/validation.py` and
  `install/client_validator.py` both refuse to start unless the declared
  `self_install_mode` and the actual daemon-source-at-project-root layout
  agree.

I'd flag this for a second look rather than assert it's certainly right —
it is a real (small) departure from the letter of the design note, argued
above on the boundary the plan itself drew (no controller/registry wiring
change).

## The dormancy-polarity trap (flagged in the brief) — found and fixed

`tests/integration/test_claude_md_guidance_coverage.py`'s
`_DORMANT_IN_THIS_PROJECT` was `dict[str, str]` (class name → dotted config
key), and `test_every_dormancy_exemption_is_still_true` asserted
`value is not True` — correct for the two existing entries (dormant when
their gate is **off**), wrong for this handler (dormant when
`daemon.self_install_mode` is **on**, which is this repository's actual
state). I generalised the mechanism rather than special-casing it:

```python
@dataclass(frozen=True)
class _DormancyExemption:
    dotted_key: str
    dormant_value: bool

_DORMANT_IN_THIS_PROJECT: dict[str, _DormancyExemption] = {
    "MergeToMainApprovalHandler": _DormancyExemption(
        "worktree.merge_to_main_requires_human_approval", dormant_value=False
    ),
    "PlanCloseApprovalHandler": _DormancyExemption(
        "plan_workflow.close_requires_human_approval", dormant_value=False
    ),
    "DaemonUpgradeDetectorHandler": _DormancyExemption(
        "daemon.self_install_mode", dormant_value=True
    ),
}
```

`test_every_dormancy_exemption_is_still_true` now branches on the recorded
polarity: `value is True` when `dormant_value` is `True`, `value is not True` (tolerating an absent key, which reads as the Pydantic default
`False`) otherwise. I verified this by first running the test unmodified
against the new entry — it failed exactly as the "inverted sense" note
predicted (`None` from the raw-YAML read didn't satisfy `value is False`
either, since `worktree...` isn't even set in this repo's YAML — the fix
needed both the polarity AND the absent-key-reads-as-default nuance, not
just one).

`DaemonUpgradeDetectorHandler` earns a `get_claude_md()` section (added to
`_EARNS_GUIDANCE`, T3: same shape as `daemon_sync_after_merge` — the remedy
happens after the advisory because the handler can't restart the process
serving the hook) and is correctly *absent* from this repo's generated
CLAUDE.md (verified: `grep -n daemon_upgrade_detector CLAUDE.md` returns
nothing after a daemon restart), because this repository is genuinely
self-install.

`test_every_earning_handler_has_a_section_in_claude_md` needed no change —
it already excludes `_DORMANT_IN_THIS_PROJECT` members by key membership,
which survived the value-type change untouched.

## TDD — RED then GREEN

Test file written first at
`tests/unit/handlers/user_prompt_submit/test_daemon_upgrade_detector.py`
(19 tests). `tdd_enforcement` was still live for the source file; confirmed
the RED failure before implementing:

```
ImportError while importing test module '.../test_daemon_upgrade_detector.py'.
E   ModuleNotFoundError: No module named 'claude_code_hooks_daemon.handlers.user_prompt_submit.daemon_upgrade_detector'
```

(also needed `HandlerID.DAEMON_UPGRADE_DETECTOR` / `Priority.DAEMON_UPGRADE_DETECTOR`
added first — those are `Edit`s to existing files, not gated by
`tdd_enforcement`). After implementing: `19 passed`.

Coverage against the brief's minimum list:

- **Version changed in place** (`TestReportsStaleWhenMetadataRewrittenInPlace`):
  same fingerprint-keyed venv dir, `.daemon-metadata.json` rewritten between
  two `handle()` calls on the *same* handler instance.
- **Version changed via a NEW fingerprint-keyed venv**
  (`TestReReResolvesTheVenvEachCall`) — the case the brief calls out as the
  one "a remembered-path check wrongly passes": an OLD, foreign-named venv is
  the only one present for call 1 (found via scan fallback); a NEW venv
  named with the *real* `python_venv_fingerprint(daemon_dir)` is created
  between calls, so call 2's `resolve_existing_venv_python()` step 2 matches
  it directly. No monkeypatching of the fingerprint function was needed —
  the test drives the real function against two genuinely different
  directory layouts, which is a stronger proof than faking the fingerprint
  return value would have been.
- **Versions equal → silent**, **missing/malformed metadata → silent
  allow**, **self-install mode → silent** — each has a dedicated test class.
  Also covered beyond the minimum: empty metadata file, a `daemon_root_reader`
  that raises `RuntimeError` (no project context yet), and the guarded-branch
  `vX.Y.Z+<ref>.<sha>` stamp shape comparing correctly on its numeric part.

## Registration checklist

- `HandlerID.DAEMON_UPGRADE_DETECTOR` — `src/claude_code_hooks_daemon/constants/handlers.py`.
- `Priority.DAEMON_UPGRADE_DETECTOR = 58` — `src/claude_code_hooks_daemon/constants/priority.py`
  (comment on `STANDING_AUTHORISATIONS` reworded since it's no longer the
  last UserPromptSubmit advisory).
- `.claude/hooks-daemon.yaml` and `.claude/hooks-daemon.yaml.example` — both
  gained a `daemon_upgrade_detector` entry under `user_prompt_submit:`
  (`enabled: true`, `priority: 58`); the `.example` addition was required by
  `test_example_config_includes_all_library_handlers`, caught on the first
  full-suite run.
- `get_claude_md()` + `_EARNS_GUIDANCE` entry (above).
- `scripts/qa/error_hiding_exclusions.json` — one new entry for
  `_resolve_installed_daemon_version` (`return-none-on-error`). The static
  `audit_error_hiding.py` AST check flags *any* `except: return None` inside
  a function, with no way to see that it's the same documented fail-open
  contract `daemon/metadata.py::read_daemon_metadata` already carries an
  exclusion for (I quoted that existing entry as precedent in the new one's
  `reason`).
- No `config/models.py` (Pydantic) entry needed — per-handler
  `enabled`/`priority`/`options` are generic (`HandlersConfig.user_prompt_submit: dict[str, Any]`), matching `standing_authorisations` and every other
  handler I checked; only true cross-cutting top-level sections
  (`worktree`, `plan_workflow`, `daemon`) get their own Pydantic model.

## Release-bound consequences

**Not authored by me** — while I was mid-implementation, a concurrent
process (this plan's owner/orchestrating session, presumably; I did not
create these) wrote and then refined:

- `CLAUDE/UPGRADES/UNRELEASED/release-notes/40-a-running-daemon-notices-its-own-upgrade.md`
- `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.64.0.yaml` (new
  `handlers.user_prompt_submit.daemon_upgrade_detector` entry)
- A JOURNAL entry in this plan's `JOURNAL/` explaining why no
  `truth-changes/` entry is warranted (additive capability, nothing
  documented elsewhere becomes false).

I read both artefacts against what I actually built and found them accurate
— except the release-note's `**Audience**: client projects (dormant in a self-install checkout)` line, which fails
`test_pending_release_notes_holding_area.py`'s exact-match regex (`^\*\*Audience\*\*: (operators|handler authors|client projects|everyone)$`). I trimmed it to
`**Audience**: client projects` (the parenthetical is already covered in the
body prose) and reran that test file green. I did not otherwise touch these
two files' content.

## Boundaries respected

- No edits to `DaemonController`, Plan 00371's fingerprint machinery,
  `check-source-fresh`, or `daemon_restart_verifier`.
- No config-drift detection attempted (Plan 00389's territory).
- Did not flip `PLAN.md`'s Task/Success-Criteria checkboxes to done in bulk —
  attempted it, and `plan_qa_edit` correctly denied it
  (`header-body-coherence`: ticking every box while `Status: In Progress`
  reads as a status the header doesn't declare, and moving a plan to
  Complete/archiving it is this project's owner-level, atomic
  status-flip-plus-archive step). Left `PLAN.md` as-is; this report and the
  JOURNAL entry carry the completion record instead.
- Restarted the daemon once (`bin/hooks-daemon restart`) after the code was
  in place, per `daemon_restart_verifier`/self-install dogfooding
  convention — required for the acceptance/smoke-test gates (which dispatch
  against the *live* daemon) to stop reporting `STALE DAEMON` against the
  old process, and to confirm the generated `CLAUDE.md` genuinely omits the
  new handler's section rather than merely asserting it does in a test.
- Did not commit anything.

## QA

Final run of `./scripts/qa/llm_qa.py all`:

```
QA: 29/29 PASSED
```

(exit code 0). Full breakdown of the 29 gates, all ✅, including `tests: 22604 passed, 0 failed, 6 skipped | coverage: 95.3%`, `error_hiding: 0 violations`, `handler_reference: 0 violations`, `smoke_test: 3/3 probes passed`. Two intermediate runs surfaced and were fixed in turn: the first
(before restarting the daemon) failed 3 gates purely on stale-daemon
grounds (`tests`/`smoke_test` dispatching against the pre-restart process)
plus the `error_hiding` static-analysis finding above; the second (after
restart + the exclusion entry) failed only the release-note audience-line
shape, fixed as described above; the third is the clean 29/29 shown here.

## Files touched

- `src/claude_code_hooks_daemon/handlers/user_prompt_submit/daemon_upgrade_detector.py` (new)
- `tests/unit/handlers/user_prompt_submit/test_daemon_upgrade_detector.py` (new)
- `src/claude_code_hooks_daemon/constants/handlers.py`
- `src/claude_code_hooks_daemon/constants/priority.py`
- `.claude/hooks-daemon.yaml`
- `.claude/hooks-daemon.yaml.example`
- `tests/integration/test_claude_md_guidance_coverage.py`
- `scripts/qa/error_hiding_exclusions.json`
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/40-a-running-daemon-notices-its-own-upgrade.md`
  (trimmed the Audience line only; not otherwise authored by me)

Not committed, per instructions.

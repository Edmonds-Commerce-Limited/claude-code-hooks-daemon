# Plan 00330 Phases 2 and 4 — delivery report

Branch: `agent-a2e8b6a7464ee9067-04480368` (worktree). Implementation commit
`bf5da1f5`; plan/journal commit follows it. Not pushed, not merged.

## What was built

### Relevance (Task 2.2, Decision 1)

- `src/claude_code_hooks_daemon/core/relevance.py` — `Relevance`
  (`applicable`, `reason`; `always()`, `when()`), `RelevanceContext`
  (`project_root`, `languages`; `probe()`, `has_file()`,
  `uses_any_language()`), `detect_languages()` from root toolchain markers.
  Pure stdlib so `core/handler.py` imports it without cost.
- `Handler.get_relevance(context) -> Relevance`, concrete, defaults to
  always-relevant. Docstring states the Decision 1 rule and the cheapness
  constraint.
- Overrides: `lsp_enforcement` (env var or `.claude/settings.json` `env`),
  `npm_command` and `global_npm_advisor` (`package.json`),
  `validate_eslint_on_write` (JS/TS toolchain), `goal_injection`,
  `compaction_signal`, `model_fallback_detector`, `tool_disable_advisor`
  (armed supervisor via new `utils.ccy_supervisor.supervisor_relevance`),
  `flaggable_work_advisor`, `flaggable_content_channel_guard`,
  `quarantine_artefact_read_guard` (deployed agent via new
  `handlers/utils/quarantine.py`).
- **No PHP override**: there is no standalone PHP guard in the registry.

### Derivation (Tasks 2.1, 2.3, Decisions 2–3)

- `handlers/registry.py`: `BuiltinHandlerRef` + `iter_builtin_handler_classes()`,
  mirroring `register_all`'s walk exactly.
- `config_optimisation/areas.py`: `Area` (six), `AREA_ORDER`, `area_for(event, tags)`.
- `config_optimisation/checklist.py`: `ChecklistItem` (status property:
  optimal / shortfall / not-applicable), `build_checklist(config, context)`,
  `render_report(items)`, `report_as_json(items)`.
- `daemon/cli.py`: `optimise-checklist [--config PATH] [--format text|json]`
  (global `--project-root` applies). Initialises `ProjectContext` itself.
- `skills/hooks-daemon/scripts/optimise-invoke.sh`: Steps 3–5 rewritten to
  run the verb and print its output verbatim; the `plan_workflow` config
  section and "plans in use" stay as the two non-handler checks; the
  literal `25/25` totals and every hand-written handler name are gone.
  `optimise.md`, `SKILL.md`, `CLAUDE/LLM-INSTALL.md` updated ("six derived
  areas"). Deployed copies under `.claude/skills/hooks-daemon/` refreshed.

### Gate (Tasks 4.1–4.3)

`tests/integration/test_skill_surface_coherence.py`:

1. checklist paths == registry (built-in + pseudo-event); procedure runs
   `optimise-checklist`; procedure names no handler by hand (backticked
   prose mentions exempt).
2. every documented CLI verb (`bin/hooks-daemon X`, `daemon-cli.sh X`,
   passthrough arms, `DAEMON_CLI X` at line start; `echo` lines skipped)
   is a cli.py subparser or alias.
3. no retired handler in code context (backticks or `handlers.<event>.`
   path) on a line that does not say retired/removed.
4. every dotted config key rooted at a `Config` field walks the pydantic
   schema; under `handlers.<event>` the next segment must be a `HandlerID`
   key, `enable_tags`/`disable_tags`, a `<placeholder>` or an example
   (`my_`/`your_`/`example_`/`custom_`).

Each extraction regex has a companion "sees known things" test so a silent
zero-match cannot make the gate vacuous. It runs inside `llm_qa.py all`'s
`tests` check, which is RELEASING.md Step 8 (BLOCKING); Step 8 now says so.

### Docs

`CLAUDE/HANDLER_DEVELOPMENT.md` (new `get_relevance()` section + checklist
rows), `CLAUDE/development/RELEASING.md` (Step 8), release note
`CLAUDE/UPGRADES/UNRELEASED/release-notes/28-optimise-is-registry-derived.md`.

## Measured result for this repository

```
Overall: 110/110 relevant handlers enabled (100%) · 6 not applicable here
```

116 handlers scored (was 22). Not applicable: flaggable trio (no quarantine
agent deployed), both npm handlers (no `package.json`),
`validate_eslint_on_write` (no JS/TS toolchain). `lsp_enforcement` is
relevant here because `ENABLE_LSP_TOOL` is set.

## QA

- `ruff check`, `black` (format authority, applied), `mypy --strict` on all
  touched source and test files: clean.
- `./scripts/qa/llm_qa.py skill_refs handler_reference doc_truth`: 3/3
  (via an uncommitted `untracked/venv -> .venv` symlink).
- `docs-qa --lint` on the three edited agent-tree docs: 0 findings.
- `tests/unit` + `test_skill_surface_coherence.py` +
  `test_deployed_skill_trees.py` + `test_claude_md_guidance_coverage.py`:
  17405 passed, 2 skipped, 1 xfailed.

## Things worth the owner's eye

- **Enabled-state semantics are inherited, not chosen**: an absent
  `handlers.<event>.<name>` block counts as enabled (that is what
  `register_all` does) while an absent `pseudo_events.nitpick` section
  counts as disabled (that is what the dispatcher does). The checklist
  reports what will actually run.
- **Status-line components and the six integrity handlers are scored**
  (Decision 1) and land under "Session, environment & daemon", which is
  therefore the largest area (32 here). Collapsing keeps it to one line.
- The gate's rules were tightened structurally after its first RED run
  (details in the journal); no allowlist of names was added anywhere.
- Phase 3 is untouched.

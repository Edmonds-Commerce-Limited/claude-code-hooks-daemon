# Docs QA architecture map (`/workspace`)

Prepared for: design of a new "remote docs" check family.
All paths absolute-relative to `/workspace`.

## 1. Package layout — `src/claude_code_hooks_daemon/docs_qa/`

| File                            | Role                                                                                                                                                        |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `types.py` (99 ln)              | `CheckStage`, `Severity`, `Finding`, `CheckContext`, `CheckFn`, `CheckSpec`                                                                                 |
| `policy.py` (145 ln)            | Plain-dataclass mirror of the pydantic config + `policy_from_config()`                                                                                      |
| `context.py` (122 ln)           | Three context builders, one per surface                                                                                                                     |
| `corpus.py` (547 ln)            | Corpus discovery, `DocRecord`/`DocCorpus`, JSON cache, scope predicates                                                                                     |
| `runner.py` (29 ln)             | `run_stage(stage, context, registry=None)` — filter-and-accumulate                                                                                          |
| `report.py` (131 ln)            | `format_block_reason` / `format_advisory` / `format_cli_report`                                                                                             |
| `quotes.py` (217 ln)            | `ssot-quote` machinery: `slugify_heading`, `resolve_anchor_span`, `normalise_markdown`, `parse_quote_blocks`, `verify_quote`, `MIN_QUOTE_LENGTH_CHARS = 80` |
| `structured_blocks.py` (194 ln) | `BlockLocation`, `extract_structured_blocks`, `extract_structured_block_hashes`, `extract_structured_block_locations`                                       |
| `comment_finder.py` (97 ln)     | `find_long_comment_blocks`, `DEFAULT_MIN_BLOCK_LINES` — feeds the CLI's `find-comment-blocks`                                                               |
| `checks/`                       | 11 check modules + `__init__.py` registry                                                                                                                   |

### How a check is defined

**A check is a pure function, registered declaratively — no base class, no decorator, no metaclass.**

- `docs_qa/types.py:90` — `CheckFn = Callable[[CheckContext], list[Finding]]`
- `docs_qa/types.py:93-99`:

```python
@dataclass(frozen=True)
class CheckSpec:
    """Declarative registration of one check."""
    check_id: str
    stage: CheckStage
    run: CheckFn
```

Each check module declares a module-level `CHECK_ID: Final[str]` (kebab-case, e.g. `"pointer-resolves"`) and a module-level `CHECKS: Final[tuple[CheckSpec, ...]]`. Example, `docs_qa/checks/source_tree_markdown.py:199-201`:

```python
CHECKS: Final[tuple[CheckSpec, ...]] = (
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.SWEEP, run=_run_sweep),
)
```

Multi-stage example, `docs_qa/checks/pointer_resolves.py:183-187`:

```python
CHECKS: Final[tuple[CheckSpec, CheckSpec, CheckSpec]] = (
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.EDIT, run=_run_edit),
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.STAGED, run=_run_staged),
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.SWEEP, run=_run_sweep),
)
```

### How a new check is registered — exactly two edits

`docs_qa/checks/__init__.py`:

1. Add the module to the import block at `:7-19`.
2. Add `*your_module.CHECKS,` to the tuple returned by `all_checks()` at `:23-37`.

`all_checks() -> tuple[CheckSpec, ...]` is the single registry function; `runner.run_stage` defaults to it. Registration order **is** the finding-accumulation order, which matters for the advisory cap (§2).

### The Finding structure

`docs_qa/types.py:39-47`:

```python
@dataclass(frozen=True)
class Finding:
    """One violated invariant plus its exact remediation."""
    check_id: str
    severity: Severity      # BLOCK | ADVISE
    message: str
    remediation: str
    path: str | None = None
```

`Severity` is a `StrEnum` at `types.py:32-36` with exactly two members: `BLOCK = "block"`, `ADVISE = "advise"`.

**There is no line-number field.** `path` is a repo-relative path string only. Checks that want a line cite it as text inside `path`/`message` — `duplicate-block` emits `path:start-end` using `BlockLocation` (`structured_blocks.py:74-84`, carrying `block_hash`/`start_line`/`end_line`). If the remote-docs family needs structured `file:line`, `Finding` must gain a field, and three consumers need updating: `report.py:36-42` (`_format_finding`), the CLI JSON payload (`daemon/cli.py:4874-4885`), and any test asserting on `Finding` equality.

### CheckContext

`docs_qa/types.py:50-87` — one flat frozen dataclass, stage-specific slots `None` when inapplicable:

- Always: `project_root: Path`, `policy: DocumentationPolicy`
- EDIT: `file_path`, `file_content`, `file_exists_before`, `file_content_before`
- SWEEP (and optionally EDIT): `corpus: DocCorpus | None`
- STAGED: `staged_documents: dict[str, str] | None`, `gitfacts: GitFacts | None`, `commit_message: str | None`
- Any surface that has one: `layout: ProjectLayout | None`

Builders in `docs_qa/context.py`: `edit_context(...)` at `:34-66`, `sweep_context(...)` at `:69-76`, `staged_context(...)` at `:79-122`.

## 2. Invocation at each surface

| Surface         | Entry point                                                                | Stage    | Mode source                                                                    |
| --------------- | -------------------------------------------------------------------------- | -------- | ------------------------------------------------------------------------------ |
| Session sweep   | `handlers/session_start/docs_qa_sweep.py` — `DocsQaSweepHandler`           | `SWEEP`  | `qa.sweep_mode` (`advise`\|`off`), gated in `matches()` at `:80`; never blocks |
| Write/Edit gate | `handlers/pre_tool_use/docs_qa_edit.py` — `DocsQaEditHandler`              | `EDIT`   | `qa.check_modes[id]` → fallback `qa.edit_mode`                                 |
| Commit gate     | `handlers/pre_tool_use/docs_qa_commit_gate.py` — `DocsQaCommitGateHandler` | `STAGED` | `qa.check_modes[id]` → fallback `qa.commit_gate_mode`                          |

### How a check declares its surfaces

Purely by which `CheckSpec`s appear in its `CHECKS` tuple. `runner.run_stage` (`runner.py:26-28`) is the whole dispatch:

```python
for spec in specs:
    if spec.stage == stage:
        findings.extend(spec.run(context))
```

The same `check_id` may appear up to three times with three different `run` functions. There is no declarative "applies to" field beyond `stage`.

### Current stage matrix

| check_id                     | module                          | EDIT | STAGED | SWEEP |
| ---------------------------- | ------------------------------- | ---- | ------ | ----- |
| `pointer-resolves`           | `pointer_resolves.py`           | Y    | Y      | Y     |
| `quote-drift`                | `quote_drift.py`                | Y    | Y      | Y     |
| `generated-doc-hand-edit`    | `generated_doc_hand_edit.py`    | Y    | —      | Y     |
| `rules-file-shape`           | `rules_file_shape.py`           | Y    | —      | Y     |
| `at-import-census`           | `at_import_census.py`           | Y    | —      | Y     |
| `module-doc-budget`          | `module_doc_budget.py`          | Y    | —      | Y     |
| `duplicate-block`            | `duplicate_block.py`            | Y    | —      | Y     |
| `quote-source-stale`         | `quote_source_stale.py`         | Y    | —      | —     |
| `plan-promotion-disposition` | `plan_promotion_disposition.py` | —    | Y      | —     |
| `rules-file-orphan-shrink`   | `rules_file_orphan_shrink.py`   | —    | Y      | —     |
| `source-tree-markdown`       | `source_tree_markdown.py`       | —    | —      | Y     |

### The two-key deny rule (critical for a new family)

Mode alone can never escalate a finding. `docs_qa_edit.py:201-208`:

```python
def _is_deny_eligible(self, finding: Finding) -> bool:
    """BLOCK severity AND the resolved mode for this check id is block."""
    if finding.severity != Severity.BLOCK:
        return False
    policy = self._documentation
    assert policy is not None
    resolved_mode = policy.qa.check_modes.get(finding.check_id, policy.qa.edit_mode)
    return resolved_mode == _MODE_BLOCK
```

The commit gate does the same inline at `docs_qa_commit_gate.py:127-133`. So **severity is the check's structural judgement** ("did this edit make it *worse*?") and **mode is the project's rollout dial**. Anything not deny-eligible is returned as `GatingResult(decision=Decision.ALLOW, context=[format_advisory(findings)])`.

The prevailing severity convention across existing checks: BLOCK only when the change is *worse-only* (a violation NEW in this edit, or a metric that GREW); unchanged-but-violating is ADVISE; shrinking is silent; SWEEP has no before/after so it is always ADVISE. See `pointer_resolves.py:133-135` and `rules_file_shape.py:15-28` for the canonical statements.

### Surface-specific plumbing

**Sweep** (`docs_qa_sweep.py`):

- `workspace_scope = WorkspaceScope.REPO` (`:55`); skips resumed sessions via `is_resume_session` (`:75`).
- Builds the corpus: `build_and_save_corpus(project_root, policy, index_path)` at `:89` — this is the **only** handler that walks the filesystem (the "cold-index rule", `corpus.py:16-22`).
- Index path: `ProjectContext.daemon_untracked_dir() / "docs-qa" / "index.json"` (`:88`).
- Passes `layout=self._project_layout` (injected onto every handler instance, Plan 00288).
- Injects one capped advisory: `report.py:28` — `MAX_ADVISORY_FINDINGS_SHOWN: Final[int] = 8`. `_select_capped_findings` (`report.py:52-92`) does two-phase selection so every distinct `check_id` gets at least one slot before the remainder fills — a naive `[:8]` slice starved later-registered checks. Overflow appends `...and N more finding(s) — run docs-qa --sweep`.

**Edit handler** (`docs_qa_edit.py`):

- `matches()` at `:119-134`: tool ∈ {Write, Edit}, `policy.enabled`, and `is_lintable_path(rel, path, root, policy)`.
- Hot-path cheap: `load_or_cold_corpus` (one JSON read, never a build) then **`refresh_own_record(corpus, root, file_path, content)`** at `:157`. That call is **mandatory** for any cross-document check — `corpus.py:455-477` documents why: the cache read performs no staleness check, so without it the edited file's own record lags the would-be content and `duplicate_block`'s `len(paths) >= 2` test never sees the newly-introduced block.
- Reconstructs would-be content for `Edit` at `:217-238` (applies `old_string`→`new_string`, honouring `replace_all`); returns `None` (skip) when the tool call would itself fail.
- **Does not yet cover Bash-authored `.md` writes** — explicitly deferred, `:35-37`.

**Commit gate** (`docs_qa_commit_gate.py`):

- `matches()` at `:97-104`: Bash tool + `is_git_commit(tokenise(command))` from `utils/git_commit_parsing`.
- Early-exits for foreign repos: `_is_foreign_repo` at `:163-170` via `GitRepo.resolve_for(cwd)`.
- Extracts message + pathspecs from the actual command line at `:114-121`.
- `staged_context` (`context.py:79-122`) builds `staged_documents: dict[rel_path, str]` for non-deleted `.md` only, using `plan_qa.gitfacts.GitFacts` — reused directly, not reimplemented. With pathspecs it reads the **working tree**, without them `gitfacts.staged_file_text` (the index) — see the comment at `context.py:103-106` for why.

### Handler registration constants

- `constants/handlers.py:651-655` (`DOCS_QA_SWEEP`), `:694-698` (`DOCS_QA_EDIT`), `:702-706` (`DOCS_QA_COMMIT_GATE`) — each a `HandlerIDMeta(class_name, config_key, display_name)`.
- `constants/priority.py:204` `DOCS_QA_EDIT = 47`, `:208` `DOCS_QA_COMMIT_GATE = 47` (same slot, mirroring plan_qa), `:242` `DOCS_QA_SWEEP = 64`.
- `constants/rule_ids.py:146` `DOCS_QA_EDIT = "R-DOCS-QA-EDIT"`, `:149` `DOCS_QA_COMMIT = "R-DOCS-QA-COMMIT"`.
- `constants/tags.py:99` `DOCUMENTATION = "documentation"`.

**Policy injection**: a handler tagged `HandlerTag.DOCUMENTATION` receives `self._documentation: DocumentationPolicy | None` from the registry — `handlers/registry.py:450-459`, which calls `policy_from_config(documentation)`. Handlers declare the attribute in `__init__` (e.g. `docs_qa_edit.py:109`) and gate on `policy is None or not policy.enabled` in `matches()`.

`init_config.py` defaults: `:224` `docs_qa_edit: {enabled: true, priority: 47}`, `:225` `docs_qa_commit_gate: {enabled: true, priority: 47}`, `:278` `docs_qa_sweep: {enabled: true, priority: 64}` — all annotated "fires only when documentation.enabled".

## 3. Configuration

Pydantic models (all `extra="forbid"`, so a new key **must** be added to the model):

- `config/models.py:857-870` — `DocumentationGeneratedDocEntry` (`glob`, `generator`)
- `config/models.py:873-892` — `_default_generated_docs()` (pre-seeds `.claude/HOOKS-DAEMON.md`)
- `config/models.py:895-959` — `DocumentationQaConfig`
- `config/models.py:962-984` — `DocumentationConfig`

YAML shape:

```yaml
documentation:
  enabled: true            # gates HANDLERS only; the CLI runs regardless
  trees:
    agent: CLAUDE
    human: docs
  qa:
    edit_mode: warn        # Literal["warn","block"], default warn
    commit_gate_mode: warn # Literal["warn","block"], default warn
    sweep_mode: advise     # Literal["advise","off"], default advise
    check_modes: {}        # dict[str, Literal["warn","block"]] keyed by check id
    grandfather_allowlist: []   # globs — capped at ADVISE forever, still indexed
    scope_exclude_globs: []     # globs — removed from the corpus ENTIRELY
    generated_docs:             # list of {glob, generator}
      - {glob: ".claude/HOOKS-DAEMON.md", generator: "bin/hooks-daemon generate-docs"}
    registered_module_docs: []  # sub-CLAUDE.md files that ARE a canonical home
    resident_at_imports: ["CLAUDE.md"]
```

Live values for this repo: `.claude/hooks-daemon.yaml:1008-1097`. Notable real entries: `scope_exclude_globs` holds `CLAUDE/UPGRADES/v[0-9]*/**`, `PLAN-v[0-9]*.md`, `*archived*.md`, `src/claude_code_hooks_daemon/{skills,guides,install/templates}/**`; `generated_docs` holds 13 entries; `registered_module_docs` holds `.claude/ccy/CLAUDE.md`.

**Adding a config knob is a 3-place mechanical change**: `config/models.py` (`DocumentationQaConfig` field) → `docs_qa/policy.py` (`DocumentationQaPolicy` field at `:37-49`, `QaConfigProtocol` property at `:81-109`, and the copy in `policy_from_config` at `:125-145`). The Protocol-based structural typing keeps `docs_qa` pydantic-decoupled — a test stand-in satisfies it without importing the daemon config.

### Is path-delineated check subsetting ALREADY possible?

**Partially — and never per-check.** Three orthogonal mechanisms exist; none crosses the check × path axes:

1. **`check_modes`** — per-check, but **global across paths**. Block vs warn only; it cannot *disable* a check (the `Literal["warn","block"]` type has no `"off"`).
2. **`grandfather_allowlist`** — per-path, but **global across checks**, and applied *by hand inside each check*. `_matches_allowlist` is copy-pasted in six modules: `pointer_resolves.py:96`, `quote_drift.py:139/188`, `at_import_census.py:88`, `module_doc_budget.py:229`, `duplicate_block.py:119/151`, `source_tree_markdown.py:129`. Semantics vary: most checks *downgrade* BLOCK→ADVISE; the two always-advisory checks (`duplicate-block`, `source-tree-markdown`) *suppress entirely*, since there is no severity left to downgrade.
3. **`scope_exclude_globs`** — per-path, global across checks, applied centrally in `corpus.py:186-210` (`_is_excluded`) so corpus-driven checks never see the file at all. The shared predicate `matches_scope_exclude` (`corpus.py:163-183`) is public because `source_tree_markdown` applies it to paths **outside** the corpus scope. It matches against both the full rel-path (for `dir/**` patterns) and the bare basename (for filename-shape patterns like `PLAN-v[0-9]*.md`) — a slash-less fnmatch pattern would otherwise never match a nested file.

**There is no per-check `exclude_paths`/`include_paths`.** I grepped the whole `docs_qa/` package plus all three handlers: zero hits. This is a deliberate contrast with ordinary handlers (`error_hiding_blocker`, `qa_suppression`, `security_antipattern` all take `options.exclude_paths`) — the docs_qa handlers have **zero per-handler options** by design; all policy flows through the shared `documentation:` block so the surfaces cannot fragment.

**The one genuine path-scoped check today is `source-tree-markdown`**, and it scopes via the `ProjectLayout` facade rather than config globs:

- `source_tree_markdown.py:176-178` — silent when `layout is None` or both `source_dirs`/`test_dirs` resolve empty.
- `:185` — `if not (layout.is_source_path(rel_path) or layout.is_test_path(rel_path)): continue`
- Facade: `core/project_layout.py`, class `ProjectLayout` at `:145`, predicates `is_source_path`/`is_test_path`/`is_vendored_path`/`is_docs_path`/`is_plan_path` at `:180-199`, constructors `built_in_default()` `:201`, `for_project()` `:222`, `from_config(config)` `:252`. Fields: `source_dirs`, `test_dirs`, `config_dirs`, `vendor_dirs`, `agent_docs_dir`, `human_docs_dir`, `plan_dir`, `plan_archive_dirs`. Built from the `layout:` config block (`config/models.py:987+`), additive onto built-ins unless `mode: replace`.
- Documented asymmetry (`source_tree_markdown.py:26-35`): `test_dirs` has cross-language built-ins, `source_dirs` has none until declared — so TEST-dir findings can fire in a zero-config project while SOURCE-dir findings stay dormant.

**Conclusion for the remote-docs family**: to path-scope it you either (a) add a new field to `DocumentationQaConfig` + `DocumentationQaPolicy` + `policy_from_config` (mechanical, 3 places), or (b) piggyback on `ProjectLayout` as `source-tree-markdown` does. There is currently **no** generic mechanism to hang a glob off an individual `CheckSpec`, and adding one would be a genuinely new capability.

## 4. Corpus discovery and frontmatter

### What counts as "documentation"

`iter_corpus_paths` (`corpus.py:275-289`) collects:

- root-level `*.md` (glob, files only)
- `rglob("*.md")` under `policy.trees.agent` and `policy.trees.human`
- `rglob("*.md")` under `.claude/{rules,skills,agents}` (`_SATELLITE_DIR_NAMES`, `corpus.py:49`)

then filters through `is_in_scope` (`corpus.py:213-238`), which re-applies the exclusions and the tree membership test.

**Exclusions** — `_is_excluded` (`corpus.py:186-210`), in order: root `CHANGELOG.md`; anything under `RELEASES/`; transient agent-worktree roots (`.claude/worktrees`, `untracked/worktrees`, via `_is_worktree_path` `:136-147`); the vendored daemon install dir (`is_vendored_daemon_install_path` `:150-160`, public for reuse); any path segment in `COMMON_VENDORED_BUILD_DIR_NAMES` (`:103`, a straight re-export of `constants/layout.CORE_VENDORED_BUILD_DIR_NAMES`); `{agent}/Plan/Completed` and `{agent}/Plan/Cancelled`; and `scope_exclude_globs`.

**Three scopes, deliberately different widths:**

- `is_in_scope(path, root, policy)` — `corpus.py:213-238`. The tracked corpus.
- `is_module_doc_path(rel_path, agent_tree)` — `corpus.py:106-121`. Any `CLAUDE.md` that is NOT a canonical root (repo root or `{agent}/CLAUDE.md`). Deliberately wider than the corpus; `src/CLAUDE.md` and `.claude/ccy/CLAUDE.md` qualify.
- `is_lintable_path(rel_path, path, root, policy)` — `corpus.py:241-272`. The SSoT union used by BOTH the EDIT handler and `docs-qa --lint`: `is_in_scope` ∪ generated-docs manifest ∪ `is_module_doc_path`. Its docstring records the drift bug that motivated centralising it (the CLI's independently-derived copy omitted the module-doc arm, so `.claude/ccy/CLAUDE.md` linted fine via the handler but was refused by the CLI).

**Two checks bypass the corpus entirely** and do their own pruned `os.walk`, because their targets sit outside corpus scope: `module_doc_budget` and `source_tree_markdown` (`_iter_markdown_paths`, `source_tree_markdown.py:133-153`). Both re-apply the corpus exclusion *primitives* (shared, not re-derived) — `_EXCLUDED_DIR_NAMES` at `:95-98`. `os.walk` with in-place `dirnames[:]` pruning, not `Path.rglob`, so a huge vendored tree is never physically descended.

### The index cache

- Path: `untracked/docs-qa/index.json` (resolved via `ProjectContext.daemon_untracked_dir()`).
- `DocRecord` (`corpus.py:303-320`): `rel_path`, `mtime_ns`, `size`, `links`, `quotes: tuple[QuoteRef,...]`, `block_hashes`, `block_locations`.
- `DocCorpus` (`corpus.py:323-359`): `project_root`, `documents: dict[str, DocRecord]`, `cold: bool`; methods `document_paths()`, `quoters_of(source_path, anchor)` (the reverse quote index, linear scan).
- Load/build API: `load_cached_corpus` `:362`, `load_or_cold_corpus` `:412` (cheap consumers), `_save_corpus` `:424` (atomic tmp + `Path.replace`, same directory), `refresh_own_record` `:455`, `build_and_save_corpus` `:497` (mtime+size reuse per file).
- **`_CACHE_SCHEMA_VERSION: Final[int] = 2`** at `corpus.py:66`. **Bump it if you add a `DocRecord` field.** The comment at `:57-66` records the exact bug: without a version gate, a warm cache reuses records with the new field empty, and every dependent check silently reports clean.

### Frontmatter

**Parsed nowhere in `docs_qa`. Stripped in exactly one place, and no key is ever read.**

- `docs_qa/checks/rules_file_shape.py:67` — `_FRONTMATTER_RE: Final = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n?", re.DOTALL)`, applied by `_strip_frontmatter` at `:83-85` so frontmatter never counts toward the 15-line body budget (`RULES_FILE_BODY_LINE_BUDGET = 15`, `:61`).

Elsewhere in the repo (not docs_qa): `utils/markdown_format.py:51` `_split_frontmatter` (preserves frontmatter around an mdformat pass), and `install/directory_role_rules.py:388` `_render_frontmatter` (*writes* `paths:` glob frontmatter into deployed `.claude/rules/` files).

**Implication**: `DocRecord` stores no frontmatter. If remote-docs checks key on frontmatter metadata (a `source:` URL, a `fetched:` date, an `upstream:` ref), that requires a new `DocRecord` field, a `_CACHE_SCHEMA_VERSION` bump, a new parser (reusable regex above, but you'll want a real YAML parse for key access), and extraction wiring in both `build_and_save_corpus` (`:531-543`) and `refresh_own_record` (`:479-491`) — those two build `DocRecord` independently and must stay in sync.

## 5. CLI surface

`bin/hooks-daemon docs-qa` → `cmd_docs_qa` at `daemon/cli.py:4756-4889`; argparse wiring at `daemon/cli.py:6266-6303`.

**Flags**: `--sweep` (default action), `--lint FILE`, `--check-staged`, `--json`, `--project-root PATH`.

**Exit codes**: `0` clean, `1` findings reported (CI-able), `2` operational error (missing or out-of-scope lint target).

Runs **regardless of `documentation.enabled`** — an explicit CLI invocation is consent; `enabled` only gates the handlers (`:4771-4772`).

- `--sweep` (`:4863-4872`): `build_and_save_corpus`, `ProjectLayout.from_config(config)`, `sweep_context`, `run_stage(SWEEP)`. `clean_scope = CLEAN_SCOPE_CORPUS`.
- `--lint` (`:4811-4862`): resolves the path **before** scope-checking (Plan 00230 lesson — a relative path must classify identically to its absolute form); gates on `is_lintable_path` with a deny message naming every accepted location; cold-loads the corpus + `refresh_own_record`; and passes `file_content_before=lint_content` (`:4858`) so worse-only checks don't report every pre-existing violation as newly introduced. `clean_scope` names the single file.
- `--check-staged` (`:4807-4810`): `staged_context(project_root, policy)` with no pathspecs, `run_stage(STAGED)`. No pathspec support — the CLI has no `git commit` command line to derive them from.
- `--json` (`:4874-4885`): emits a list of `{check_id, severity, message, remediation, path}`.

**Stale help text worth fixing**: `daemon/cli.py:6281` still says `--check-staged` is *"Not implemented in this slice (Plan 00284 Task 3.1a); exits 2"*, and the section comment at `:6266-6267` says the same — but `cmd_docs_qa` implements it fully at `:4807-4810`. Cosmetic, but it will mislead anyone extending the CLI.

**Related command**: `bin/hooks-daemon find-comment-blocks PATHS [--min-lines N] [--json]` → `cmd_find_comment_blocks` (`daemon/cli.py:4892-4931`), backed by `docs_qa/comment_finder.py`. Deterministic finder feeding the `hooks-daemon-docs-qa` agent's worklist; lists candidates only, never judges.

### Where the rule IDs and explain text live

- IDs: `constants/rule_ids.py:146` (`R-DOCS-QA-EDIT`), `:149` (`R-DOCS-QA-COMMIT`).
- The explain **text is not in a table** — it is the `Rule(...)` object constructed in each handler's `__init__`:
  - `docs_qa_edit.py:110-116`, fed by `_RULE_WHY`/`_RULE_FIX`/`_RULE_VERBOSE` at `:69-80`
  - `docs_qa_commit_gate.py:88-94`, fed by `:55-66`
  - exposed via `get_rules() -> list[Rule]` (`docs_qa_edit.py:179-181`, `docs_qa_commit_gate.py:141-143`)
- `rule_explain/lookup.py` — `collect_handler_rules` (`:67`), `find_rule`, `find_handler`, `near_rule_matches`; instantiates every discoverable handler and harvests `get_rules()` + `get_claude_md()` into `HandlerRules` (`:40-57`). Matching is tolerant (case-insensitive, `R-` prefix optional). This is what `explain-rule` / `explain-handler` and the auto-generated CLAUDE.md rules table read.
- **Granularity is one Rule per GATE, not per check** — stated explicitly at `docs_qa_edit.py:64-68` and `docs_qa_commit_gate.py:50-54`. Per-check text lives in each `Finding.remediation` and in the handler's `get_claude_md()` prose (`docs_qa_edit.py:240-299`, `docs_qa_sweep.py:103-156`, `docs_qa_commit_gate.py:172-204`). Deny messages use the verbose-first/terse-after disclosure ladder (`_blocking_message`, `docs_qa_edit.py:183-199`) with the dynamic findings ALWAYS fully present.

**Consequence for a new family**: it gets no new rule ID unless it gets a new handler. If the remote-docs checks fold into the existing three handlers, you extend `get_claude_md()` prose and rely on per-finding remediation. If they warrant their own surface (e.g. a network-fetching sweep that must not run in a PreToolUse budget), that is a new `HandlerIDMeta` + `Priority` + `RuleID` + `Rule`.

## 6. `plan_qa` vs `docs_qa` as a structural template

They are deliberate mirrors — `docs_qa/types.py:7` and `docs_qa/runner.py:3` say so, and `run_stage` is byte-equivalent between them.

|                      | `plan_qa`                                                                                                                                                                                                                               | `docs_qa`                                                |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| Stage enum           | `Stage` (`EDIT`/`COMMIT`/`SWEEP`), `types.py:24-29`                                                                                                                                                                                     | `CheckStage` (`EDIT`/`STAGED`/`SWEEP`), `types.py:24-29` |
| Severity             | `Finding.level: Level`                                                                                                                                                                                                                  | `Finding.severity: Severity`                             |
| `CheckSpec` fields   | `check_id, stage, level, sins, run` (`types.py:176-189`)                                                                                                                                                                                | `check_id, stage, run` (`types.py:93-99`)                |
| Policy               | ~15 flat knobs **on `CheckContext` itself** (`types.py:117-165`)                                                                                                                                                                        | separate `DocumentationPolicy` on `context.policy`       |
| Path classification  | dedicated `plan_qa/paths.py` — `PlanFileKind` enum (`:43`), `PlanFile` (`:66`), `classify(path, context) -> PlanFile` (`:151`)                                                                                                          | ad-hoc predicates scattered across `corpus.py`           |
| Registration helper  | `document_rule_checks(...)` (`checks/common.py:195-230`)                                                                                                                                                                                | none                                                     |
| Shared check helpers | `checks/common.py` (417 ln): `DocumentTarget`, `edit_target`, `tree_targets`, `level_for_plan`, journal helpers, staged helpers                                                                                                         | none — each check is standalone                          |
| Coverage guard       | `WRITE_ACT_ONLY_RULES` (`common.py:139-168`) + `_modules_registered_for` (`:181-192`) derive attribution from the registry itself; `tests/unit/plan_qa/checks/test_document_rule_stage_parity.py` fails on an unexplained missing stage | none                                                     |
| Check count          | 34 modules                                                                                                                                                                                                                              | 11 modules                                               |

### Verdict: `plan_qa` is the better structural template for a path-scoped family

Three concrete reasons:

1. **`plan_qa/paths.py` is exactly the "classify a path into a kind, then dispatch" primitive a path-delineated family needs.** `docs_qa` has nothing equivalent — its scope logic is a scatter of `is_in_scope` / `is_module_doc_path` / `is_lintable_path` / `matches_scope_exclude` / six copies of `_matches_allowlist`. That scatter has already caused one real drift bug, recorded in `is_lintable_path`'s own docstring (`corpus.py:246-253`).

2. **`document_rule_checks` (`plan_qa/checks/common.py:195-230`) is the family-level registration adapter.** You write ONE rule function against a single `DocumentTarget`; the adapter feeds it the edit payload on one surface and every tree document on the other, returning a `DocumentRuleChecks` NamedTuple whose `.edit`/`.sweep` still splat into the registry. It rewrites `run.__module__` to the rule's own module (`:220-221`) so the registry can attribute the closures back. `docs_qa` would have you hand-write N×stages near-identical functions — which is visibly what has happened (`_run_edit`/`_run_staged`/`_run_sweep` triplicated across 11 modules).

3. **The `sins` field plus the parity guard give a family a machine-checkable "every check is registered where it should be".** `WRITE_ACT_ONLY_RULES` is a dict of *documented exceptions with reasons*, and `_modules_registered_for` reads the live registry rather than a hand-maintained list, "so a new check is classified the moment it is registered — a list would need remembering, which is the failure this guard exists to prevent" (`common.py:184-187`).

**But** the remote-docs family is about *documents*, so it needs `DocCorpus`, `ProjectLayout`, `is_in_scope`, the quote/block machinery, the index cache, and the `documentation:` config block — all of which live in `docs_qa` and none of which `plan_qa` has.

**Recommended path**: build inside `docs_qa`, but port `plan_qa`'s two missing primitives first —

- a `docs_qa/paths.py` classifier (folding in the six duplicated `_matches_allowlist` copies and giving path-scoping ONE home), and
- a `document_rule_checks`-style registration adapter in a new `docs_qa/checks/common.py`.

Doing (a) is also the cheapest way to add per-check path scoping: one place to thread a per-check glob, rather than six.

## 7. Test conventions

**Locations** (mirror the source tree exactly):

- Check tests: `tests/unit/docs_qa/checks/test_<module>.py` — one per check module, 11 files.
- Core tests: `tests/unit/docs_qa/test_{types,context,corpus,policy,quotes,report,runner,structured_blocks,comment_finder}.py`.
- Handler tests: `tests/unit/handlers/pre_tool_use/test_docs_qa_edit.py`, `tests/unit/handlers/pre_tool_use/test_docs_qa_commit_gate.py`, `tests/unit/handlers/session_start/test_docs_qa_sweep.py`.
- CLI tests: `tests/unit/daemon/test_cli_docs_qa.py`.
- No `docs_qa`-local `conftest.py`. Repo conftests: `tests/conftest.py`, `tests/acceptance/conftest.py`, `tests/integration/conftest.py`, `tests/integration/handlers/conftest.py`, `tests/unit/supervise/conftest.py`.

**Shape of a typical check test** (canonical examples: `tests/unit/docs_qa/checks/test_source_tree_markdown.py:1-79`, `tests/unit/docs_qa/checks/test_pointer_resolves.py:1-60`):

1. One-line module docstring naming the check id and the plan/task that introduced it — e.g. ``` """Tests for check ``source-tree-markdown`` (Plan 00288, Task 5.1).""" ```
2. Private `_run_<stage>(context) -> list[Finding]` helpers that pull the matching spec out of the module's `CHECKS` and `raise AssertionError("no SWEEP check registered")` if absent:

```python
def _run_sweep(context: CheckContext) -> list[Finding]:
    for spec in CHECKS:
        if spec.stage is CheckStage.SWEEP:
            return spec.run(context)
    raise AssertionError("no SWEEP check registered")
```

3. A `_context(...)` builder that calls the **real** `edit_context`/`sweep_context`/`staged_context` — never a hand-rolled `CheckContext` — with `DocumentationPolicy()` / `DocumentationQaPolicy(...)` fixtures and, where relevant, a hand-built `ProjectLayout(...)` (see `test_source_tree_markdown.py:16-38` for the full-field constructor).
4. **`class TestRegistration` first**, asserting the stage set and check-id consistency:

```python
def test_registers_sweep_only(self) -> None:
    stages = {spec.stage for spec in CHECKS}
    assert stages == {CheckStage.SWEEP}
    assert all(spec.check_id == CHECK_ID for spec in CHECKS)
```

5. Then one `class Test<Behaviour>` per scenario group, all using the `tmp_path` fixture and writing **real files** (no filesystem mocking).
6. Tests needing git shell out through helpers (`test_pointer_resolves.py:35-48`): `subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True, timeout=Timeout.GIT_CONTEXT)` plus an `_init_repo` that runs `git init` and sets `user.email`/`user.name`.
7. Registry-override testing uses the fake-spec pattern from `tests/unit/docs_qa/test_runner.py:11-15` — build `CheckSpec`s wrapping a closure that returns a canned finding, and pass them as `run_stage(..., registry=...)`.

**Note**: `tdd_enforcement` is active in this repo, so the test file must exist on disk before the check source file — write `tests/unit/docs_qa/checks/test_<new_check>.py` first.

## Reference documents

- `CLAUDE/DocumentationStrategy.md` — the ruleset being enforced (R4b, R6, R7a, R7d, R10, R12, R13 are cited throughout the check docstrings).
- `CLAUDE/Plan/00284-documentation-ssot-enforcement/DESIGN-enforcement.md` — the architecture this package implements (§2.1 cold-index rule, §2.2 block eligibility, §2.4 ssot-quote).
- `CLAUDE/Plan/00284-documentation-ssot-enforcement/RULESET-sub-claude-md.md` — §3 is the source of the 15-line rules-file budget.
- Plans 00287 (F1/F3 fixes), 00288 (`ProjectLayout` facade, `source-tree-markdown`), 00289 (`scope_exclude_globs`) are the most recent extensions and are the best worked examples of adding to this subsystem.
- `.claude/skills/docs-qa/SKILL.md` — the semantic (LLM-judged) half; `hooks-daemon-docs-qa` agent is its executor.

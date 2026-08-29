# Design — project-layout config SSoT (Plan 00288)

Design analysis for a single top-level configuration surface recording which
directory is what (source, test, human docs, agent docs, plans, vendor/build),
consumed by every handler that needs the answer. This is Core Standard 10
("config is truth, code reads config, never hardcode") and
[DocumentationStrategy.md](../../../DocumentationStrategy.md) R5 (derived facts
stated only by their source) applied to CONFIG rather than prose — a follow-on
in the Plan 00284 documentation-SSoT programme.

Owner direction, in substance: a top-level config block tracks project truths
(which dir is what); handler options configure handler BEHAVIOUR only; roll
into the docs-SSoT programme; then enforce the SSoT pattern for markdown under
source/test dirs, with collocated `CLAUDE.md` files allowed as directly
relevant module docs.

---

## 1. Inventory — where directory truths live today

Full citations gathered 2026-08-29 against the current tree. Two distinct
defect shapes emerged, and they need different fixes:

- **Shape A — truth has a config home, consumers ignore it.** Fix = consumption
  refactor, no schema change.
- **Shape B — truth has NO config home; N hardcoded copies.** Fix = new schema
  member (or one shared constant, where per-project variation is implausible).

### 1a. Truths WITH a config home (Shape A)

| Truth                       | Config home                                                                              | Consumers that READ it                                                                      | Consumers that HARDCODE it instead                                                                                                                                                                    |
| --------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Agent/human doc tree names  | `documentation.trees.agent/human` (`config/models.py:776-777`, defaults `CLAUDE`/`docs`) | `docs_qa` corpus + checks (via `docs_qa/policy.py:16-17`, a deliberate plain-values mirror) | `markdown_organization.py:901,937` (allowed-location branches), `:153` (`normalize_path` marker list); `british_english.py:35` (`CHECK_DIRECTORIES = ["private_html", "docs", "CLAUDE"]`)             |
| Plan directory              | `plan_workflow.directory` (`config/models.py:738-741`, default `CLAUDE/Plan`)            | `markdown_organization` (`_track_plans_in_project`, :117), plan_qa paths, installer         | `goal_injection.py:138,143`, `recovery_cron_advisor.py:67`, `plan_workflow.py:46`, `plan_number_helper.py:479` — all regex/prefix-hardcode `CLAUDE/Plan/`                                             |
| Plan archive dir names      | `plan_workflow.qa.completed_dir/cancelled_dir` (`config/models.py:555-562`)              | `plan_qa/paths.py:120-127`                                                                  | `docs_qa/corpus.py:179-184` (`_PLAN_COMPLETED_DIR_NAME` etc.); `markdown_organization.py:32` (`("completed", "cancelled", "archive")` — the only place that knows `archive`); `constants/paths.py:54` |
| Vendored daemon install dir | `ProjectPath.HOOKS_DAEMON_INSTALL_DIR` (`constants/paths.py:94`)                         | `docs_qa/corpus.py:82` (aliased — clean)                                                    | — (single derivation; fine)                                                                                                                                                                           |

**The doc-tree row is a live conflict of intent, not just duplication**: a
client configuring `trees.human: documentation` gets docs_qa treating
`documentation/` as the human tree while `markdown_organization` BLOCKS
markdown written there. The two handlers contradict each other today.

### 1b. Truths WITHOUT a config home (Shape B)

| Truth                                               | Declarations (values differ where noted)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Test directory names                                | `strategies/tdd/common.py:4-9` (`/tests/`, `/test/`, `/__tests__/`, `/spec/`); `tdd_enforcement.py:33-34,42` (`tests`, `unit`, `__tests__`); `constants/paths.py:75-77` (`tests`, `tests/unit`, `tests/integration` — **dead code**, nothing imports these members). Different granularity per copy.                                                                                                                                                                                                                                                                                                                          |
| Source directory names                              | `tdd_enforcement.py:35` (`src`); 11 per-language `_SOURCE_DIRECTORIES` tuples in `strategies/tdd/*_strategy.py:14` (`/src/`, `/lib/`, `/app/`, `/cmd/`, `/pkg/`, `/internal/`, `/src/main/`, `/Sources/` …); `constants/paths.py:80` (dead)                                                                                                                                                                                                                                                                                                                                                                                   |
| Vendored/build dir names                            | **Four+ conflicting sets**: `docs_qa/corpus.py:93-104` `COMMON_VENDORED_BUILD_DIR_NAMES` (8 names, only home of `third_party`, `.next`); `strategies/lint/common.py:4-16` `COMMON_SKIP_PATHS` (11, only home of `coverage/`, `__pycache__/`, `.git/`); `utils/worktree_seed_suggestions.py:58-75` (14, only home of `.tox`, `.mypy_cache`); `validate_eslint_on_write.py:35` (5); `error_hiding_blocker.py:42-48` (5 globs); 11 per-language `_SKIP_DIRECTORIES` tuples EACH in `strategies/tdd/` and `strategies/qa_suppression/` (the python pair is value-identical, declared twice); `strategies/security/common.py:4-15` |
| "Main repo code dirs" (`src/`, `tests/`, `config/`) | `worktree_file_copy.py:54-55` (regex, twice); `plan_qa/checks/same_commit_plan_doc.py:23`; `plan_qa/checks/path_existence.py:40` — same values, three independent declarations                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| Worktree roots                                      | `constants/paths.py:87-88` (canonical) — but `worktree_file_copy.py:16` re-hardcodes the same two values as a regex literal directly beneath its own constant-derived tuple at `:13` (drift hazard)                                                                                                                                                                                                                                                                                                                                                                                                                           |

### 1c. Non-findings worth recording

- `constants/paths.py` `ProjectPath` **conflates two different subjects**: the
  daemon repository's OWN layout (`HANDLERS_DIR`, `QA_SCRIPTS_DIR` — self-
  install facts) and the CLIENT project's layout (`SRC_DIR`, `TESTS_DIR`,
  `PLAN_DIR` — which are per-project and mostly dead code there). The new block
  is about the CLIENT project; `ProjectPath` should shed or clearly re-scope
  its dead client-layout members, not become the SSoT.
- Self-install detection re-declares `src/claude_code_hooks_daemon` in six
  places (`core/project_context.py:125`, `daemon/paths.py:1096`,
  `daemon/cli.py:1587`, `install/client_validator.py:175`,
  `qa/strategy_pattern_checker.py:422`, `utils/ccy_supervisor.py:37`). That is
  daemon IDENTITY, not project layout — out of scope here (recorded non-goal;
  a DRY fix on its own merits if ever wanted).
- Ansible's `_PLAYBOOK_SEGMENTS` (`strategies/lint/ansible_strategy.py:70`) are
  an ECOSYSTEM convention (Ansible defines them), not project layout. Not
  migrated.
- `qa/runner.py:169-328` hardcodes `src/`/`tests/` — but that is THIS repo's QA
  runner operating on this repo; self-install fact, not client config.
- Stale derived fact: `utils/path_exclusion.py:196-212` and
  `tests/unit/utils/test_path_exclusion.py:7` both say "eight" handlers consume
  `handler_excludes_path`; the actual count is nine (`sensitive_content` is
  uncounted). An R5 violation in miniature — the fix is to stop stating the
  count, not to bump it to nine.
- Three handlers' guidance claims default excludes that code does not implement:
  `comment_size.py:333` and `comment_changelog.py:355` say "vendor/build/
  fixture dirs are skipped by default" yet pass no `defaults=` to
  `handler_excludes_path` (`:179-183`, `:215-219`); `security_antipattern.py`'s
  guidance is true only via strategy `SKIP_PATTERNS`, not exclude_paths. Either
  implement the defaults or correct the guidance (DBF: the guidance drift is
  the guard failure).

---

## 2. Schema proposal

### 2a. Shape: facade over existing homes + new block for homeless truths

**Recommended: do NOT move `documentation.trees` or `plan_workflow.directory`.**
Those truths already have exactly one config home each; their defect is
consumers that bypass it (Shape A). Moving them into a new block would need
alias/precedence/migration machinery and would churn every existing client
config for zero SSoT gain — the SSoT property is "one declaration", which they
already have.

Instead:

1. **A new top-level `layout:` config block** holding ONLY the truths that have
   no home today (Shape B).
2. **A runtime facade, `ProjectLayout`** (a small frozen object built once from
   `Config`), which composes the new block WITH the existing homes
   (`documentation.trees`, `plan_workflow.directory`,
   `plan_workflow.qa.completed_dir/cancelled_dir`) and the built-in constants,
   and is the ONE API handlers call. Handlers never read raw keys and never
   re-declare a truth — satisfying "a single top-level config that other
   handlers access as config SSoT" at the ACCESS level, where the drift
   actually happens, without a key migration.

The alternative — full migration (`layout.agent_docs_dir` canonical,
`documentation.trees.agent` a deprecated alias, fail-fast on contradiction) —
is recorded as Option B in §6 (D2) for the human to overrule; it buys a
tidier YAML shape at the cost of alias machinery, a config-migration manifest
entry per moved key, and a deprecation period.

### 2b. The `layout:` block

```yaml
layout:
  # All lists ADDITIVE onto built-in inference/constants by default (see 2c).
  source_dirs: []        # e.g. ["backend/src", "packages/*/src"]
  test_dirs: []          # e.g. ["backend/tests", "e2e"]
  config_dirs: []        # extends the built-in ["config"]
  vendor_dirs: []        # extends the canonical vendored/build set (see §3)
  mode: additive         # additive | replace (replace: project lists stand alone)
```

Pydantic model `LayoutConfig` (`extra="forbid"`, all defaults empty), field
`layout` on `Config`. `mode: additive|replace` follows the established
precedent (`secret_file_guard`, `flaggable_content_channel_guard`,
`command_hints`, `goal_injection`). One mode for the whole block, not per-list
(YAGNI; per-list modes can be added compatibly later if a real project needs
mixed semantics).

**Deliberately absent** (facade reads existing homes instead):

- `human_docs_dir` / `agent_docs_dir` → `documentation.trees.human/agent`
- `plan_dir` → `plan_workflow.directory`
- plan archive dir names → `plan_workflow.qa.completed_dir/cancelled_dir`

The `ProjectLayout` facade exposes all of them uniformly:

```python
@dataclass(frozen=True)
class ProjectLayout:
    source_dirs: tuple[str, ...]       # declared + (per additive) built-in
    test_dirs: tuple[str, ...]
    config_dirs: tuple[str, ...]
    vendor_dirs: frozenset[str]        # canonical set + declared
    agent_docs_dir: str                # from documentation.trees.agent
    human_docs_dir: str                # from documentation.trees.human
    plan_dir: str                      # from plan_workflow.directory
    plan_archive_dirs: tuple[str, ...] # from plan_workflow.qa
    # plus membership helpers: is_source_path(), is_test_path(),
    # is_vendored_path(), is_docs_path(), is_plan_path()
```

### 2c. Defaults, inference, and additive semantics

Zero-config behaviour must be byte-identical to today. Achieved by:

- Empty `source_dirs`/`test_dirs` ⇒ the per-language TDD strategy conventions
  (`/src/` for Python, `/lib/` for Ruby/Dart, `/src/main/` for JVM …) and
  `COMMON_TEST_DIRECTORIES` remain the inference base, exactly as now.
- `mode: additive` (default) ⇒ declared dirs EXTEND that inference: a project
  declaring `source_dirs: ["engine"]` makes `engine/` source-like for every
  layout consumer WITHOUT disabling Go's `cmd/`/`pkg/` inference for its Go
  files.
- `mode: replace` ⇒ declared lists stand alone (a project whose layout defies
  every convention). Replace applies only to lists the project actually set;
  an unset list keeps its built-ins even under replace (matching how
  `secret_file_guard` scopes its mode to the path-glob list).

Trade-off honestly stated: additive-by-default means a project cannot NARROW
inference without `mode: replace` on the whole block. Accepted — narrowing is
the rare case, and `replace` covers it.

No filesystem sniffing ("does `src/` exist?") — inference stays what it is
today (path-shape conventions), and declaration is explicit config. Guessing
layout from disk at daemon startup is a new failure mode for zero benefit
(Core Standard 8).

### 2d. Handler consumption (DI)

Mirror the existing `_project_exclude_paths` injection: the registry builds one
`ProjectLayout` from `Config` and `setattr`s it onto every handler instance
(`handlers/registry.py:379-386` pattern), e.g. `self._project_layout`. The
plan_qa / docs_qa check packages receive it through their existing context
objects (`plan_qa`'s context already carries `completed_dir`; docs_qa's corpus
takes policy values). No handler constructor churn; no global.

---

## 3. Canonical vendored/build dir set

Consolidate the four independent whole-project sets into ONE reviewed constant
(new module, e.g. `constants/layout.py`, or a re-scoped `constants/paths.py`):
the base for `docs_qa/corpus.py`, `strategies/lint/common.py`,
`utils/worktree_seed_suggestions.py`, `validate_eslint_on_write.py`, and
`error_hiding_blocker`'s glob defaults. Per-DOMAIN extras remain legitimate and
stay local (lint's `__pycache__/`, seed-suggestion's cache dirs) — the shared
constant is the CORE, not a forced union.

**Measurement discipline required** (Plans 00208/00214 precedent): unifying
sets changes behaviour per consumer — e.g. lint would newly skip
`third_party/`, corpus would newly skip `coverage/` — so implementation must
produce a per-consumer before/after diff table and get each delta accepted (or
kept as a domain extra) BEFORE the swap. A silent union is not acceptable.

The 22 per-language `_SKIP_DIRECTORIES` tuples (11 TDD + 11 qa_suppression,
several value-identical pairs) are a per-language convention registry, not
project config. Consolidating each language's pair into one shared per-language
constant is a worthwhile DRY fix but is **deferred to a recorded non-goal**
here (single-domain refactor, no config involvement) — noting it so it is not
re-derived.

---

## 4. The new enforcement: markdown under source/test dirs

Owner direction: markdown in source/test folders must follow the SSoT pattern —
collocated `CLAUDE.md` allowed (directly relevant module docs), everything else
flagged to point/promote.

### 4a. Who owns what today

- `markdown_organization` (PreToolUse, blocking, enabled here) already gates
  markdown LOCATION at write time: its hardcoded allowed list
  (`markdown_organization.py:883-952`) blocks a new `src/foo/NOTES.md` already,
  while `is_adhoc_instruction_file` (`:164-189`) lets `CLAUDE.md` land
  anywhere. But it is **write-time only** — per Core Standard 15's corollary, a
  write-time rule cannot see what predates it or arrives by `mv`/merge.
- `docs_qa` `module-doc-budget` already polices collocated `CLAUDE.md` SHAPE
  (routing budget / registered size tiers) on EDIT + SWEEP.
- Nothing sweeps for NON-`CLAUDE.md` markdown already sitting in source/test
  trees.

### 4b. Proposed division (so the two never double-report)

| Question                                                                       | Owner                                          | Surface                   |
| ------------------------------------------------------------------------------ | ---------------------------------------------- | ------------------------- |
| "May a NEW `.md` be written here?"                                             | `markdown_organization`                        | EDIT (blocking, as today) |
| "Is a collocated `CLAUDE.md` well-shaped?"                                     | `docs_qa` `module-doc-budget`                  | EDIT + SWEEP (as today)   |
| "Does markdown ALREADY ON DISK in a source/test dir violate the SSoT pattern?" | **new** `docs_qa` check `source-tree-markdown` | **SWEEP only**            |

The new check is SWEEP-ONLY by design: an edit-time stage would duplicate
`markdown_organization`'s verdict on every write (double-report), and the gap
it closes is precisely the on-disk/batch one. Findings are ADVISE severity
(R13: all deterministic checks ship advisory; and there is no "worse-only"
baseline for sweep), each naming the file and the remediation: promote content
into the configured agent/human tree and leave a pointer, or convert to a
routing `CLAUDE.md`, or delete. `documentation.qa.grandfather_allowlist`
applies (R12).

Scope comes from the `ProjectLayout` facade (`source_dirs` + `test_dirs`,
vendored/worktree/daemon-install paths excluded via the same corpus
exclusions). Allowed in place: `CLAUDE.md` (budget-checked separately),
`README.md` (conventional package/module entry point — flagging every
`README.md` under `src/` would be noise; see D4), generated-docs manifest
entries (R10), and test FIXTURE markdown (a `.md` under
`tests/fixtures/`-style dirs is test data, not documentation — reuse the
fixture-dir conventions).

### 4c. Reconciliation refactor for `markdown_organization`

Independent of the new check, `markdown_organization` gets the Shape-A fix: its
allowed-location logic reads the facade (`agent_docs_dir`, `human_docs_dir`,
`plan_dir`, `plan_archive_dirs`) instead of hardcoding `CLAUDE/`, `docs/`,
`claude/plan/`, `("completed", "cancelled", "archive")`. This dissolves the
live conflict in §1a. Its daemon-repo-specific allowances
(`src/claude_code_hooks_daemon/guides|skills/**.md`) stay hardcoded — they
describe the DAEMON's shipped assets, not the client project. Its two pattern
languages (regex options vs the glob dialect everywhere else) are flagged but
NOT unified here (breaking change to existing option values; recorded
non-goal).

---

## 5. Consumption refactors (sized; only ≥2-consumer truths)

| #   | Refactor                                                                                                                                                                                                                                                                                                                  | Consumers touched                                                                                | Size   |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ------ |
| C1  | Build `LayoutConfig` + `ProjectLayout` facade + registry injection + `plan_qa`/`docs_qa` context plumbing                                                                                                                                                                                                                 | new module + registry                                                                            | M      |
| C2  | Canonical vendored/build core constant + per-consumer measured swap (§3)                                                                                                                                                                                                                                                  | corpus, module_doc_budget, lint common, seed suggestions, eslint-on-write, error_hiding defaults | M      |
| C3  | `markdown_organization` reads facade (§4c)                                                                                                                                                                                                                                                                                | 1 handler, several branches                                                                      | M      |
| C4  | Plan-dir regex handlers read facade                                                                                                                                                                                                                                                                                       | `goal_injection`, `recovery_cron_advisor`, `plan_workflow`, `plan_number_helper`                 | S each |
| C5  | "Main repo code dirs" from facade (`source_dirs`+`test_dirs`+`config_dirs`)                                                                                                                                                                                                                                               | `worktree_file_copy`, `same_commit_plan_doc`, `path_existence`                                   | S      |
| C6  | TDD source/test resolution consults facade first (declared dirs), inference as fallback — `test_path_map` continues to work unchanged and stays the flat-placement override                                                                                                                                               | `tdd_enforcement` + strategy gate                                                                | M      |
| C7  | `british_english` `CHECK_DIRECTORIES` derives docs dirs from facade (keeps `private_html`-style extras as handler OPTION — that one is behaviour, not truth)                                                                                                                                                              | 1 handler                                                                                        | S      |
| C8  | Drive-bys: `worktree_file_copy.py:16` regex derived from its own `:13` constant; delete `constants/paths.py` dead client-layout members (or re-scope with a comment); fix the stale "eight callers" derived-fact docstrings (state no count); fix or implement the three handlers' phantom default-exclude guidance (§1c) | small                                                                                            | S      |

Recorded NON-goals (≥1 consumer or wrong concept): self-install marker
sextuplet; ansible ecosystem segments; per-language TDD/qa_suppression skip
tuple consolidation; markdown_organization pattern-language unification;
`docs_qa/policy.py` defaults mirror (deliberate, documented); qa runner's own
`src/`/`tests/` args.

---

## 6. Decisions needed from the human

- **D1 — Block name**: `layout:` (recommended: named for exactly what it
  holds, matching `documentation:`/`plan_workflow:` style) vs `project:`
  (more extensible if non-layout "project truths" are anticipated; YAGNI says
  don't reserve the name on speculation). Renaming later is a config
  migration, so worth settling now.
- **D2 — Facade vs full migration** (§2a): recommended Option A (facade;
  existing keys stay canonical). Option B (move keys under `layout:` with
  deprecated aliases) only if the owner wants the YAML itself, not just the
  access API, unified — it costs alias/precedence machinery and a per-key
  config-changes migration entry.
- **D3 — Should any source dir be REQUIRED to carry a `CLAUDE.md`?** The
  direction "ensure that md files in src and test folders are present but
  enforce the SSoT pattern" reads two ways: (i) markdown that IS present must
  follow the pattern (designed here, §4), or (ii) major source dirs SHOULD
  each have a routing `CLAUDE.md` (a presence check — plausible but noisy:
  which dirs count as "major"?). This design implements (i) and defers (ii)
  pending the owner confirming they want it and for what granularity.
- **D4 — `README.md` under source dirs**: proposed allowed-in-place (package
  convention). Confirm, or include it in the flagged set.

## 7. Client impact on upgrade

- **No `layout:` block ⇒ nothing changes.** Defaults are empty; facade
  composition reproduces today's inference and constants exactly. Pinned by
  before/after tests on every refactored consumer.
- The Shape-A fixes change behaviour ONLY for clients who configured
  `documentation.trees` / `plan_workflow.directory` / archive dirs to
  non-defaults — for them the previously-hardcoding handlers start honouring
  their config (bug fix in their favour, but a behaviour change: goes in the
  release's truth-changes manifest).
- C2's vendored-set deltas are per-consumer and gated on the measured diff
  table (§3).
- A `config-changes` manifest entry (`UNRELEASED/config-changes/`) declares
  `layout` as `added` (and `recommended: false` — it is useful, not urgent);
  the new `source-tree-markdown` check ships advisory under existing
  `documentation.qa` modes, off wherever `documentation.enabled` is false
  (upstream default), so dormant for clients until they opt in.

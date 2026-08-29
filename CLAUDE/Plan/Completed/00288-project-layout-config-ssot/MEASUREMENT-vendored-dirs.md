# Measurement — vendored/build dir set unification (Task 3.1)

Measured 2026-08-29 against the current tree (post-Task-5b.1 state, commit
`f8212b8f` lineage). This is the before/after diff table DESIGN §3 requires
before any swap: exact current membership per consumer, a proposed CORE set,
per-consumer deltas each with an ACCEPT / KEEP-LOCAL verdict, and a
behavioural-risk note per ACCEPT. Analysis only — no source changed; the swap
is Task 3.2.

## 1. Current membership, cited

### 1a. `docs_qa/corpus.py` — `COMMON_VENDORED_BUILD_DIR_NAMES`

`src/claude_code_hooks_daemon/docs_qa/corpus.py:94-105` (8 names; the design's
`:93-104` citation has shifted by one line since — membership unchanged):

`node_modules`, `vendor`, `dist`, `build`, `target`, `.venv`, `.next`,
`third_party`

Matching: exact path-SEGMENT equality over the relative path's directory parts
(`corpus.py:199`). Also composed downstream by
`docs_qa/checks/module_doc_budget.py:103-112`, whose `_EXCLUDED_DIR_NAMES` is
this frozenset unioned with `{untracked, .git, worktrees}` — so
module_doc_budget inherits any corpus delta automatically and needs no swap of
its own.

### 1b. `strategies/lint/common.py` — `COMMON_SKIP_PATHS`

`src/claude_code_hooks_daemon/strategies/lint/common.py:4-16` (11 entries,
slash-suffixed):

`node_modules/`, `dist/`, `vendor/`, `.build/`, `coverage/`, `.venv/`,
`venv/`, `__pycache__/`, `.git/`, `target/`, `build/`

Matching: SUBSTRING containment anywhere in the full path
(`common.py:19-29` `matches_skip_path`; the trailing slash keeps `build/` from
matching a FILE named `build`, but it still matches `mybuild/x.py`).
Consumed by ten lint strategies (`php|python|go|rust|kotlin|swift|dart|shell|ruby|ansible_strategy.py`, each `get_skip_paths` returning it verbatim);
`rust_strategy.py:12,40` appends `_EXTRA_SKIP_PATHS = ("target/",)` which is
ALREADY in the common set — fully redundant, a drift-in-miniature the design
inventory did not list.

### 1c. `utils/worktree_seed_suggestions.py` — `_EXCLUDED_DIRECTORY_NAMES`

`src/claude_code_hooks_daemon/utils/worktree_seed_suggestions.py:58-75`
(14 names):

`.git`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.tox`, `.venv`,
`__pycache__`, `build`, `dist`, `node_modules`, `target`, `untracked`,
`vendor`, `venv`

Matching: exact path-segment equality (`:104-106`).

### 1d. `handlers/post_tool_use/validate_eslint_on_write.py` — `SKIP_PATHS`

`src/claude_code_hooks_daemon/handlers/post_tool_use/validate_eslint_on_write.py:35`
(5 names, NO slash suffix):

`node_modules`, `dist`, `.build`, `coverage`, `test-results`

Matching: bare SUBSTRING containment (`:83` `any(skip in file_path ...)`) —
the loosest matcher of the five: `dist` already matches
`src/distribution/x.ts` today.

### 1e. `handlers/pre_tool_use/error_hiding_blocker.py` — `_DEFAULT_EXCLUDE_GLOBS`

`src/claude_code_hooks_daemon/handlers/pre_tool_use/error_hiding_blocker.py:42-48`
(5 globs, applied via `handler_excludes_path(defaults=...)` at `:136-139`):

`**/vendor/**`, `**/node_modules/**`, `**/tests/fixtures/**`,
`**/tests/assets/**`, `**/__fixtures__/**`

Only the first TWO are vendored/build dirs; the other three are test-FIXTURE
semantics (deliberately-broken code), a different category that stays local.
Matching: gitignore-style glob, segment-anchored.

### 1f. Adjacent set, in scope for context only

`strategies/security/common.py:4-15` `SKIP_PATTERNS` mixes vendored dirs
(`/vendor/`, `/node_modules/`) with fixture, docs and repo-specific paths
(`/docs/`, `/CLAUDE/`, `/eslint-rules/`, `/tests/PHPStan/`,
`/strategies/security/`, `.env.example`). Its vendored pair matches the core;
the rest is domain policy. Task 3.2 may swap its two vendored entries onto the
core or leave the set intact — the design's C2 row does not list it as a
mandatory consumer, and its repo-specific entries make a full swap wrong.

## 2. Proposed CORE set (11 names)

Criterion for CORE membership: the directory holds only third-party or
generated content in ANY ecosystem, so no consumer that skips
vendored/build content could ever be wrong to skip it. Entries failing that
test (tool caches, VCS internals, fixture dirs, this-daemon conventions) stay
domain extras.

| Name           | Justification                                                  | Present today in                 |
| -------------- | -------------------------------------------------------------- | -------------------------------- |
| `node_modules` | JS dependency tree — vendored by definition                    | all five sets                    |
| `vendor`       | Go/PHP/Ruby vendoring convention                               | corpus, lint, seed, error_hiding |
| `third_party`  | Vendored code by definition (Chromium/Bazel convention)        | corpus only                      |
| `dist`         | JS/Python distribution output                                  | corpus, lint, seed, eslint       |
| `build`        | Generic build output                                           | corpus, lint, seed               |
| `.build`       | SwiftPM build output                                           | lint, eslint                     |
| `target`       | Cargo/Maven build output                                       | corpus, lint, seed               |
| `.next`        | Next.js build output                                           | corpus only                      |
| `.venv`        | Python virtualenv (deps + activation scripts, all third-party) | corpus, lint, seed               |
| `venv`         | Ditto, unhidden spelling                                       | lint, seed                       |
| `coverage`     | Coverage-report output (generated html/lcov)                   | lint, eslint                     |

Union entries argued OUT of the core, as domain extras:

- `__pycache__`, `.git` — byte-compiled cache and VCS internals, not
  "vendored/build". Harmless in every consumer, but the constant should mean
  what its name says; lint keeps them as its extras (they are lint's only
  extras), seed keeps `.git`.
- `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.tox` — Python TOOL caches;
  seed-suggestion extras (the design's own worked example of a domain extra).
  The seed walk scans gitignored paths where caches abound; no other consumer
  ever encounters them as candidates worth excluding.
- `untracked` — this daemon's own scratch convention (daemon identity, not
  project layout); seed extra, and separately declared where needed
  (module_doc_budget).
- `test-results` — Playwright/JS test artifact dir; eslint-on-write extra.
  Plausible future core member, but single-consumer today and its bare-substring
  matcher makes broad names risky there (§4).
- `**/tests/fixtures/**`, `**/tests/assets/**`, `**/__fixtures__/**` —
  fixture semantics, error_hiding_blocker extras (shared with the
  qa_suppression/security fixture conventions, which are a different truth).

## 3. Per-consumer delta table

"Newly skips" = core ∪ kept-extras minus today's set. "Keeps as extra" =
today's entries the core lacks.

| Consumer                   | Newly skips (delta)                                                                      | Verdict per delta                            | Keeps as domain extra                                                                     |
| -------------------------- | ---------------------------------------------------------------------------------------- | -------------------------------------------- | ----------------------------------------------------------------------------------------- |
| corpus (1a)                | `.build`, `venv`, `coverage`                                                             | ACCEPT all                                   | — (module_doc_budget's `{untracked, .git, worktrees}` union unchanged)                    |
| lint common (1b)           | `.next`, `third_party`                                                                   | ACCEPT both                                  | `__pycache__/`, `.git/` (and Task 3.2 should DROP rust's redundant `target/`)             |
| seed suggestions (1c)      | `.build`, `.next`, `third_party`, `coverage`                                             | ACCEPT all                                   | `.git`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.tox`, `__pycache__`, `untracked` |
| eslint-on-write (1d)       | `vendor`, `build`, `target`, `.venv`, `venv`, `.next`, `third_party`                     | ACCEPT all — CONDITIONAL on matcher fix (§4) | `test-results`                                                                            |
| error_hiding defaults (1e) | `dist`, `build`, `.build`, `target`, `.venv`, `venv`, `.next`, `third_party`, `coverage` | ACCEPT all                                   | the three fixture globs                                                                   |

Totals: **21 ACCEPT deltas, 0 KEEP-LOCAL deltas** (every candidate delta from
the core is desirable), with **13 existing entries retained as domain extras**
across lint/seed/eslint/error_hiding.

## 4. Behavioural-risk notes per ACCEPT delta

- **corpus newly skips `.build`, `venv`, `coverage`**: a `.md` inside those
  dirs leaves the tracked doc corpus (no link-graph node, no sweep findings).
  No such dirs exist in this repo (`venv` exists only as the
  `untracked/venv` symlink, already outside corpus scope). For clients, docs
  inside a virtualenv or coverage output are third-party/generated — dropping
  them is the intent. Residual risk: a project with a FIRST-PARTY dir literally
  named `venv/` or `coverage/` holding real docs loses tracking; implausible,
  and `layout.vendor_dirs`/`mode: replace` (Task 2.x) is the declared remedy.
- **lint newly skips `.next`, `third_party`**: generated Next.js output and
  vendored code stop being lint-denied on write. Neither dir exists in this
  repo. For clients this is the intent — a heredoc-authored file inside
  `third_party/` is vendored bytes, not authored source. Note the lint set
  never applied to JS/TS anyway (no JS lint strategy exists; TS is
  `validate_eslint_on_write`'s), so `.next` is near-inert for lint in practice.
- **seed newly skips `.build`, `.next`, `third_party`, `coverage`**: gitignored
  config-looking files at depth ≤2 inside these dirs stop being suggested as
  worktree seeds. They were incidental matches — exactly what
  `_is_excluded` exists to drop. No behaviour change in this repo (none of the
  four exists at suggestion depth).
- **eslint-on-write newly skips 7 names — RISK, matcher must change first**:
  `SKIP_PATHS` uses bare substring matching (`:83`), so adding `build` would
  newly skip `src/builder/x.ts`, and `venv` would skip `src/venvtool.ts` —
  silent loss of ESLint enforcement on first-party files whose PATH merely
  contains the token. The delta is only acceptable if Task 3.2 also moves this
  consumer to segment matching (or slash-bounded containment like lint's).
  With that fix, the deltas themselves are pure intent: vendored/generated
  `.ts` under `vendor/`, `build/`, `.next/` stops producing write DENIALs.
  This repo has no `.ts` files, so zero local behaviour change either way.
- **error_hiding newly exempts 9 names**: error-suppression patterns inside
  build outputs and venvs stop being write-blocked. Aligned with the handler's
  own stated intent (`:38-41` "generated/vendored trees ... are never
  scanned"); writes into build outputs are rare and wrong for independent
  reasons. Glob matching is segment-anchored, so no over-match risk. No such
  dirs are written to in this repo.
- **Cross-cutting**: matching SEMANTICS stay per-consumer in Task 3.2 (segment
  for corpus/seed, slash-substring for lint, glob for error_hiding); only the
  MEMBERSHIP unifies. Unifying the matchers too is a separate decision — the
  eslint fix above is the one place a matcher change is a precondition rather
  than an option.

## 5. Dead-code claims — verified

Both DESIGN §1b/§1c claims check out, and the first is wider than stated:

- **`constants/paths.py` client-layout members are dead.**
  `grep -rn "ProjectPath\.<member>" src/ tests/ scripts/` finds ZERO uses of
  `SRC_DIR`, `TESTS_DIR`, `UNIT_TESTS_DIR`, `INTEGRATION_TESTS_DIR`,
  `PLAN_DIR`, `PLAN_COMPLETED_DIR`, `RELEASES_DIR`, `UPGRADES_DIR`,
  `CLAUDE_DOC_DIR`, all five `*_DOC` members, `CLAUDE_MD`, `README_MD`,
  `CONTRIBUTING_MD`, `PLAN_FILE`, `PLAN_README`, `SCRIPTS_DIR`,
  `QA_SCRIPTS_DIR`, `HANDLERS_DIR`, `CONFIG_DIR`, `CORE_DIR`, `DAEMON_DIR`,
  `PYPROJECT_TOML`, `SETUP_PY`, `REQUIREMENTS_TXT` outside the defining module
  (`constants/paths.py:43-99`). The ONLY live `ProjectPath` members are
  `WORKTREES_DIR` (:87), `CLAUDE_WORKTREES_DIR` (:88) and
  `HOOKS_DAEMON_INSTALL_DIR` (:94); no test file references `ProjectPath` at
  all. So the C8 drive-by can delete nearly the whole class body, not just the
  three members the design names.
- **`worktree_file_copy.py:16` duplicates `:13`.** `_WORKTREE_PREFIXES`
  (:13) is derived from the two `ProjectPath` constants;
  `_WORKTREE_RE = r"(?:untracked/worktrees|\.claude/worktrees)"` (:16)
  re-hardcodes the same two values as a regex literal directly beneath it.
  Confirmed verbatim; C8's derive-the-regex fix stands.

## 6. Surprises vs the design's inventory

1. `rust_strategy.py:12` `_EXTRA_SKIP_PATHS = ("target/",)` is redundant with
   `COMMON_SKIP_PATHS` (which already carries `target/`) — not in the design's
   inventory; fold into Task 3.2.
2. `validate_eslint_on_write`'s bare-substring matcher makes membership
   unification UNSAFE without a matcher change (§4) — the design measured
   memberships but not matcher dialects.
3. Only 2 of `error_hiding_blocker`'s 5 default globs are vendored/build; the
   design's "5 globs" count is right but the set is 40% vendored, 60% fixture.
4. `ProjectPath` dead code is broader than the design's three named members —
   effectively the entire client-layout half of the class (§5).
5. Line drift only: corpus set now at `:94-105`; membership identical to the
   design's snapshot.

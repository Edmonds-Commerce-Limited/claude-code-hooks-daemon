# Plan 00251: tdd_enforcement needs an exclusion escape and a declarable test root

**Status**: In Progress
**Created**: 2026-08-17
**Owner**: Claude (Opus 5)
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

A field report from a client monorepo (`FIELD-REPORT.md` in this folder) — a
new custom PHPStan rule cannot be authored, because `tdd_enforcement` denies the
source file and **no configuration can exempt it**. The reporter's test is in
the right place by their project's own convention (`qaConfig/Tests/`, capital T,
the only directory their `phpunit.xml` scans), and that location is not among
the candidates the handler searches.

Every claim in the report was re-verified against the source before this plan
was filed, and one of its three diagnoses was found to be **wrong in a way that
matters** — its recommended remedy for that defect would not have worked. See
"Verified findings" below.

## Verified findings

| ID  | Verdict                    | Where                                     | Defect                                                               |
| --- | -------------------------- | ----------------------------------------- | -------------------------------------------------------------------- |
| A   | REAL, **misdiagnosed**     | `strategies/tdd/php_strategy.py:15,63-79` | QA-tooling dirs under a source root are classified production source |
| B   | REAL                       | `handlers/…/tdd_enforcement.py:213,219`   | Both mirror test-path resolvers are gated on a `src/` path segment   |
| C   | REAL, and **already owed** | `handlers/…/tdd_enforcement.py` (absent)  | No `exclude_paths` support, unlike SIX sibling PreToolUse handlers   |

### A — real gap, but NOT the substring false-match the report describes

The report says the monorepo path `…/apps/app/qaConfig/…` "contains the
substring `/app/`", implying an accidental match that a segment-exact comparison
would fix. Executed against the real code, that is not what happens:

```
matches_directory(path, ("/src/", "/app/")):
   True  /workspace/apps/app/qaConfig/PHPStan/Rules/Foo.php
  False  /workspace/apps/foo.php
  False  /workspace/application/foo.php
  False  /workspace/happ/foo.php
```

`matches_directory` normalises every pattern to leading **and** trailing `/`
(`common.py:22-27`), so it is already effectively segment-bounded — `apps`,
`application` and `happ` do not match. The `/app/` hit is a **correct** match on
a directory genuinely named `app`.

So the report's Option 2 ("make the `/app/` match segment-exact and not fire
inside `apps/app/`") would change nothing: `app` already *is* an exact segment.
The real defect is narrower and different — the PHP strategy has no notion that
a QA-tooling directory inside a source root is not application source. That is a
**scoping** gap, and the fix for C resolves it without touching a heuristic other
PHP projects legitimately depend on.

### C — this is Plan 00150's explicitly deferred follow-up

Plan 00150 ("client-configurable exclude_paths for content-scanning blockers",
Complete) wired three handlers and recorded in its **Non-Goals**:

> Not wiring `lint_on_edit` / `tdd_enforcement` this plan (follow-up if wanted).

So C is not an oversight to be argued for — it is the follow-up that plan named,
and `lint_on_edit` was deferred in the same breath. Six handlers now honour
exclusions (`qa_suppression`, `security_antipattern`, `error_hiding_blocker`,
`comment_size`, `comment_changelog`, `sensitive_content`); `tdd_enforcement` and
`lint_on_edit` are the two that do not, and both **deny**.

### The DRY fact that shapes the fix

`_is_excluded` is **byte-identical in five of the six** wired handlers, and the
sixth (`error_hiding_blocker`) differs only by prepending its own defaults and
dropping a `bool(patterns)` short-circuit. Adding a seventh copy would be the
wrong move; the shared helper wants extracting first (Core Standard 7), which
also removes the `getattr(self, "_project_exclude_paths", None)` defensive
idiom that exists only because `registry.py:364` injects the attribute after
construction.

## Goals

- A project can exempt a directory from TDD enforcement via config, consistent
  with the six handlers that already allow it.
- A project can DECLARE its non-`src/` test root and keep TDD enforcement ON,
  because excluding is a weaker outcome than mapping.
- The exclusion helper has one definition, not seven.
- `lint_on_edit` gets the same treatment, since it is the other half of Plan
  00150's deferral and it also denies.

## Non-Goals

- Changing `_SOURCE_DIRECTORIES` or `matches_directory`. `/app/` is a legitimate
  PHP source root and the match is correct; see finding A.
- Hardcoding `qaConfig/` (or any project's directory name) into a shared
  strategy. Config is the source of truth; a client convention in upstream code
  is the defect that pattern exists to prevent.
- Relaxing TDD enforcement by default. Every change here is opt-in per project.

## Tasks

### Phase 1: Extract the duplicated exclusion helper

- [x] ✅ **Task 1.1**: RED — a test that pins the shared helper's behaviour,
  including the `error_hiding_blocker` variant (defaults prepended) and the
  empty-patterns short-circuit
  - [x] ✅ 7 tests on `handler_excludes_path`, including that the three sources
    are ADDITIVE (no source may mask another) and that `[]` behaves as `None`
- [x] ✅ **Task 1.2**: Extract one helper, and move all six handlers onto it
  - [x] ✅ Confirm behaviour is unchanged for each — this is a refactor, so the
    existing tests for all six must pass untouched
    - [x] ✅ 424 passed across the six handlers' own test modules plus
      `test_path_exclusion` and `test_handler`, none of them edited
    - [x] ✅ Verified through the LIVE socket after restart, not only in unit
      tests: `error_hiding_blocker` (the defaults variant) and
      `security_antipattern` (a guarded variant) both still DENY
  - [x] ✅ Formalise the post-construction injection rather than reproducing
    `getattr(self, ..., None)` in the shared code
    - [x] ✅ Root cause was in `core/handler.py`: `__slots__` declared
      `_project_exclude_paths`/`_project_languages` and the class annotated both
      as `list[str] | None`, but `__init__` assigned NEITHER — so the slot
      existed while unset and plain access raised `AttributeError` on any
      handler built outside the registry. The annotation was the lie; assigning
      both to `None` makes it true and retires the idiom at **14 sites across 9
      modules**. RED first (two `AttributeError`s), and a third test pins that
      the registry can still overwrite them

### Phase 2: Wire the two handlers Plan 00150 deferred (finding C)

- [x] ✅ **Task 2.1**: RED — `tdd_enforcement` fires on an excluded path
- [x] ✅ **Task 2.2**: GREEN — `matches()` short-circuits on an excluded path,
  honouring both the per-handler `exclude_paths` and the project-wide
  `daemon.exclude_paths`
  - [x] ✅ Checked BEFORE the strategy lookup: an exclusion is the project
    stating a path is out of scope, which outranks any per-language judgement
    and must not depend on a strategy existing for the extension
- [x] ✅ **Task 2.3**: Same for `lint_on_edit`, the other half of the deferral
- [x] ✅ **Task 2.4**: Verify finding A's symptom is resolved by this alone —
  the reporter's path, excluded by config, no longer denies
  - [x] ✅ Executed against the reporter's exact path: unconfigured it still
    matches (no default relaxed), and either `**/qaConfig/PHPStan/Rules/**` or
    `**/qaConfig/**` exempts it while a real source file beside it still matches
- [x] ✅ **Task 2.5**: Fix `config/models.py:904`, which enumerated four
  handlers as honouring `daemon.exclude_paths` while six consumed it — the same
  stale-count drift found in Phase 1, now pointing at `handler_excludes_path`
  instead of a number that this phase would have made wrong again

### Phase 3: A declarable test root (finding B)

- [x] ✅ **Task 3.1**: RED — a source file under a non-`src/` PSR-4 root with a
  correctly-placed test is still denied
  - [x] ✅ Kept as a permanent regression pin rather than deleted once green:
    it is the evidence that no inference reaches `qaConfig/Tests/`, which is the
    entire justification for a config surface
- [x] ✅ **Task 3.2**: Add a configurable source-glob-to-test-dir mapping, so the
  resolver gains the declared candidate
  - [x] ✅ Decide the config shape against the existing `_effective_test_locations`
    option rather than beside it — there is already a test-location config
    surface, and a second unrelated one is how config sprawls
    - [x] ✅ Resolved as Decision 5: `test_locations` selects among INFERENCE
      styles, so a DECLARATION is not one of its values and is not gated by it
  - [x] ✅ `test_path_map: [{source_glob, test_dir}]`, matched with the same glob
    dialect as `exclude_paths`; declared candidates searched FIRST
  - [x] ✅ RED proved by disabling only the resolver wiring: 6 failed / 11 passed,
    then 17 passed with it restored — so the new tests discriminate rather than
    passing vacuously
- [x] ✅ **Task 3.3**: Confirm the reporter's layout passes with enforcement ON,
  which is the outcome that keeps the value of the gate
  - [x] ✅ Executed on the reporter's exact layout: `matches=True` in every case
    (the gate never stops firing), `allow` with the test present, and with the
    test deleted the deny message's FIRST searched location is the project's own
    declared directory

### Phase 4: Verify

- [ ] ⬜ **Task 4.1**: Full QA green, daemon restart RUNNING
- [ ] ⬜ **Task 4.2**: Client-mode verification — this changes handler matching
  driven by project config, so verify in `dummy-client-repo` as well as
  self-install
- [ ] ⬜ **Task 4.3**: Document both options in
  `docs/guides/HANDLER_REFERENCE.md`, and record a `config-changes` manifest
  entry so upgrading projects are told the option exists

## Dependencies

- Follows: Plan 00150 (Complete) — this executes the follow-up its Non-Goals
  named, for both handlers it deferred.
- Related: Plan 00055 (Complete), which gave the resolver its multiple-candidate
  design. Phase 3 extends that rather than replacing it.

## Technical Decisions

### Decision 1: fix the scoping gap with config, not with a wider skip-list

**Context**: finding A could be fixed by adding `qaConfig/` to the PHP
strategy's `_SKIP_DIRECTORIES`, which is a one-line change.

**Decision**: no. `qaConfig/` is one project's convention, and upstream code is
the wrong place for it — Core Standard 10 (config is truth) exists for exactly
this. The exclusion mechanism from Phase 2 lets that project declare it, and
every other project declare its own, without upstream knowing any of them.

**Date**: 2026-08-17

### Decision 2: exclusion AND mapping, not exclusion alone

**Context**: the report's recommendation is Option 1 (exclude) as the unblock,
with Option 3 (mapping) as "best long-term".

**Decision**: do both, in that order. The report itself demonstrates that this
project TDDs its PHPStan rules successfully — 40+ of them, with a worked
`RuleTestCase` example — so excluding them gives up a working TDD flow. The
exclusion is the right unblock precisely because it is available immediately; the
mapping is the right end state because it keeps the gate on. Shipping only the
exclusion would leave the better outcome permanently unbuilt.

**Date**: 2026-08-17

### Decision 3: extract the helper before adding the seventh caller

**Context**: five byte-identical copies of `_is_excluded`, plus one near-copy.

**Decision**: Phase 1 extracts before Phase 2 adds. Adding callers 7 and 8 to a
five-times-duplicated helper is how six copies became a norm in the first place,
and the extraction is what makes Phase 2 a two-line change per handler.

**Date**: 2026-08-17

### Decision 4: `test_dir` is project-root-relative, not suffix-anchored

**Context**: the report's example writes `test_dir: "qaConfig/Tests"` while the
real directory is `apps/app/qaConfig/Tests`. So the report implies a SUFFIX,
resolved by walking up from the source file to the nearest ancestor named
`qaConfig`. That form handles a whole monorepo in one entry.

**Options considered**:

1. **Project-root-relative** (or absolute). One rule, no walking, no ambiguity.
   Costs one entry per app in a monorepo.
2. **Suffix-anchored on `test_dir`'s first segment.** Elegant for the reporter,
   but it is implicit path magic (Core Standard 9), and it needs a SECOND rule
   for the case where the first segment names no ancestor — e.g.
   `test_dir: "Tests"` with the source in `qaConfig/PHPStan/Rules/`. Two rules
   means the meaning of a value depends on the tree, which is exactly the class
   of surprise a declaration exists to remove.

**Decision**: Option 1. It also matches the anchoring a project has already
learned from `exclude_paths` globs (a leading `/` anchors to the project root),
so the whole config surface has one mental model. The repetition is honest and
greppable, and a typo surfaces in the deny message's searched-locations list —
the one place the author is already reading. Option 2 stays available later
without breaking Option 1, since a suffix form would be a new spelling rather
than a changed meaning.

**Date**: 2026-08-17

### Decision 5: a declaration is not gated by `test_locations`

**Context**: Task 3.2 required designing against `_effective_test_locations`
rather than beside it. The obvious reading is to add a fourth style token
(`mapped`) to that option.

**Decision**: no — and the reason is that the two options answer different
questions. `test_locations` selects WHICH of three built-in INFERENCE styles to
attempt. `test_path_map` is the project asserting a FACT about its own tree. A
fact does not belong in a list of guesses, and gating it there would produce two
bad outcomes: a project would have to opt in twice (declare the map, then enable
the style), and a project narrowing to `test_locations: ["collocated"]` would
silently lose its own declared test root. Declared candidates are therefore
always added, and added FIRST, because a declaration outranks every inference.

**Date**: 2026-08-17

## Success Criteria

- [ ] A project can exclude a directory from `tdd_enforcement` and from
  `lint_on_edit` via `.claude/hooks-daemon.yaml`
- [ ] A project can declare a non-`src/` test root and keep enforcement ON
- [ ] `_is_excluded` has exactly one definition
- [ ] The reporter's exact layout is verified working, both ways
- [ ] No change to default behaviour for any project that configures nothing
- [ ] QA green, daemon restart RUNNING, client-mode verified

## Risks & Mitigations

| Risk                                                      | Impact | Probability | Mitigation                                                                                             |
| --------------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------------------------------ |
| Refactoring six live handlers regresses one of them       | High   | Low         | Phase 1 is behaviour-preserving by definition; all six handlers' existing tests must pass as-is        |
| An exclusion escape gets used to switch TDD off wholesale | Medium | Medium      | Opt-in, per-path globs, and Phase 3 gives the better alternative so the blunt tool is not the only one |
| A new test-path config surface overlaps the existing one  | Medium | Medium      | Task 3.2 requires designing it against `_effective_test_locations`, not beside it                      |
| Clients never learn the option exists                     | Medium | High        | Task 4.3 requires a `config-changes` manifest entry, which the upgrade advisory surfaces               |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Filed at the commit that adds this plan.

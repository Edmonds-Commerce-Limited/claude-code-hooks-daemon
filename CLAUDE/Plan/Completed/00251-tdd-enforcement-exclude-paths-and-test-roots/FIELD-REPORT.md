# Hooks-daemon report: `tdd_enforcement` blocks new custom PHPStan rules

**Component:** `claude-code-hooks-daemon` → `pre_tool_use.tdd_enforcement` (+ PHP TDD strategy)
**Repo:** `Edmonds-Commerce-Limited/claude-code-hooks-daemon` (upstream — must not be edited in this project)
**Reported from:** the `marketing` project, Plan 00197 (schema type-safety nets)
**Status:** blocking — cannot author a new `qaConfig/PHPStan/Rules/*.php` rule with a runnable, convention-correct test

---

## TL;DR

Creating a **new custom PHPStan rule** in this repo is blocked by `tdd_enforcement`. Two compounding
daemon behaviours cause it, and there is currently **no config escape** because — unlike the content
blockers — `tdd_enforcement` does not honour `exclude_paths`.

The user's instinct ("allow certain dirs to be excluded from TDD enforcement") is the right *shape* of
fix and the smallest change. But the premise that **"stan rules are not easy to TDD"** is not the real
problem — this repo already TDDs its rules cleanly (40+ of them). The block is a **path-mapping bug**,
not a TDD-feasibility problem. Details and options below.

---

## Symptom

`Write` of a brand-new rule source file is denied:

```
TDD REQUIRED: Cannot create PHP source file without test file
Source file: EnumColumnMappingPolicy.php
Missing test: EnumColumnMappingPolicyTest.php
Searched locations:
  - /workspace/apps/app/qaConfig/tests/EnumColumnMappingPolicyTest.php      ← lowercase "tests"
  - /workspace/apps/app/qaConfig/PHPStan/Rules/EnumColumnMappingPolicyTest.php   ← collocated
  - /workspace/apps/app/qaConfig/PHPStan/Rules/__tests__/EnumColumnMappingPolicyTest.php
```

The real, house-convention test location — `qaConfig/Tests/EnumColumnMappingPolicyTest.php` (capital
`Tests`) — is **not** among the searched locations, so a correctly-placed test never satisfies the gate.

---

## This repo's custom-rule layout (the context the daemon must fit)

- **Rules** live in `apps/app/qaConfig/PHPStan/Rules/*.php` (namespace `QaConfig\PHPStan\Rules`).
  This is mandated by the project (`qaConfig/PHPStan/CLAUDE.md`: *"NEVER put rules in `src/PHPStan/`"*).
- **Rule tests** live in `apps/app/qaConfig/Tests/*Test.php` (namespace `QaConfig\Tests`), autoloaded
  via `composer.json` `autoload-dev` (`QaConfig\Tests\ → qaConfig/Tests/`).
- **phpunit only runs tests from `qaConfig/Tests`.** `qaConfig/phpunit.xml` declares a dedicated
  `qa-rules` testsuite: `<directory suffix="Test.php">../qaConfig/Tests</directory>` — and nothing else
  under `qaConfig/`. A test placed collocated (`qaConfig/PHPStan/Rules/FooTest.php`) or in a lowercase
  `qaConfig/tests/` would **not be discovered or executed**.

So the two hook-accepted alternatives (collocated / lowercase `tests/`) are not merely unconventional
here — a test in either location **would never run**, defeating the purpose.

---

## Root cause (two compounding daemon behaviours)

### Bug A — the `/app/` source-dir heuristic false-matches the monorepo's `apps/app/` root

`strategies/tdd/php_strategy.py`:

```python
_SOURCE_DIRECTORIES: tuple[str, ...] = ("/src/", "/app/")
...
def is_production_source(self, file_path: str) -> bool:
    return matches_directory(file_path, _SOURCE_DIRECTORIES)

def should_skip(self, file_path: str, content: str = "") -> bool:
    if matches_directory(file_path, _SKIP_DIRECTORIES):  # only tests/fixtures/, vendor/
        ...
```

`_SOURCE_DIRECTORIES` includes `/app/` (intended for PHP projects whose source root is `app/`). This
repo is a monorepo whose application root is **`apps/app/`**, so the path
`/workspace/apps/app/qaConfig/PHPStan/Rules/Foo.php` contains the substring `/app/` and
`is_production_source()` returns **True** for it. `should_skip()` only skips `tests/fixtures/` and
`vendor/`, so `qaConfig/` is *not* skipped. Net: **every `.php` under `apps/app/` is treated as
production source, including the QA-tooling dir `qaConfig/`.** That is what makes the handler fire on a
rule file at all.

### Bug B — the test-path resolver can't map a non-`src/` PSR-4 root to its test dir

`handlers/pre_tool_use/tdd_enforcement.py` → `_get_test_file_paths()` tries, in order:

1. **mirror** (`_map_src_to_tests_mirror`) — gated on `if _SRC_DIR in path_parts:` (i.e. only when the
   path contains a `src/` segment). A `qaConfig/PHPStan/Rules/` path has **no `src/` segment**, so this
   is skipped.
2. **current/unit** (`_map_src_to_test_path`) — same `_SRC_DIR in path_parts` gate → skipped.
3. **fallback** (`_map_fallback_test_path`) — `Path(source).parent.parent.parent / "tests" / testfile`
   → resolves to `qaConfig/tests/FooTest.php` (**lowercase** `tests`).
4. **collocated** → `qaConfig/PHPStan/Rules/FooTest.php`.
5. **`__tests__/`** → `qaConfig/PHPStan/Rules/__tests__/FooTest.php`.

None of these is the real dir `qaConfig/Tests/` (capital T; case-sensitive filesystem). The mirror
strategies — the only ones that could hit a PSR-4 `Tests/` dir — bail because they hard-require a
`src/` segment in the path.

### Bug C (gap) — `tdd_enforcement` ignores `exclude_paths`

The content blockers (`qa_suppression`, `security_antipattern`, `error_hiding_blocker`) call
`utils/path_exclusion.is_path_excluded(...)` with the union of their own `exclude_paths` **and** the
injected project-wide `daemon.exclude_paths` (`registry.py` injects `_project_exclude_paths` into every
handler). But `tdd_enforcement.py` **never references `_project_exclude_paths` or `is_path_excluded`** —
its `matches()` consults only the strategy's `should_skip`/`is_test_file`/`is_production_source`. So
**there is no configuration today that excludes a directory from TDD enforcement.** That is why this
can't be worked around in `.claude/hooks-daemon.yaml`.

---

## The "stan rules are hard to TDD" premise — gently corrected

They aren't, in this repo. The established, working pattern is:

- A pure **`*Policy`** class holding the decision logic → an exhaustive **unit test** (`TestCase`).
- A thin reflection **`*Rule`** adapter → a **`RuleTestCase`** test that runs the real rule against
  committed fixture classes and asserts the exact errors + lines.

`qaConfig/Tests/DeadNotScoredReasonRuleTest.php` is a full worked example (fixtures + `->analyse([...], [[msg, line], ...])`, red-half and green-half). So excluding rule files from TDD enforcement **forgoes
a TDD flow that genuinely works and is valuable** — it's a pragmatic trade, not a necessity. The
blocker is purely the path mapping (Bugs A/B), plus the no-escape gap (Bug C).

That said: excluding is defensible if the project accepts that the `qa-rules` phpunit suite + the
`bin/qa -t stan` authoring proof (the rule must land RED against the tree, then GREEN) are sufficient
enforcement that a rule ships with a test. That is a real, if softer, net.

---

## Fix options

### Option 1 — make `tdd_enforcement` honour `exclude_paths` (smallest; the user's instinct)

Mirror what the content blockers already do: in `tdd_enforcement.matches()`, short-circuit to
`False` when `is_path_excluded(file_path, merged_excludes, project_root=...)`, where `merged_excludes`
unions the injected `_project_exclude_paths` and an optional per-handler `exclude_paths` option (reuse
`utils/path_exclusion.merge_exclude_patterns`).

Then this project would add, in `.claude/hooks-daemon.yaml`:

```yaml
handlers:
  pre_tool_use:
    tdd_enforcement:
      options:
        exclude_paths:
          - "**/qaConfig/PHPStan/Rules/**"
```

- **Pro:** tiny, consistent with three sibling handlers, unblocks immediately, no fragile path logic.
- **Con:** turns TDD enforcement **off** for rule files (relies on convention + the phpunit `qa-rules`
  suite + the stan authoring proof to ensure a paired test exists). Acceptable given those nets.
- **Blast radius:** one handler; additive config; opt-in per project.

### Option 2 — fix the `/app/` false-match (Bug A) so `qaConfig/` isn't "production source"

Either drop `/app/` from `_SOURCE_DIRECTORIES` for a monorepo layout, or (better) have `should_skip`
treat `qaConfig/` (a QA-tooling dir) as non-source, or make the `/app/` match segment-exact and not fire
inside `apps/app/`. This stops the handler firing on `qaConfig/` at all.

- **Pro:** removes the spurious "production source" classification at its source.
- **Con:** `/app/` is a legitimate PHP source root for *some* projects; changing it risks regressions
  there. And on its own it still leaves Bug B for any *genuinely* source-resident custom-rule layout.

### Option 3 — configurable test-directory mapping (most correct; keeps enforcement ON)

Add a project-configurable mirror map so a repo can declare its non-`src/` test roots, e.g.:

```yaml
tdd_enforcement:
  options:
    test_path_map:
      - source_glob: "**/qaConfig/PHPStan/Rules/**"
        test_dir: "qaConfig/Tests"
```

The resolver adds the mapped `qaConfig/Tests/FooTest.php` as a candidate. This keeps TDD **enforced**
for rules (the correct outcome, since they're TDD-able) while fitting this repo's real layout.

- **Pro:** preserves enforcement; general; fixes Bug B properly.
- **Con:** largest change; new config surface + resolver logic + tests.

---

## Recommendation

- **Immediate unblock:** **Option 1** (honour `exclude_paths` in `tdd_enforcement`) + this project
  excludes `**/qaConfig/PHPStan/Rules/**`. Smallest upstream change, consistent with existing handlers,
  and the `qa-rules` phpunit suite + stan authoring proof keep rules honestly tested.
- **Also worth doing upstream:** **Option 2** (guard the `/app/` heuristic against `apps/app/`) — it's a
  latent false-positive for *any* monorepo with an `apps/app` root, affecting more than just rules.
- **Best long-term:** **Option 3** if the daemon wants to keep TDD enforced on custom rules (they are
  TDD-able) rather than exclude them.

All three are **upstream daemon changes** in `claude-code-hooks-daemon`; per the daemon's own policy
(`.claude/hooks-daemon/src/CLAUDE.md`) they must be filed and made upstream by a human, not patched in
this project's vendored copy.

---

## Reproduction

1. In this repo, first create a correct test at `apps/app/qaConfig/Tests/FooPolicyTest.php`.
2. `Write` a new source file `apps/app/qaConfig/PHPStan/Rules/FooPolicy.php`.
3. Observe the TDD block; note `qaConfig/Tests/` is absent from the searched locations.

## Evidence (files/lines)

- `strategies/tdd/php_strategy.py:15` — `_SOURCE_DIRECTORIES = ("/src/", "/app/")`; `:63-64`
  `is_production_source`; `:16,66-68` `should_skip` skips only `tests/fixtures/`, `vendor/`.
- `handlers/pre_tool_use/tdd_enforcement.py:191-236` `_get_test_file_paths`; `:213,219` mirror/current
  gated on `_SRC_DIR in path_parts`; `:295-306` fallback → `parent.parent.parent/tests/` (lowercase).
- `handlers/pre_tool_use/tdd_enforcement.py` — no reference to `_project_exclude_paths` /
  `is_path_excluded` (contrast: `qa_suppression.py`, `security_antipattern.py`,
  `error_hiding_blocker.py` all do).
- `registry.py:387` injects `_project_exclude_paths` into every handler (available but unused by TDD).
- `apps/app/qaConfig/phpunit.xml:73-75` — `qa-rules` suite scans only `../qaConfig/Tests`.
- `apps/app/qaConfig/Tests/DeadNotScoredReasonRuleTest.php` — proof custom rules ARE TDD'd here.

---

## Impact on Plan 00197 (this project)

Finding 1's permanent net (a PHPStan rule flagging any enum-backed column lacking `enumType:`) and
Finding 2's `CompaniesHouseNumber`-raw-string net are both **new custom rules** and are therefore
blocked. The column-conversion *fixes* (mapping `enumType:` + DB CHECK + real-DB filter tests) have **no
such friction** (they edit existing `src/` files and add tests under `tests/`), so Plan 00197 proceeds
fix-first; the permanent nets land once the daemon is fixed (Option 1/3) or a decision is taken to
author them at a hook-accepted location.

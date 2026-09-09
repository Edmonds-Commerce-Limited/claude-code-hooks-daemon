# Code Review: v3.63.0 release gate — strategies, utils, tool_report, block_report, constants, rule_explain

Reviewer: code-reviewer (Opus 5). Scope assigned by team-lead as RELEASING.md Step 10.

## Summary

The slice is in good shape. The large mechanical change (acceptance tests gain a
declared `ToolPayload`) is applied consistently and is verified by unconditional
contract tests that already exist and pass. The substantive new utility modules
are well designed, individually tested, and free of the antipatterns this review
looks for. No blocking defect was found.

Seven non-blocking findings are recorded below, each with a concrete
remediation. One of them (Finding 1) is a measured resource-consumption edge in
a security handler's hot path and is the only one worth scheduling promptly.

**Reviewed**

| Item | Count |
| ---- | ----- |
| Files changed in slice | 89 |
| Lines changed | 2428 added, 512 removed |
| Findings at confidence >= 70 | 7 |
| Blockers | 0 |

**Diff command used**

```
git diff v3.62.1..HEAD -- \
  src/claude_code_hooks_daemon/strategies/ \
  src/claude_code_hooks_daemon/utils/ \
  src/claude_code_hooks_daemon/tool_report/ \
  src/claude_code_hooks_daemon/block_report/ \
  src/claude_code_hooks_daemon/constants/ \
  src/claude_code_hooks_daemon/rule_explain/
```

## Verification performed

All commands run from `/workspace` with `.venv/bin/python`.

| Check | Result |
| ----- | ------ |
| `ruff check` over the six packages | clean |
| `mypy` over utils, strategies, block_report, tool_report | clean, 148 files |
| `pytest tests/unit/{utils,strategies,block_report,tool_report,constants,rule_explain}` | 2962 passed |
| `pytest tests/integration/test_acceptance_{contract,tool_payload_agrees_with_prose,test_coverage}.py` | 43 passed |
| `bin/hooks-daemon generate-playbook --format json` | 293 blocks, exit 0 |
| `bin/hooks-daemon block-report --no-write` | exit 0, 5.8 s, no stderr |

Test files exist for every changed or added module in the slice. Confirmed by
checking `tests/unit/utils/test_<module>.py` for all thirteen touched utils
modules, plus `tests/unit/strategies/security/test_secret_strategy.py`,
`tests/unit/strategies/lint/test_common.py` and
`tests/unit/strategies/lint/test_lint_commands_are_runnable_as_declared.py`.

## The mechanical change, verified

Every strategy's `get_acceptance_tests()` now states a `ToolPayload` once and
renders `command=probe.as_instruction()` from it, replacing a hand-written
English sentence that could drift from the values beside it. The pattern is
identical across the comments, error_hiding, lint, qa_suppression, security and
tdd families.

Consistency was checked mechanically rather than by reading 60 near-identical
hunks. Of the 69 strategy files declaring an `AcceptanceTest`, 61 carry a
`tool_payload` and the count of `tool_payload=` occurrences equals the count of
`AcceptanceTest(` occurrences in every one of them. The eight exceptions are all
`pipe_blocker` strategies, and Finding 5 explains why: their tests are
unreachable, so the conversion correctly had nothing to do there.

The playbook confirms the change had its intended effect end to end:

| Handler | Blocks in playbook | Carrying a payload |
| ------- | ------------------ | ------------------ |
| LintOnEditHandler | 23 | 23 |
| CommentChangelogHandler | 13 | 13 |
| SecurityAntipatternHandler | 13 | 13 |
| QaSuppressionHandler | 13 | 13 |
| TddEnforcementHandler | 11 | 11 |
| ErrorHidingBlockerHandler | 10 | 10 |

`tests/integration/test_acceptance_contract.py::TestEveryBlockingTestDeclaresAWayToDriveIt`
is unconditional with no allowlist and passes, so a future strategy test that
omits a driver fails on the commit that adds it.

## Findings

### 1. A wide bracket range is materialised before the expansion cap applies (NOTE, confidence 90)

**Location:** `src/claude_code_hooks_daemon/utils/secret_file_matching.py:434-462`
(`_bracket_expression_members`), with the cap at
`src/claude_code_hooks_daemon/utils/secret_file_matching.py:488`.

**Problem**

`_MAX_BRACKET_EXPANSIONS` (64) bounds the combinatorial product across a token's
bracket expressions, and the code is careful to check it incrementally so a
runaway product returns the token unexpanded. But the check runs on the value
`_bracket_expression_members` has *already returned*. That function expands a
range eagerly:

```python
members.extend(chr(point) for point in range(ord(start), ord(end) + 1))
```

For a token carrying a wide literal range, the full member list plus the
`dict.fromkeys` deduplication are built and discarded before the cap ever sees
them.

**Evidence**

Measured with the probe saved beside this report
(`untracked/agent-reports/260909-review-strategies-bracket-probe.py`, output in
`untracked/agent-reports/260909-review-strategies-bracket-probe-output.txt`):

| Input | Time | Peak memory |
| ----- | ---- | ----------- |
| `cat f[0-9].txt` | 1.35 ms | 0.0 MB |
| `cat file[CJK-range].txt` (literal CJK chars) | 9.54 ms | 2.4 MB |
| `cat f[NUL-U+10FFFF].txt` (literal chars) | 650 ms | 144.5 MB |
| 20 wide-range tokens in one Write payload | 13.5 s | 144.5 MB |

**Why it matters**

`find_protected_mention` is called on Write/Edit *content* by
`secret_file_guard` (`src/claude_code_hooks_daemon/handlers/pre_tool_use/secret_file_guard.py:270`),
which is a PreToolUse handler on the dispatch hot path. Cost is linear in the
number of such tokens, so a file with twenty of them stalls a hook for over
thirteen seconds.

This is availability only, not a matching bypass: the over-cap path returns
`[token]` and the token is judged exactly as before, which fails closed. It also
needs *literal* wide characters — a Python-source escape sequence tokenises as
ordinary backslash text and parses cheaply, which is why the realistic
accidental trigger (a CJK class) costs only 10 ms.

**Suggested fix**

Reject a range wider than the cap before materialising it, inside
`_bracket_expression_members`:

```python
if ord(end) < ord(start) or ord(end) - ord(start) >= _MAX_BRACKET_EXPANSIONS:
    return None
```

Returning `None` keeps the existing fail-closed semantics (the token is left
unexpanded) and makes the guarantee uniform rather than product-only.

---

### 2. Kotlin lint strategy docstring contradicts its own new command (NOTE, confidence 95)

**Location:** `src/claude_code_hooks_daemon/strategies/lint/kotlin_strategy.py:28`

**Problem**

The class docstring still reads `Default: kotlinc -script (compilation check)`.
Line 19 of the same file removed `-script` in this release, and the constant's
own comment explains at length that `-script` expects a `.kts` file while the
strategy is registered for `.kt` only, so the old command rejected every file it
was given. The docstring now documents the exact defect that was fixed.

**Why it matters**

A reader who trusts the class docstring over the constant will reintroduce the
bug. `test_lint_commands_are_runnable_as_declared.py` guards the constant, not
the prose.

**Suggested fix**

Change line 28 to `Default: kotlinc (compilation check, class files discarded)`.

---

### 3. Kotlin lint writes compiler output to a fixed path in the shared temp directory (NOTE, confidence 75)

**Location:** `src/claude_code_hooks_daemon/strategies/lint/kotlin_strategy.py:19`,
alongside the pre-existing `src/claude_code_hooks_daemon/strategies/lint/rust_strategy.py:21`.

**Problem**

```python
_DEFAULT_LINT_COMMAND = "kotlinc -nowarn -d /tmp/claude-hooks-daemon-kotlin-lint {file}"
```

The destination is a fixed, predictable name in a world-writable directory. On a
shared host another user can pre-create that path as a symlink and steer compiler
output through it, which is the classic insecure-temporary-directory shape. Two
concurrent lint runs also share the directory, and the path is not portable off
POSIX.

The Rust sibling already had this, so the new line follows an existing pattern
rather than inventing one. That is exactly why it is worth naming now: there are
two copies, so it should become one helper before there is a third.

**Why it matters**

Low likelihood on a single-user dev box, but it is a file-write primitive handed
to an attacker on a multi-user one, and it is cheap to remove.

**Suggested fix**

Give both strategies one shared destination derived from
`tempfile.mkdtemp()` (unpredictable, per-process) or from the daemon's untracked
directory, and reference it from a single constant in
`src/claude_code_hooks_daemon/strategies/lint/common.py`.

---

### 4. `cron_cadence` hand-rolls the temp name that `temp_names` was added to own (NOTE, confidence 85)

**Location:** `src/claude_code_hooks_daemon/utils/cron_cadence.py`, in
`write_cadence`:

```python
tmp_path = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
```

**Problem**

This release adds `src/claude_code_hooks_daemon/utils/temp_names.py`, whose
module docstring states its whole purpose: "the count of hand-rolled copies grew
from four to nine before Plan 00159 gave them this helper." The sibling module
added in the same release, `utils/model_downgrade_signal.py`, uses
`unique_temp_path`. `cron_cadence` does not, and becomes a tenth copy.

**Why it matters**

The helper exists to make this spelling fixable in one place. A new hand-rolled
copy landing in the same release that introduces the helper is how the count
starts climbing again. The names also differ in attribution: `unique_temp_path`
carries pid and thread ident, so a crashed writer's leftover is traceable, while
the uuid form is anonymous.

**Suggested fix**

```python
tmp_path = unique_temp_path(path)
```

Keep the existing `os.open(..., O_WRONLY | O_CREAT | O_EXCL, FileMode.PRIVATE_FILE)`
— the restrictive mode is a good reason to keep the open, but not to hand-roll
the name.

---

### 5. Eight `pipe_blocker` strategy `get_acceptance_tests()` methods are dead code (NOTE, confidence 90)

**Location:** `src/claude_code_hooks_daemon/strategies/pipe_blocker/` —
`go_strategy.py`, `java_strategy.py`, `javascript_strategy.py`,
`python_strategy.py`, `ruby_strategy.py`, `rust_strategy.py`,
`shell_strategy.py`, `universal_strategy.py` (one `AcceptanceTest` each).

**Problem**

`PipeBlockerHandler.get_acceptance_tests()`
(`src/claude_code_hooks_daemon/handlers/pre_tool_use/pipe_blocker.py:1238`)
declares its own ten tests and never aggregates the strategies', unlike every
other strategy family. Verified against the generated playbook: `PipeBlockerHandler`
contributes exactly 10 blocks, none of which is a strategy title such as
"Python: pytest piped to tail".

The methods are therefore never called outside the strategies' own unit tests,
which assert only that the returned list is non-empty.

**Why it matters**

This is pre-existing, not introduced here, but it belongs in this review because
it is the reason these eight files were the only strategy files the release-wide
`ToolPayload` conversion skipped. Left alone, they read as an inconsistency in
the conversion rather than as unreachable code, and the next person to run a
consistency sweep will spend the same time rediscovering it.

**Suggested fix**

Either delete the eight methods, or aggregate them in
`PipeBlockerHandler.get_acceptance_tests()` the way the lint and security
handlers aggregate theirs, and give each a `dispatch_as_bash=True` declaration
so the contract test can drive it.

---

### 6. The uncached rule-index branch is expensive and logs a traceback per handler (NOTE, confidence 70, latent)

**Location:** `src/claude_code_hooks_daemon/block_report/fingerprints.py:183-193`

**Problem**

`_rule_id_to_config_key()` now serves an uncached `_build_rule_index()` whenever
`ProjectContext` is not initialised. The reasoning is sound: an index built then
is partial, and memoising it would mis-attribute every rule of the handlers that
dropped out. But `attribute_deny` is called once per deny event
(`src/claude_code_hooks_daemon/block_report/analyser.py:174`), so on that branch
the whole handler package is walked per event.

**Evidence**

Measured on this checkout:

| Measurement | Value |
| ----------- | ----- |
| `attribute_deny` with `ProjectContext` uninitialised | 4.3 ms per call |
| Rule IDs discovered, uninitialised | 79 |
| Rule IDs discovered, initialised | 90 |
| Rule IDs a partial index cannot attribute | 11 |

Each uncached build also logs a full traceback for every handler whose
`__init__` reads `ProjectContext` (22 calls produced 120 KB of tracebacks).

**Why it matters — and why this is not a blocker**

No current caller reaches it. `block_report` is used only by
`src/claude_code_hooks_daemon/daemon/cli.py`, and I instrumented
`_build_rule_index` while running `block-report` end to end: it is called
**once**, with `ProjectContext` already initialised. The real run took 5.8 s and
produced no stderr. So this is latent, and the guard is correctly defensive
rather than currently wrong.

The reason to record it is the second half of that table: a future caller
landing on the uncached branch does not merely run slowly, it silently
under-attributes 11 of 90 rule IDs into `unattributed_denies`, which reads as a
data conclusion rather than a missing precondition.

**Suggested fix**

Log once at WARNING when the uncached branch is taken, naming the missing
precondition, so a future caller's degraded attribution is visible rather than
inferred from a count.

---

### 7. Eighty redundant `str()` wrappers around `scratch_path()` (NOTE, confidence 95)

**Location:** throughout the converted strategy files, e.g.
`src/claude_code_hooks_daemon/strategies/lint/python_strategy.py` and
`src/claude_code_hooks_daemon/strategies/security/secret_strategy.py`.

**Problem**

`scratch_path` is annotated to return `str` and returns a joined string
(`src/claude_code_hooks_daemon/utils/scratch_dir.py`), so wrapping it in `str()`
is a no-op. The added lines carry 76 single-line occurrences plus 4 wrapped
across lines.

**Why it matters**

Purely noise, but it is 80 instances of a pattern that suggests to a reader that
`scratch_path` returns a `Path`, which is the opposite of what it does.

**Suggested fix**

Drop the wrapper. A one-file-per-agent bulk edit, no behaviour change; mypy
already passes either way.

---

## Observations that did not reach the reporting threshold

- **Import spelling drift.** Some converted strategies import `ToolName` from
  `claude_code_hooks_daemon.constants`, others from
  `claude_code_hooks_daemon.constants.tools`. Both resolve to the same object.
  Cosmetic only.
- **Generated-forwarder interpolation.** `install/forwarder_generator.py`
  interpolates `EventIDMeta.daemon_down_stdout` into a generated shell `echo`
  without escaping. The only value is the literal warning text set at
  `src/claude_code_hooks_daemon/constants/events.py:310`, which is
  developer-controlled and carries no shell metacharacter, so nothing is
  exploitable today. Worth remembering if that field ever becomes
  project-configurable.
- **Priority 33 is used twice** (`MODEL_DOWNGRADE_RECORDER` and `COMMENT_SIZE`)
  but on different events (PostToolUse and PreToolUse), so the chains never
  compare them. Not a collision.
- **`resolve_configured_patterns` cache.** It sets its resolved flag before
  attempting resolution, so a first call made before `ProjectContext` is
  initialised would pin the shipped defaults for the process lifetime. All four
  callers are handlers or the daemon server, which run post-initialisation, and
  the function is unchanged in this release. Not reachable, not in scope.

## Positive observations

- **`matches_skip_path` closes a real fail-open.**
  `src/claude_code_hooks_daemon/strategies/lint/common.py:37-46` replaces a bare
  substring test with a segment-boundary scan, so a `build/` pattern no longer
  matches inside `rebuild/`. The loop is correct: the search start strictly
  increases, so it terminates, and every occurrence is examined rather than only
  the first.
- **`test_lint_commands_are_runnable_as_declared.py` is real testing, not
  theatre.** It asserts a property (no shell metacharacter in a command run
  without a shell) across every registered strategy, and carries two explicit
  vacuity guards — one that the check fails on the shape it exists to reject,
  one that the registry is non-empty. It caught two genuine defects (the Kotlin
  flag pair and the Rust `clippy-driver` crate framing) that a box without the
  toolchain had been masking.
- **`option_coercion` and `cron_cadence` both handle the bool-is-an-int trap
  deliberately and document why.** `coerce_int_option` rejects `bool` before the
  int test; `read_cadence` rejects a JSON true rather than coercing it to 1.
- **`path_predicates` makes the right call on the fallback.** Requiring
  `unreadable_means` keyword-only with no default, and justifying it with three
  call sites that provably disagree, is better engineering than a canonical
  default that would silently invert a DENY guard.
- **The `secret_file_matching` bracket-expansion work fails closed throughout.**
  Negated classes, POSIX named classes, inverted ranges and over-cap products
  all return the token unexpanded, and the unexpanded literal spelling is still
  matched alongside the expansions.
- **No SOLID violations found.** No conditional chains on language or type names
  anywhere in the slice; the strategy-registry pattern is used consistently.
- **Clean of the usual smells.** No TODO, FIXME, HACK or XXX in the added lines;
  no debug prints; no QA suppressions; no shell-enabled subprocess calls; no
  hardcoded credentials outside deliberate acceptance fixtures using AWS's own
  documentation example key.

## Verdict

**APPROVE.** No critical or blocking issue. Ship v3.63.0. Finding 1 is the only
one worth scheduling promptly; the remaining six are ordinary follow-up work.

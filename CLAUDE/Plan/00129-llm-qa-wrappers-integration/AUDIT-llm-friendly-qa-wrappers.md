# Audit: `edmondscommerce/llm-friendly-qa-wrappers`

## Executive Summary

`llm-friendly-qa-wrappers` is an early-stage (v0.1.0, single tag, 0 stars, 0 issues/PRs, no CI, no LICENSE file) collection of 14 thin wrapper scripts that run a QA tool, print a 1-5 line terse summary, and dump full results to a temp `*.json` file whose path is emitted as `(details: /tmp/<tool>-<hex>.json)`. The core idea is sound and the terse-output + temp-file contract is consistent and machine-parseable across all 14 wrappers — that part genuinely works (verified live with the ShellCheck wrapper end-to-end). However, the repo is **not yet safe to adopt as a major dependency**: there is no LICENSE file despite an MIT claim, no CI and no real test execution evidence, two mutually incompatible dependency-resolution models (Node/PHP run a *bundled* tool from the wrapper's own `node_modules`/`vendor`; Python/Bash run the tool from the caller's `PATH`), per-wrapper installs with no install entrypoint, every tool emits a **completely different JSON shape** (by design, but a real cost for a generic redirect handler), there is no machine-readable "raw command → wrapper invocation" mapping, several wrappers have brittle regex/text parsing and at least two real correctness bugs (PHPStan fail-branch under-counts config errors; tsc invoked per-file ignoring `tsconfig` project semantics), and the project's own plan index and docs are already stale.

**Overall readiness verdict: NOT READY (ADOPT WITH FIXES, after upstream changes).** A small subset (ShellCheck, Ruff, MyPy, ESLint when its deps are bundled) is usable today behind a defensive handler, but the repo as-published cannot be a load-bearing dependency without the fixes in §9.

---

## 1. Inventory & Completeness

14 wrappers exist on disk and all 14 are advertised in the README. No advertised-but-missing or present-but-undocumented wrappers. The four-language split (Node 6, PHP 3, Bash 2, Python 3) matches the README and `RELEASES/v0.1.0.md`.

| Lang   | Tool         | Wrapper file                                 | schema.json | examples/ pass+fail | per-wrapper README | dep manifest                                          |
| ------ | ------------ | -------------------------------------------- | :---------: | :-----------------: | :----------------: | ----------------------------------------------------- |
| Node   | ESLint       | `wrappers/nodejs/eslint/llm-eslint.js`       |     ✅      |         ✅          |         ❌         | `package.json` + `package-lock.json`                  |
| Node   | Prettier     | `llm-prettier.js`                            |     ✅      |         ✅          |         ❌         | `package.json` + lock                                 |
| Node   | Jest         | `llm-jest.js`                                |     ✅      |         ✅          |         ❌         | `package.json` + lock                                 |
| Node   | tsc          | `llm-tsc.js`                                 |     ✅      |         ✅          |         ❌         | `package.json` + lock                                 |
| Node   | Vitest       | `llm-vitest.js`                              |     ✅      |         ✅          |         ❌         | `package.json` + lock                                 |
| Node   | Biome        | `llm-biome.js`                               |     ✅      |         ✅          |         ❌         | `package.json` + lock                                 |
| PHP    | PHPStan      | `wrappers/php/phpstan/llm-phpstan.php`       |     ✅      |         ✅          |         ❌         | `composer.json` + `composer.lock`                     |
| PHP    | PHP-CS-Fixer | `llm-php-cs-fixer.php`                       |     ✅      |         ✅          |         ❌         | `composer.json` + lock                                |
| PHP    | PHPUnit      | `llm-phpunit.php`                            |     ✅      |         ✅          |         ❌         | `composer.json` + lock                                |
| Bash   | ShellCheck   | `wrappers/bash/shellcheck/llm-shellcheck.py` |     ✅      |         ✅          |         ❌         | `pyproject.toml` (no deps — uses system `shellcheck`) |
| Bash   | shfmt        | `llm-shfmt.py`                               |     ✅      |         ✅          |         ❌         | `pyproject.toml` (no deps — system `shfmt`)           |
| Python | Ruff         | `wrappers/python/ruff/llm-ruff.py`           |     ✅      |         ✅          |         ❌         | `pyproject.toml` (`ruff>=0.4.0`)                      |
| Python | pytest       | `llm-pytest.py`                              |     ✅      |         ✅          |         ❌         | `pyproject.toml` (`pytest>=7.0.0`)                    |
| Python | MyPy         | `llm-mypy.py`                                |     ✅      |         ✅          |         ❌         | `pyproject.toml` (mypy dep declared)                  |

**Completeness gaps:**

- **Per-wrapper `README.md` is universally MISSING.** Both `MISSION.md` (lines 103-126) and `CONTRIBUTING.md` (lines 30-36, 150-178, PR checklist line 195) mandate a `README.md` in every wrapper directory. The repo top-level README (line 110) also lists it in the per-directory structure. Zero of 14 wrappers have one. The documented contract is already violated by the project itself.
- **No `LICENSE` file** (verified absent) despite `README.md` line 130 and `package.json` `"license": "MIT"`. See §8(d).
- Naming convention `llm-{tool}.{ext}` is followed correctly by all 14.

---

## 2. Consistency

**Naming / output framing — consistent.** All wrappers:

- Are named `llm-{tool}.{ext}` ✅
- Emit the success line `✅ {Tool}: {summary} (details: {path})` ✅
- Emit the failure block `❌ {Tool}: {summary}` + up to 3 indented `   - ...` detail lines + `   (details: {path})` ✅
- Use exit codes `0` pass / `1` fail / `2` error ✅ (verified for eslint no-args→2, eslint missing-deps→2, shellcheck pass→0, shellcheck fail→1)
- Write JSON to a temp file ✅

**JSON shape — wildly inconsistent (by stated design, but real cost).** There is no shared envelope. Three families, and even within a family the fields differ:

- *Native passthrough* (no envelope at all): ESLint = **bare top-level array**; Jest/Vitest = object with `success/numTotalTests/...`; PHPStan = object with `totals/files/errors`; PHP-CS-Fixer = object with `about/files/time/memory`; Biome = object with `summary/diagnostics`.
- *Custom envelope* (`tool/timestamp/command/summary/results`): Prettier, tsc, shfmt — but tsc uses `summary.total_errors`/`diagnostics` while prettier/shfmt use `summary.error_count`/`results`.
- *Custom envelope, inconsistent fields*: Ruff and MyPy drop `version` and `exit_code`; pytest drops `exit_code`, `command`, and `version` (`required: tool/timestamp/summary/tests`); ShellCheck includes `exit_code` + `version`.

Net effect for a redirect handler: **a caller cannot write one `jq` query for "did it pass".** `eslint` needs `[.[].errorCount] | add`, `phpstan` needs `.totals.file_errors`, `mypy` needs `.summary.error_count`, `jest` needs `.success`, `ruff` needs `.summary.error_count`, prettier needs `.summary.error_count`. The CONTRIBUTING "semantic keys" guidance (`error_count` not `errors`) is **not** followed by the native-passthrough wrappers (ESLint `errorCount`, PHPStan `file_errors`), because they pass the tool's raw shape through. The terse terminal line is the only uniform signal.

---

## 3. Code Quality & Correctness

General quality is decent for a v0.1: top-level `try/except` (or PHP equivalent) with exit-2 fallback, no obvious shell-injection (Node uses `execFileSync`/`spawnSync` with arg arrays; PHP uses `proc_open` with array `$cmd`; Python uses `subprocess.run` with list args — no `shell=True`, no string interpolation into a shell). Specific findings:

**Bugs / correctness:**

- **PHPStan fail branch under-reports config errors.** `llm-phpstan.php`: the pass check uses `$totalIssues = $totalErrors + $fileErrors` (line 80-82), but the failure line prints only `{$fileErrors} errors found` (line 86). A PHPStan run with a config/global error (`totals.errors > 0`, `totals.file_errors == 0`) will exit 1 with the message **"❌ PHPStan: 0 errors found"** and an empty detail list (the `files` loop is empty). Misleading.
- **tsc ignores `tsconfig` project semantics.** `llm-tsc.js` collects individual `.ts` files (`collectTsFiles`, lines 29-39) and passes them as explicit args to `tsc --noEmit ... file1 file2` (lines 67-74). Passing files explicitly to `tsc` **bypasses the project's `tsconfig.json`** `compilerOptions`/`include`/`paths`. Type-checking results will differ from (and be less correct than) a normal `tsc -p tsconfig.json` run. This is a fundamental modeling error for a type-checker wrapper, not a cosmetic bug.
- **shfmt diff parsing is lossy.** `llm-shfmt.py` `parse_diff` (lines 38-71) only extracts hunk *line ranges* (`@@ -a,b +c,d @@`), discarding the actual `+/-` content. The committed `examples/fail.json` shows `original_count: 12, formatted_count: 12` for a real formatting diff — i.e. the JSON tells a consumer *that* a file is unformatted but gives almost no actionable detail. For an LLM "fix the formatting" use case this is near-useless; `shfmt -d` raw diff would be more useful than this structured-but-empty hunk list.
- **pytest parser is brittle regex-over-stdout.** `llm-pytest.py` parses `-v` console output with `re.match(r"^(.+?)::(\S+)\s+(PASSED|FAILED|ERROR|SKIPPED)")` and a hand-rolled FAILURES-section state machine (lines 27-69). This breaks on: parametrized test IDs containing `::`, xfail/xpass statuses (not in the enum), pytest plugins that alter line format, non-default verbosity, and progress/percentage suffixes. There is a community-standard `pytest-json-report` plugin the project chose not to use; the result is the least robust wrapper in the set. (The README/MISSION even cite Prettier as the canonical "no native JSON" case; pytest is the more dangerous one.)
- **tsc per-file run also means `filesWithErrors`/version probe spawn `tsc` twice** (lines 67, 111) — minor.

**Error handling when the tool is absent — inconsistent UX:**

- PHP wrappers check `file_exists($bin)` and print a friendly `Run composer install first.` (phpstan line 20-23, etc.). Good.
- **Node wrappers do NOT.** With deps not installed, `llm-eslint.js` against a target produces a raw `❌ ESLint: Execution error - spawnSync .../node_modules/.bin/eslint ENOENT` (verified live, exit 2). No "run npm install" guidance. A redirect handler firing this on a project that hasn't installed the wrapper's deps yields a cryptic message.
- Python/Bash wrappers catch `FileNotFoundError` with a friendly `Install with: pip install ruff` / `shellcheck not found in PATH`. Good — but see the dependency-model split below.

**Swallowed errors (minor):** several `except Exception: pass` / `catch {}` blocks for *version probing* (shellcheck `get_shellcheck_version` lines 41-42; tsc version `catch {}` line 114) — acceptable since they fall back to `"unknown"`, but they are exactly the silent-suppression pattern this consuming project blocks in its own code.

**"Native JSON first" — mostly honoured.** ESLint, Jest, Vitest, Biome, PHPStan, PHP-CS-Fixer, ShellCheck, Ruff, MyPy use the tool's JSON. Prettier (programmatic `prettier.check`), tsc (regex over diagnostics), PHPUnit (JUnit XML→JSON), shfmt (diff→JSON), pytest (stdout regex) are the custom cases. Four of those five custom parsers (tsc, shfmt, pytest, and prettier's directory-walk) are the riskiest code in the repo.

**JSON-buffer robustness:** Jest/Vitest do `indexOf("{")`/`slice` to skip preamble (jest line 44-48, vitest 51-55); Biome does `indexOf("{")` + `lastIndexOf("}")` (lines 44-50). These are heuristic and will mis-slice if a tool ever emits a brace inside preamble text. `maxBuffer: 50MB` is set on the Node spawns (reasonable).

---

## 4. Temp-file / Output Contract (CRITICAL for redirect use case)

**Path generation differs by language:**

- Node: `join(tmpdir(), "<tool>-<randomBytes(4).hex>.json")` — 4 random bytes = **32 bits of entropy**, file written but **not opened atomically** (predictable-ish, collision-prone under high concurrency, ~1-in-65k collision after ~65k runs by birthday bound; low but non-zero, and no O_EXCL).
- PHP: `tempnam(sys_get_temp_dir(), '<tool>-') . '.json'` — `tempnam` creates a unique 0-byte file (good, atomic), but appending `.json` creates a **second** path; the original extension-less `tempnam` file is **leaked** every run (orphan temp files accumulate). PHPUnit additionally creates a JUnit `.xml` tempfile and `@unlink`s it (line 71) — but also leaks the extension-less `phpunit-junit-XXXX` from its own `tempnam` (line 25).
- Python: `tempfile.NamedTemporaryFile(prefix=..., suffix=".json", delete=False)` — atomic and unique (good), but `delete=False` means **the file is never cleaned up** by design.

**Communication of the path — consistent and parseable.** Every wrapper emits `(details: <abs-path>.json)` on the success line and as the last failure line. The acceptance harness extracts it with `re.search(r"\(details:\s+(/\S+\.json)\)", output)` (`run_acceptance.py` line 58). This is the one reliable, uniform machine-readable contract in the repo. **Caveat:** the regex requires the path to start with `/` (POSIX absolute). On Windows `tmpdir()` this breaks; for our Linux/container use case it's fine. A redirect handler can rely on `(details: <path>)` — but should parse it itself rather than depend on the harness.

**Risks for our handler:**

- **Leftover temp files**: PHP `tempnam`-orphans + every wrapper's `delete=False`/no-cleanup means `/tmp` fills over a long session. We'd want to GC `/tmp/{eslint,ruff,...}-*.json` ourselves.
- **Path is non-deterministic** (random/`tempnam`) — the handler **must capture stdout and parse the `(details: ...)` token**; it cannot predict the path. That's workable but means the handler can't pre-create or pin the location.
- **No JSON-path on stderr-only error exits**: on exit 2 (no targets, missing binary) there is no `(details:)` line at all — the handler must treat "no details path" as "tool errored, fall back to raw".

---

## 5. Installation & Dependency Surface

**Heavy and fragmented. No single install entrypoint** (verified: no `Makefile`, no top-level install script, no `scripts` in root `package.json`). Adoption today means, per wrapper you want:

- Node (6 tools): `cd wrappers/nodejs/<tool> && npm install` each (each has its own `package.json`+lockfile; `node_modules/` is gitignored). 6 separate installs.
- PHP (3 tools): `cd wrappers/php/<tool> && composer install` each (`vendor/` gitignored). 3 separate installs.
- Python (3 tools) + Bash (2 tools): tools expected on `PATH` (`pip install ruff pytest mypy`, system `shellcheck`/`shfmt`). The `pyproject.toml`s declare deps but **nothing installs them into an isolated env** — the wrappers call bare `ruff`/`mypy`/`python3 -m pytest`/`shellcheck`/`shfmt` from PATH.

**Two incompatible dependency models — the single biggest adoption hazard:**

- Node & PHP wrappers run the tool from the **wrapper's own** `node_modules/.bin` / `vendor/bin` (e.g. `llm-eslint.js` line 26 `join(wrapperDir, "node_modules", ".bin", "eslint")`). They use the **bundled** tool version, NOT the target project's. So linting "the project" actually uses the wrapper's ESLint 9 + the *project's* config — which can mismatch the project's installed ESLint/plugins and fail to resolve `eslint.config.js` plugin imports.
- Python & Bash wrappers run the tool from **PATH** (the ambient/project env). Opposite model.

This split means there is no coherent story for "which tool version runs." For our redirect use case this is serious: an agent running `eslint src/` in a project expects the *project's* ESLint; redirecting to `llm-eslint.js` silently swaps in the wrapper's bundled ESLint and may produce different (or broken, on plugin resolution) results.

**Runtimes required:** Node ≥20, PHP ≥8.2, Python ≥3.11 (declared in manifests; enforced only by `engines`/`requires-python` metadata, not checked at runtime). The acceptance harness additionally needs the `jsonschema` Python package (imported unconditionally, `run_acceptance.py` line 28) — undeclared in any manifest.

**Vendoring/pinning:** lockfiles ARE committed (`package-lock.json`, `composer.lock`) so installs are reproducible. But there is no published npm/composer/pip package and no version beyond the git tag `v0.1.0`; pinning = git submodule/subtree at a commit, then running 9+ installs.

---

## 6. Testing

- **`acceptance-tests/run_acceptance.py`** is the only test artifact. It takes **one** `<wrapper_dir> <fixture_dir>` pair (lines 211-217) and checks: exit code (0/1/2), presence of ✅/❌ marker, terseness (pass=1 line, fail=2-5 lines), a `(details:)` path that exists, and **JSON validates against that wrapper's `schema.json`** (it imports `jsonschema`). The schema-validation step is genuinely valuable.
- **No aggregate runner**: nothing loops over all 14 wrappers. You must invoke the harness 14 times by hand.
- **No CI**: no `.github/` directory at all. Nothing runs these tests automatically. There is zero evidence any wrapper passes its own acceptance test in a clean environment.
- **Fixtures exist** for all tools (`test-fixtures/<lang>/<tool>/{pass,fail}/src/...`), and they look real (e.g. `eslint/fail/src/messy.js` has `var`+`==`+unused vars). Some PHP fixtures commit caches (`.php-cs-fixer.cache`, `.phpunit.result.cache`) which is sloppy.
- **Live spot-check (this audit):** I ran `llm-shellcheck.py` against its pass and fail fixtures — both behaved exactly per spec (exit 0/1, correct terse output, valid `(details:)` temp JSON). So at least one wrapper demonstrably works. I could not run eslint/ruff/etc. here without installing their deps; eslint with deps absent failed with the raw ENOENT noted in §3.

**Confidence: LOW-to-MODERATE.** The harness is reasonable but unautomated and unproven at scale; the custom-parser wrappers (tsc/shfmt/pytest) have only a single happy-path fixture each, which won't exercise the brittle branches.

---

## 7. Stability & Maturity Signals

- **Version:** single tag `v0.1.0`, `0.1.x` in every manifest. Pre-1.0 — API explicitly unstable by SemVer convention.
- **History:** initial release 2026-02-17, repo last pushed 2026-02-18. ~30 commits, mostly "Plan 000NN: Add X wrapper" with duplicate/merge commits (several `Add Jest wrapper` repeats) indicating messy branch hygiene.
- **GitHub:** **0 stars, 0 open or closed issues, 0 PRs** (queried both `--state all`). No external usage, no community, no battle-testing. Public repo.
- **Docs drift already present:** `CLAUDE/Plan/README.md` lists all 5 plans as "Not Started" and "Completed Plans: None yet" — *after* shipping all of them. Per-wrapper READMEs mandated but absent. LICENSE claimed but absent. CHANGELOG has one entry.
- **No deprecation/stability policy, no schema-versioning** (schemas have no `version` field of their own; if a tool changes its native JSON, the wrapper's `schema.json` and our `jq` queries silently break).

**This is a brand-new, single-author, unproven repo.** Treat the API and JSON shapes as liable to change.

---

## 8. Gaps & Risks for Our Use Case

**(a) Which raw tools could a handler safely redirect today?**

- *Reasonable now (behind a defensive handler):* **ShellCheck** (system binary, verified working, clean envelope), **Ruff** and **MyPy** (PATH-based, native JSON, simple envelopes, friendly missing-tool errors). These match the "agent runs the project's tool from PATH" mental model.
- *Risky / needs work:* **ESLint, Jest, Vitest, Biome, Prettier, tsc** (bundled-deps model swaps tool version vs. the project; tsc additionally mis-models projects; Node missing-deps error is cryptic). **PHPStan/PHP-CS-Fixer/PHPUnit** (bundled-deps model; PHPStan fail-branch bug; PHPUnit JUnit-XML round-trip). **pytest/shfmt** (brittle parsers, lossy output).
- *Net:* only ~3-4 of 14 are dependable as-is.

**(b) What breaks if the agent's project doesn't have the wrapper installed?**

- Node/PHP: wrapper exits 2 — Node with a *cryptic* `spawnSync ENOENT`, PHP with a friendly "run composer install". Either way the agent's QA "succeeds at nothing" unless our handler detects exit 2 + missing-deps and falls back to the raw tool.
- Python/Bash: if the wrapper script itself isn't vendored into the project, there's nothing to redirect *to*. The wrappers are **not** installed as global commands; they're files inside this repo. Our handler would have to ship/locate the wrapper script paths. There is no `llm-eslint` on PATH anywhere.

**(c) Machine-readable "raw command X → wrapper invocation"?** **None exists.** No manifest maps `eslint` → `node wrappers/nodejs/eslint/llm-eslint.js`. A handler would have to hardcode a tool→(interpreter, relative-path) table itself. The directory layout `wrappers/{lang}/{tool}/llm-{tool}.{ext}` is regular enough to *derive* such a map, and `detect_wrapper_command` (`run_acceptance.py` lines 199-208) already encodes the ext→interpreter logic (`.js`→node, `.php`→php, `.py`→python3) we could reuse. But it's not provided as data; we'd build and maintain it.

**(d) Licensing.** `README.md` line 130 and `package.json` say MIT, but **there is no `LICENSE` file in the repo.** A bare "MIT" mention without the license text is legally ambiguous and a blocker for depending on it as a vendored dependency. Must be fixed upstream (add `LICENSE`) before adoption.

---

## 9. Concrete Recommendations (prioritized)

**BLOCKERS — upstream must fix before we depend on it:**

1. **Add a `LICENSE` file** (actual MIT text). Non-negotiable for vendoring.
2. **Resolve the dependency-model split.** Pick one: either run the *project's* installed tool (preferred for QA fidelity — matches Python/Bash wrappers), or document loudly that Node/PHP wrappers pin their own version. As-is, eslint/phpstan silently lint with the wrong tool version.
3. **Provide a machine-readable tool→wrapper map** (a `wrappers.json` manifest: `{tool, language, wrapper_path, interpreter, pass_jq, fail_jq}`), so a redirect handler and `jq` queries aren't hardcoded against shapes that may drift.
4. **Add CI** that runs `run_acceptance.py` for all 14 wrappers on clean installs. Without it there is no evidence of correctness.
5. **Fix the tsc wrapper** to honour `tsconfig.json` (`tsc -p`/`--project`) instead of per-file invocation.
6. **Fix the PHPStan fail-branch** to report `totals.errors + totals.file_errors` and surface config-level errors.

**SHOULD-FIX (reliability):**
7\. Add the mandated per-wrapper `README.md` (or drop the requirement from docs to stop the drift).
8\. Make Node wrappers emit a friendly "run npm install" on missing bundled binary (match PHP/Python UX).
9\. Replace pytest stdout-regex with `pytest-json-report`/`--report-log`; replace shfmt lossy hunk-ranges with the actual diff text or a proper formatter API.
10\. Clean up temp-file leaks: PHP `tempnam`+`.json` orphans the base file; add optional cleanup or document that `/tmp` GC is the caller's job.
11\. Make `run_acceptance.py` an aggregate runner (loop all wrappers) and declare its `jsonschema` dependency.
12\. Normalize at least a **minimal uniform envelope field** (e.g. every JSON gets `{passed: bool, error_count: int}` alongside the native shape) so one `jq` query answers pass/fail across all tools.

**USABLE AS-IS (today, behind a defensive handler that parses `(details:)` and falls back to the raw tool on exit 2 / no-details):**

- ShellCheck, Ruff, MyPy (PATH model, native JSON, verified/clean). ESLint is usable *if* we accept the bundled-version caveat and add missing-deps detection.

**Handler design implications for us (regardless of upstream):**

- Capture wrapper stdout, extract the `(details: <path>)` token, hand the agent a per-tool `jq` query (we maintain the query table — there's no uniform schema).
- Treat exit 2 or absent `(details:)` as "wrapper unavailable/errored → let the raw command through or surface a clear install hint."
- GC `/tmp/<tool>-*.json` ourselves; the wrappers never clean up.
- Vendor the wrapper scripts + their lockfiles at a pinned commit (no published package exists); budget for 9+ per-wrapper installs or wrap that in our own installer.

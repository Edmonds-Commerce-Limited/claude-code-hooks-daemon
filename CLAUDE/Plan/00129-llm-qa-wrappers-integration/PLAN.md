# Plan 00129: Wire `llm-friendly-qa-wrappers` in as a Major Dependency

**Status**: Not Started
**Created**: 2026-06-18
**GitHub Issue**: #33
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The daemon already nudges agents toward LLM-friendly tooling (`npm_command` rewrites
raw `npm`/`npx` to `llm:`-prefixed scripts; `lint_on_edit`/`validate_eslint_on_write`
run language-aware linting). The [`edmondscommerce/llm-friendly-qa-wrappers`](https://github.com/edmondscommerce/llm-friendly-qa-wrappers)
repo generalises that idea: a family of thin wrappers around common QA / static-analysis
tools (ESLint, Prettier, Jest, TSC, Vitest, Biome, PHPStan, PHP-CS-Fixer, PHPUnit,
ShellCheck, shfmt, Ruff, pytest, MyPy) that print a **terse 1–5 line terminal summary**
and write **full JSON details to a temp file** for `jq` querying. That output contract is
exactly what an LLM agent wants instead of a wall of human-formatted tool noise.

This plan tracks adopting that repo as a **major dependency** of the hooks daemon and
building handlers that **redirect raw QA tool invocations to the wrapper version**, then
**guide the agent to parse the JSON with `jq`** — the same interception pattern as
`npm_command`, generalised across every wrapped tool and language.

A secondary strand: the wrappers cover individual PHP tools, but our PHP estate runs
[`lts/php-qa-ci`](https://github.com/LongTermSupport/php-qa-ci) (org `lts` =
`LongTermSupport`, a first-party org we fully control) — a Bash pipeline orchestrating
Rector, PHP-CS-Fixer, PHPStan, PHPUnit, Infection, etc. across four phases via `bin/qa`.
We want a wrapper that integrates the *whole pipeline* with the LLM-friendly contract —
most likely a **global `--json` mode on `php-qa-ci`** that puts every underlying tool into
its JSON output mode and emits one machine-readable result document, rather than wrapping
each PHP tool individually and re-implementing the orchestration.

## Goals

- Decide and document HOW `llm-friendly-qa-wrappers` is consumed as a dependency
  (git submodule / vendored clone / pinned tarball / installed package) and pin a version.
- Complete a full critical audit of the wrapper repo (see `AUDIT-llm-friendly-qa-wrappers.md`)
  and gate adoption on its readiness verdict.
- Ship one or more PreToolUse handlers that detect raw wrapped-tool invocations and
  redirect to the wrapper equivalent, with `get_claude_md()` guidance teaching `jq` parsing
  of the JSON temp file.
- Define a single machine-readable mapping `raw command → wrapper invocation` as the SSOT
  for the redirect handlers (no per-handler hardcoding).
- Land a `php-qa-ci` integration: a global `--json` flag (or equivalent) on `bin/qa` that
  drives every tool into JSON mode and produces one aggregate JSON result, exposed through
  the wrapper repo's conventions.
- Maintain the daemon's own standards throughout: TDD, 95%+ coverage, Strategy Pattern for
  the language/tool-aware redirect logic (no if/elif chains in handlers), zero magic values.

## Non-Goals

- NOT reimplementing any QA tool's logic in the daemon — we orchestrate and redirect only.
- NOT forcing the wrappers on projects that don't have them installed — redirect handlers
  must degrade gracefully (advise, don't hard-block, when the wrapper is absent).
- NOT replacing the daemon's existing `npm_command` / lint-on-edit handlers in this plan —
  they may later be refactored to delegate to the wrapper mapping, but that is follow-up.
- NOT changing the wrappers' per-tool JSON schemas — we consume each tool's native shape.

## Context & Background

### Repos cloned for reference

Both reference repos are cloned (untracked) for inspection during this plan:

- `untracked/repos/llm-friendly-qa-wrappers/` — the dependency under evaluation.
- `untracked/repos/php-qa-ci/` — `LongTermSupport/php-qa-ci`, the PHP pipeline to integrate.

(`untracked/repos/` is gitignored; these are scratch clones, not vendored copies.)

### Wrapper repo at a glance

- Output contract: `✅/❌ [Tool]: [Summary] (details: [path])` on stdout; full JSON to a
  temp file; exit codes `0`=pass / `1`=fail / `2`=error. Each wrapper ships a `schema.json`.
- "Native JSON first" — wrappers use each tool's own `--json`/`--format json` mode where it
  exists, and only synthesise JSON for tools that lack one (Prettier, TSC, PHPUnit, pytest,
  shfmt). The reliability of that synthesis is a key audit question.
- Same-language wrappers (`llm-eslint.js`, `llm-phpstan.php`, `llm-ruff.py`), naming
  `llm-{tool}.{ext}`. Runtimes: Node ≥20, PHP ≥8.2, Python ≥3.11.

### php-qa-ci at a glance

- Installed as a Composer dev-dep (`lts/php-qa-ci`); exposes `bin/qa` orchestrator
  (Bash), driven by `includes/options.inc.bash` + `includes/functions.inc.bash`.
- Already ships `scripts/parse-junit-logs.py` (some structured-output handling exists).
- Four phases: code-mod (Rector, CS-Fixer) → lint/validate → PHPStan (max) → PHPUnit/Infection.
- A global `--json` mode would need to thread JSON flags through every phase tool and
  aggregate per-tool JSON into one result document — feasibility to be assessed in Phase 4.

## Tasks

### Phase 1: Audit & Consumption Decision

- [ ] ⬜ **Task 1.1**: Complete the wrapper-repo audit (`AUDIT-llm-friendly-qa-wrappers.md`,
  produced by a dispatched audit agent). Read it and record the readiness verdict.
- [ ] ⬜ **Task 1.2**: Triage audit findings into (a) blockers we must upstream-fix before
  depending, (b) usable-as-is today, (c) nice-to-have. File upstream issues/PRs on the
  wrapper repo for blockers (we control `edmondscommerce`).
- [ ] ⬜ **Task 1.3**: Decide the consumption mechanism (submodule vs vendored clone vs
  pinned release tarball vs package) and pin a specific version/tag. Record as a
  Technical Decision below.
- [ ] ⬜ **Task 1.4**: Decide the wrapper-presence contract — what a redirect handler does
  when the project has not installed the wrapper (advise-and-allow vs offer install).

### Phase 2: Redirect Mapping (SSOT)

- [ ] ⬜ **Task 2.1**: Define a single config/data source mapping `raw tool invocation →     wrapper invocation` (tool name, detector, wrapper path, runtime, jq hint). This is the
  source of truth — handlers read it, never hardcode tool names.
- [ ] ⬜ **Task 2.2**: TDD a tool/language-aware Strategy + Registry so each wrapped tool is
  a strategy (mirrors existing QA-suppression / security-antipattern registries). No
  if/elif chains in the handler.
- [ ] ⬜ **Task 2.3**: Schema-validate the mapping at load (fail fast on malformed entries).

### Phase 3: Redirect Handler(s)

- [ ] ⬜ **Task 3.1**: TDD a PreToolUse handler that detects a raw wrapped-tool Bash command
  and redirects to the wrapper equivalent, with `get_claude_md()` guidance that (a) names
  the wrapper invocation and (b) teaches reading the JSON temp file with `jq`.
- [ ] ⬜ **Task 3.2**: Decide blocking vs advisory per tool (default advisory; degrade
  gracefully when wrapper absent — see Task 1.4). Document rationale.
- [ ] ⬜ **Task 3.3**: Register handler(s) in config with an appropriate priority
  (Code-quality band 25–35, alongside/aware of `npm_command` at 49).
- [ ] ⬜ **Task 3.4**: Daemon restart verification + dogfooding config tests + full QA.
- [ ] ⬜ **Task 3.5**: `get_acceptance_tests()` coverage for redirect + jq-guidance.

### Phase 4: php-qa-ci Integration

- [ ] ⬜ **Task 4.1**: Assess feasibility of a global `--json` flag on `php-qa-ci` `bin/qa`
  (thread JSON modes through each phase tool; aggregate to one result document). Capture
  findings in a supporting doc.
- [ ] ⬜ **Task 4.2**: Decide ownership — does the JSON aggregation live in `php-qa-ci`
  (we control `lts`), in a dedicated `llm-php-qa-ci` wrapper in the wrapper repo, or
  both (flag in php-qa-ci + thin wrapper that calls it). Record as a Technical Decision.
- [ ] ⬜ **Task 4.3**: Implement the chosen integration in the appropriate repo(s) with that
  project's standards (php-qa-ci's own QA pipeline / wrapper repo's CONTRIBUTING checklist).
- [ ] ⬜ **Task 4.4**: Add a redirect-mapping entry so the daemon redirects a raw `qa` /
  pipeline invocation to the JSON-mode equivalent and guides jq parsing.

### Phase 5: Documentation & Rollout

- [ ] ⬜ **Task 5.1**: Document the dependency, the redirect mapping, and the jq workflow in
  `CLAUDE/` + handler reference; regenerate `generate-docs`.
- [ ] ⬜ **Task 5.2**: Changelog + release notes; ship behind config (default conservative)
  so existing projects opt in.

## Dependencies

- Depends on: nothing blocking; audit (Task 1.1) gates Phase 2+.
- Related: existing `npm_command`, `lint_on_edit`, `validate_eslint_on_write` handlers
  (candidate future refactor to delegate to the wrapper mapping).
- Cross-repo: `edmondscommerce/llm-friendly-qa-wrappers` and `LongTermSupport/php-qa-ci`
  (both first-party — we have write access).

## Technical Decisions

### Decision 1: Consumption mechanism — DEFERRED to Task 1.3

**Context**: How the daemon depends on the wrapper repo (submodule / vendored / pinned
release / package) determines update cadence and the "wrapper present?" contract.
**Options Considered**: git submodule (explicit pin, extra clone step), vendored snapshot
(self-contained, manual updates), pinned release tarball fetched at install (clean, needs
release discipline in the wrapper repo), language package managers (per-runtime, fragmented).
**Decision**: TBD after audit reveals release maturity.

### Decision 2: php-qa-ci JSON ownership — DEFERRED to Task 4.2

**Context**: Whether aggregate JSON lives in `php-qa-ci` (`--json` flag) or in a wrapper.
**Decision**: TBD after Task 4.1 feasibility assessment.

## Success Criteria

- [ ] Audit complete with a recorded verdict; blockers filed upstream.
- [ ] Consumption mechanism chosen, pinned, and documented.
- [ ] Redirect mapping exists as a single schema-validated SSOT.
- [ ] At least one redirect handler ships (TDD, 95%+ coverage, acceptance tests, dogfooded,
  daemon restart verified) redirecting a raw tool to its wrapper and teaching jq parsing.
- [ ] php-qa-ci global JSON integration implemented and wired into the redirect mapping.
- [ ] All QA checks pass; docs regenerated; changelog/release notes updated.

## Risks & Mitigations

| Risk                                                              | Impact | Probability | Mitigation                                                              |
| ----------------------------------------------------------------- | ------ | ----------- | ----------------------------------------------------------------------- |
| Wrapper repo not mature enough to depend on                       | High   | Med         | Audit gates adoption; fix blockers upstream first (we own the repo)     |
| Non-deterministic JSON temp-file paths break programmatic capture | High   | Med         | Audit Item 4; require predictable/announced paths before redirect ships |
| Redirect fires in projects without the wrapper installed          | Med    | High        | Advisory default + graceful degradation (Task 1.4/3.2)                  |
| Heavy per-tool install surface deters adoption                    | Med    | Med         | Prefer single install entrypoint; document minimal footprint            |
| php-qa-ci `--json` threading is invasive across phases            | Med    | Med         | Feasibility spike (Task 4.1) before committing to flag vs wrapper       |

## Notes & Updates

### 2026-06-18

- Plan created. Both reference repos cloned into `untracked/repos/`
  (`llm-friendly-qa-wrappers`, `php-qa-ci` from `LongTermSupport`).
- Audit agent dispatched against the wrapper repo; full report in
  `AUDIT-llm-friendly-qa-wrappers.md` in this folder.
- GitHub tracking issue opened: Edmonds-Commerce-Limited/claude-code-hooks-daemon#33.
- Note: `lts/php-qa-ci` resolves to `github.com/LongTermSupport/php-qa-ci` (org slug `lts`).

#### Audit verdict (2026-06-18): NOT READY — adopt with upstream fixes

Brand-new v0.1.0 repo (single tag, 0 issues/PRs, no CI, **no LICENSE file despite MIT
claim**). The core terse-output + JSON-temp-file contract genuinely works (ShellCheck
wrapper verified end-to-end), but it is **not a safe major dependency as-published**.
A small subset is usable *today* behind a defensive handler.

**Upstream blockers (file against `edmondscommerce/llm-friendly-qa-wrappers` — we own it):**

1. **No LICENSE file** — add one (claims MIT). Hard blocker for vendoring.
2. **Two incompatible dependency models** — Node/PHP wrappers run the tool from the
   wrapper's OWN bundled `node_modules`/`vendor` (lints with the *wrapper's* tool version,
   not the project's); Python/Bash wrappers run from PATH. Redirecting `eslint src/` would
   silently swap in the wrapper's ESLint. Needs a coherent "which version runs" story.
3. **No machine-readable `raw command → wrapper` manifest** — our Task 2.1 SSOT cannot be
   sourced from the repo; we'd hand-maintain it. Best fixed upstream so the map is shared.
4. **No uniform JSON shape** — every tool emits a different structure (ESLint=bare array,
   PHPStan=`totals/files`, MyPy=`summary.error_count`, Jest=`success`…), so a caller cannot
   write one `jq` pass/fail query. The one reliable uniform signal is the stdout token
   `(details: /tmp/<tool>-<hex>.json)` — a redirect handler MUST capture stdout and parse
   that token (path is non-deterministic); exit-2 errors emit NO details path.
5. **Correctness bugs** — PHPStan fail-branch under-reports config-level errors (prints
   "0 errors found" while exiting 1); `tsc` invoked per-file bypasses `tsconfig.json`
   project semantics; `shfmt` output lossy; pytest uses brittle stdout-regex parsing.
6. **No CI; per-wrapper READMEs missing on all 14; no aggregate test runner.**
7. **Temp-file hygiene** — wrappers never clean up (`delete=False`), PHP `tempnam`+`.json`
   leaks orphans → `/tmp` accumulates.

**Usable as-is today** (PATH model, native JSON, clean): **ShellCheck, Ruff, MyPy** —
behind a defensive handler that parses the `(details:)` token and falls back on exit 2.

**Implications for this plan:**

- Phase 1 consumption decision (Task 1.3) is **gated on the LICENSE fix** — cannot vendor
  without it. Prefer pinning a future hardened release over the current `v0.1.0`.
- Task 2.1 (mapping SSOT): push for the manifest to live **upstream** in the wrapper repo
  so the daemon consumes it rather than hand-maintaining a parallel table.
- Phase 3 first handler should target the **3 clean tools (ShellCheck/Ruff/MyPy)** behind a
  defensive `(details:)`-token parser + exit-2 fallback, NOT the Node/PHP wrappers until
  blocker #2 is resolved.
- The `(details:)` stdout token — not any per-tool JSON shape — is the redirect handler's
  contract with the wrapper. Design `get_claude_md()` jq guidance around reading that file.

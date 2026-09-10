# Plan 00368: lsp is signal not noise

**Status**: In Progress
**Created**: 2026-09-10
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Claude Code injects the language server's diagnostics into the agent's
context after every edit. In this session that stream carried thousands of
pyright errors about symbols this checkout does not have: `pyrightconfig.json`
had no `exclude`, so the server analysed every linked worktree under
`untracked/`, and two sub-agents' half-built branches were reported as
defects here. Measured with the CLI: 3,011 errors, of which 2,056 came from
`untracked/`, the plan archive's probes and deliberately broken fixtures.
The agent learnt to skim the stream, which is the failure the owner named:
"if there's noise, there's no signal and LSP is pointless".

Owner ruling: LSP noise must be fixed at its source, never ignored, because
leaving it is a context leak and it trains the agent to skip real defects.
The exclude landed first (`461a2563`, pinned by
`tests/unit/test_pyright_config.py`). This plan makes the property hold by
construction: the pyright CLI becomes a blocking QA tool at zero errors, so
any diagnostic the agent sees is real; every remaining real error is fixed;
and a session-start check reports a missing exclude or a stale language
server with the exact fix, in this repo and in every client.

## Goals

- `./scripts/qa/llm_qa.py all` runs pyright over the project and fails on
  any error; the count is zero on main.
- A `SessionStart` handler `lsp_noise_checker` advises, for every supported
  language present (Python, TypeScript/JavaScript, Go, Rust, PHP - not
  Python alone), with that language's exact fix, when its server isn't
  told to exclude a tree the daemon knows is not project code (its runtime
  dir, the plan directory, vendor and build dirs, fixture trees, the
  remote-docs tree), or when a matching language-server process started
  before that check's anchor file was last written.
- The remaining real errors are fixed, not suppressed: no `# type: ignore`,
  no `# pyright: ignore`, no rule downgrades in the config.

## Non-Goals

- No replacement of mypy: pyright joins it, it does not supersede it.
- No per-rule relaxation in `pyrightconfig.json` to reach zero.

## Tasks

### Phase 1: The exclude (delivered)

- [x] ✅ **Task 1.1**: `pyrightconfig.json` excludes `untracked`, the plan
  archive, both fixture trees and `remote-docs`; `test_pyright_config.py`
  pins the list; `LSP.md` explains why (`461a2563`).

### Phase 2: The gate and the checker

- [x] ✅ **Task 2.1**: `pyright` as a `TOOL_REGISTRY` entry in
  `scripts/qa/llm_qa.py` (blocking, zero errors, cache file like the
  others), with the wiring tests the other tools have; `CLAUDE/QA.md` and
  `CLAUDE/development/QA.md` name it. Pyright itself: pin the version and
  install path the QA needs (`pyproject.toml` dev extra if it is on PyPI
  as `pyright`, else document the `npm`/binary route the CI job uses) and
  add it to the CI workflow (`61bd6d36`).
- [x] ✅ **Task 2.2**: `lsp_noise_checker` (`SessionStart`, advisory,
  every supported language - Python, TypeScript/JavaScript, Go, Rust, PHP,
  not Python alone): a per-language `LspNoiseStrategy` Strategy Pattern
  registry (`strategies/lsp_noise/`, mirroring the `tdd` archetype) behind
  a zero-language-logic handler; the two checks above, rule IDs
  `R-LSP-CONFIG-EXCLUDE` and `R-LSP-SERVER-STALE` (language named in the
  message), `get_claude_md()`, `get_acceptance_tests()` aggregated per
  language, `explain-rule`, handler reference with a per-language mechanism
  table; the daemon's own knowledge of the excluded trees comes from
  `constants.layout`, the plan-workflow config and the remote-docs config,
  never a hand-typed list. Each language's exclude mechanism verified
  against Claude Code's own marketplace plugin configs
  (`anthropics/claude-plugins-official`) and each tool's own docs, never
  assumed - PHP (intelephense) takes no project-file exclude at all, so
  its fix is a project-scope LSP plugin override, scanned for rather than
  reported "unsupported".

### Phase 3: The sweep

- [ ] ⬜ **Task 3.1**: Fix every pyright error under `src/`, `scripts/`,
  `install.py` and `tests/` outside the excluded fixture trees, by making
  the code correct (Optional narrowing with assertions or guards, typed
  fixtures, real attribute access), never by suppression.
- [ ] ⬜ **Task 3.2**: Full QA green with the new tool; daemon restart
  RUNNING; release-notes callout; config-changes manifest if the handler
  adds a key.

## Success Criteria

- [ ] `pyright --project .` reports 0 errors on main and QA fails if one
  returns.
- [ ] A session in a project using any supported language whose server
  analyses its runtime dir, or whose language-server process predates its
  check's anchor file, is told exactly how to fix it.
- [ ] No suppression comment or rule downgrade was added to reach zero.
- [ ] Every release-bound consequence is in the pending-release holding
  area: a release-notes callout, and a config-changes manifest if a key
  was added.

## Delivery & Milestones

- `461a2563` — Phase 1, the exclude and its guard.
- `61bd6d36` — Task 2.1, pyright as a zero-errors QA gate.

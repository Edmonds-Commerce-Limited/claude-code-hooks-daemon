# Plan 00467: recommend the defence before fix plugin to client projects

**Status**: Blocked
**Created**: 2026-09-24
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The owner asked to install the Defence Before Fix (DBF) Claude Code plugin
(`Defence-Before-Fix/claude-plugin`), dogfood it here, and, once it is
judged good, recommend it to every hooks-daemon project "as part of the
suggested stuff".

The plugin (v0.1.1, MIT, by the method's author) ships the `/dbf` skill
and two agents, `conformance-reviewer` and `independent-searcher`. It has
no hooks and no MCP servers. The skill's only extra tool grant is its own
`refresh-spec.bash`, which fetches the five method documents from
`defence-before-fix.github.io` into the plugin's data directory, and falls
back to its vendored copies. Projected cost is about 290 tokens always-on,
and about 1.6k per `/dbf` invocation.

It is enabled here through `.claude/settings.local.json`: the marketplace
is in `extraKnownMarketplaces`, the plugin in `enabledPlugins`. It is not
in `.claude/settings.json`, because that file is also the template the
installers ship to every client (Plan 00468 P1). The plugin's files are
cached under `.claude/ccy/plugins/` (`cache/` and `marketplaces/`).

The daemon has no mechanism for recommending a Claude Code plugin to a
client project. Plans 00133 and 00308 suggest dormant **daemon** features
on upgrade and through `/hooks-daemon config-optimisation`; that is the
closest prior art, and the natural home for the recommendation.

## Goals

- Dogfood the plugin against written criteria, and record what it does
  well and where it falls short, on this repository.
- Feed the shortfalls back to the plugin upstream as specific,
  reproducible reports.
- Once the owner signs off, recommend the plugin to client projects
  through a general recommended-plugins mechanism, with DBF as its first
  entry.

## Non-Goals

- Installing or enabling the plugin in a client project automatically. A
  recommendation is advice; enabling it is the client's decision.
- Replacing this repository's own DBF guidance
  (`CLAUDE/CodeLifecycle/Bugs.md`, `CLAUDE/Security/`). The plugin and
  that guidance follow the same canonical specification.

## Tasks

### Phase 1: Dogfood

- [x] ✅ **Task 1.1**: Review the plugin before installing it (manifest,
  agents' tool grants, the network script), then install it at project
  scope.

- [ ] ⬜ **Task 1.2**: Evaluate it against these criteria, recording
  evidence in the journal each time `/dbf` runs or auto-triggers:

  - Does it find this project's detectors? Found before the first run:
    its toolchain discovery reads `composer.json` / `package.json`
    manifest keys and a register graded for PHP and TypeScript. This
    repository is Python, and its detectors are the `scripts/qa/check_*.py`
    family behind `llm_qa.py`, catalogued in `CLAUDE/Security/`. Nothing
    tells the skill that.
  - Does its auto-trigger ("fix a bug, a failing check or a red QA run")
    fire where DBF applies, and stay quiet where it doesn't? How does it
    interact with the hooks daemon's own guards and with sub-agent
    targeted-QA rules (Plan 00463)?
  - Spec duplication: this repository vendors the method documents under
    `remote-docs/`, and the plugin vendors its own copy. Record whether
    the versions agree.
  - The token cost, measured against the projection.
  - Do the two agents' outputs follow this repository's report
    conventions (sub-agent reports to a file, Plan 00460)?

  Evidence: [EVALUATION.md](EVALUATION.md). Every criterion has evidence
  except auto-trigger. That one is judged from the description only,
  because the headless probe could not log in. It stays open until one
  logged-in probe runs (EVALUATION.md, last section).

- [x] ✅ **Task 1.3**: File each shortfall upstream on
  `Defence-Before-Fix/claude-plugin`, with a reproduction and no
  client-identifying detail. For example: a Python toolchain route, or a
  way for a project to declare its detector entry point. Filed: #2 and #3
  earlier; from [upstream-drafts/](upstream-drafts/), #4 (draft 01,
  discovery skips the project's own detectors), #5 (draft 03, the
  reviewer's full-gate cost) and #6 (draft 04, the spec cache directory and
  versions). Drafts 05 and 06 are posted as comments on #2 and #3. Draft 02
  (auto-trigger on every red run) is held: it is a judgement from the
  description, and it is filed only if the logged-in probe in Task 1.2
  confirms it.

- [ ] ⬜ **Task 1.4**: Write up the dogfood findings and put the go/no-go
  question to the owner. **Phase 2 starts only on the owner's sign-off.**
  Written up in [EVALUATION.md](EVALUATION.md) and the
  [dogfood report](subagent-reports/260924-p467-dogfood-opus-5-5.md).
  **Recommendation: no-go for now.** Four reasons:

  1. The agents lose their reports without this repository's auto-save (#3).
  2. Discovery cannot find a non-PHP/TS project's own detectors (#2, #4).
  3. The daemon's own plugin support (00468 Phases 2–3) should land first.
  4. The auto-trigger has not been observed live, and a false trigger costs
     roughly 6–20k tokens plus two agents.
     Go once 1–3 are fixed upstream and here, with the measured costs stated.
     **Waiting on the owner** for the go/no-go, and on one logged-in session
     (a human-started one, where the plugin is loaded) running the Task 1.2
     trigger probe in `untracked/scratch/p467/trigger-probe/`.

### Phase 2: Recommend to client projects (gated on owner sign-off)

- [ ] ⬜ **Task 2.1**: Design a recommended-plugins list (marketplace,
  plugin id, why, what it costs) in one place, with DBF as its first
  entry. Decide where it is surfaced: the `config-optimisation` flow
  (00308), an `optimal_config_checker` check, or a SessionStart advisory
  that reads `enabledPlugins` and `extraKnownMarketplaces`. Say it once
  per session at most, never block, and allow opting out per project.
- [ ] ⬜ **Task 2.2**: TDD the mechanism; release note and docs.

## Success Criteria

- [ ] Phase 1 findings are written up with evidence, and each shortfall
  has an upstream issue.
- [ ] The owner has decided go or no-go.
- [ ] On go: a client project without the plugin is told about it once,
  can opt out, and is never blocked.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00467-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plugin installed at project scope: `b00ecd02`.

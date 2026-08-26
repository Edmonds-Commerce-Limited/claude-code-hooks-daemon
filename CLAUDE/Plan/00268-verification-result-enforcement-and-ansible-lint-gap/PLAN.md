# Plan 00268: Verification-result enforcement (verifier→mutator) and the Ansible/YAML lint gap

**Status**: In Progress
**Created**: 2026-08-25
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A field report from a client project (an Ansible-first repo running this daemon)
records an incident where a verification command failed, **printed its own correct
diagnosis**, and was then ignored by a `git commit` in the same Bash invocation.
`ansible-lint` exited 2, the exit code was captured and echoed, the full diagnosis
was `cat`-ed — and `git add` / `git commit` / `git push` ran anyway. An unloadable
play sat on `main` for one commit. The failure was not that the agent skipped the
check; it is that **nothing consumed the check's result**. A check whose outcome
nothing acts on is decoration that produces the feeling of having verified.

The report's full analysis lives in
[ANALYSIS-command-chaining.md](ANALYSIS-command-chaining.md) and is the durable
reference for this plan — read it before implementing. Its headline conclusion is
deliberately *against* the obvious rule: blanket `;` → `&&` enforcement would have
**missed this very incident** (the dangerous separator was a NEWLINE, not a `;`)
and would fire constantly on legitimate diagnostic shell (`grep -q x f; echo done`,
`cmd > f 2>&1; echo "exit=$?"`, `diff a b; echo ---`). A handler that is mostly
wrong gets disabled, which leaves the project worse off than no handler.

Two changes are worth building, in the report's own priority order. First, close a
genuinely surprising coverage gap: `lint_on_edit` lints Python, Shell, Go, PHP,
Ruby, Rust, Swift, Kotlin and Dart, and **nothing lints Ansible YAML** — verified
against `strategies/lint/`, which has no YAML strategy. Had the Edit been linted,
the write would have been denied at the moment it was made, with the right
diagnosis, before a commit was contemplated. Second, add a narrow, high-precision
`verifier → mutator` handler that fires only when a verifier and a later mutator
share one Bash invocation with nothing consuming the verifier's exit status.

## Goals

- Add an Ansible/YAML lint strategy to `lint_on_edit`, scoped to files that are
  plausibly playbooks, so a load-time parse failure is reported at write time.
- Ship a `verifier → mutator` PreToolUse handler in `warn` mode that names the
  specific offending pair, treats a **newline as a separator equal to `;`**, and
  does not fire when the result is genuinely consumed.
- Reuse the existing shared scanner (`utils/shell_segmentation.split_unquoted`,
  whose separator tuples already include `"\n"`) rather than growing a third
  private bash scanner — the exact failure Plan 00200 Task 3.7 consolidated away.
- Evaluate extending the commit gate to lint staged files as the backstop, so the
  outcome is caught however the commit was invoked.

## Non-Goals

- **Blanket `;` → `&&` enforcement is explicitly rejected, not deferred.** The
  report demonstrates it is simultaneously leaky (misses the motivating incident,
  which used newline separation) and noisy (fires on `grep`-exits-1, diagnostic
  sweeps, independent listings, deliberate exit-code observation). Mechanical
  rewriting also changes semantics — `a && b; c` differs from `a && b && c`, and a
  cleanup step that must always run silently stops running.
- Enforcing `set -e` on multi-command invocations as a standalone rule. It fixes
  the whole class with no taxonomy to maintain, but changes semantics for every
  command in the invocation. Offer it as **remedy text in the block message**, not
  as its own gate.
- Linting arbitrary YAML. `.github/workflows/`, `hooks-daemon.yaml`, inventory
  `hosts.yml` and vault files are not playbooks; linting them produces noise or
  spurious failures.
- Preventing the original mistake (writing an apostrophe into an Ansible `shell:`
  block). Nothing here does that. The aim is to catch it in seconds rather than in
  a push.

## Context & Background

Relevant existing infrastructure, verified in this codebase:

- `utils/shell_segmentation.py` — the single quote-aware scanner. `split_unquoted`
  already takes a separator tuple, and both callers (`pipe_blocker._CHAIN_SEPARATORS`,
  `command_hints._SEGMENT_SEPARATORS`) already include `"\n"`. The report's most
  important design point is therefore **already available** — the new handler must
  use it, not reimplement it.
- `utils/command_evasion.py` — recognises path-qualified and `env`-prefixed
  invocation respellings; needed so `/usr/bin/ansible-lint` and `env X=1 git commit`
  are matched as the tools they are.
- `strategies/lint/` — the Strategy + Registry pattern a YAML strategy plugs into
  (`protocol.py`, `registry.py`, `common.py`), with the cheap-syntax-check /
  deeper-linter split already modelled.
- `plan_qa_commit_gate` — proves the `git commit` hook point works for staged-tree
  inspection, which is the pattern the Phase 3 backstop would follow.

Precision is the binding constraint on both handlers. Plan 00204 records the same
lesson for `security_antipattern`: a construct-level rule only earns its place if
its false-positive rate stays low enough that nobody disables it.

## Tasks

### Phase 1: Ansible/YAML lint strategy for `lint_on_edit`

- [x] ✅ **Task 1.1**: Gap confirmed; detection rule decided — see
  [DESIGN-ansible-lint.md](DESIGN-ansible-lint.md) §2–§3. Neither of the
  obvious rules survives: a path allowlist misses `site.yml`, the canonical
  Ansible entry point, and a parse-based content test cannot see the very file
  this feature exists to catch, because the motivating incident was a file that
  FAILED to parse. Accepts on path OR a crude text sniff that survives a broken
  file; parse is confirmation, never a gate
- [x] ✅ **Task 1.2**: Resolution rule decided — reuse `_MODULE_ROOT_MARKERS`,
  the existing per-language marker walk that already gives Go its `go.mod`
  root, mapping `"Ansible": "ansible.cfg"`. No new mechanism (DESIGN §4)
- [x] ✅ **Task 1.3**: `AnsibleLintStrategy` TDD'd with the tier split intact —
  `ansible-playbook --syntax-check` as the cheap default, `ansible-lint` at
  `extended`. The narrowing needed a new capability protocol, `NarrowsByPath`:
  a member added to `LintStrategy` itself would break 13 existing
  `isinstance(..., LintStrategy)` assertions, since a `runtime_checkable`
  Protocol tests member PRESENCE
- [x] ✅ **Task 1.4**: Registered in `strategies/lint/registry.py`, which now
  honours `NarrowsByPath` so an extension match can be declined. The eight
  strategies that do not implement it keep matching on extension alone, proven
  by test. `languages` / `command_overrides` / `exclude_paths` and the
  missing-linter leniency are inherited unchanged from the handler
- [x] ✅ **Task 1.5**: `get_claude_md()` states which YAML is claimed and which
  is left alone, names both tiers, and repeats that the write has ALREADY
  landed — the denial is a failure report to repair with `Edit`, not a rollback
- [x] ✅ **Task 1.6**: QA 23/23, daemon RUNNING, and the client fixture rebuilt
  from the committed tree registers Ansible, resolves `ansible.cfg`, claims
  `playbooks/` and `site.yml`, and declines workflows, Compose, inventories and
  vault. Dogfooded against the live daemon: the motivating shape is DENIED at
  write time with the linter's own `failed at splitting arguments` diagnosis,
  and a workflow file returns `{}`

### Phase 2: `verifier → mutator` PreToolUse handler (warn mode)

- [x] ✅ **Task 2.1**: Settle the verifier and mutator taxonomies as named
  constants, seeded from the report's lists, and decide whether they are
  config-extensible per project.
- [x] ✅ **Task 2.2**: TDD the detection using `split_unquoted` with a separator
  tuple containing `"\n"`. A regression test must encode the motivating
  incident verbatim: a multi-line command whose lint is on line 1 and whose
  `git commit` is on line 3, with no `&&` between them.
- [x] ✅ **Task 2.3**: TDD every non-firing case: `verifier && mutator`;
  `verifier || { …; exit 1; }`; `rc=$?` followed by an `if`/`case`; `set -e` in
  effect for the invocation; and a mutator that appears only inside a heredoc
  body or a quoted string and is therefore never executed.
- [x] ✅ **Task 2.4**: TDD the false-positive suite from the report's own table —
  `grep -q p f; echo done`, `cmd > f 2>&1; echo "exit=$?"`, `diff a b; echo ---`,
  independent `ls -1t` listings, and a labelled diagnostic sweep — all ALLOW.
- [x] ✅ **Task 2.5**: Write the advisory text so it names the pair
  ("`ansible-lint` can fail here and `git commit` would still run — gate it")
  and shows the accepted forms. It must not read as a style opinion about `&&`.
- [x] ✅ **Task 2.6**: Ship `mode: warn` by default with a documented ratchet to
  `block`, mirroring `plan_qa_commit_gate`'s warn-first rollout.
- [x] ✅ **Task 2.7**: Add `get_acceptance_tests()`, register in config, restart the
  daemon, and dogfood the handler in this repo.

### Phase 3: Staged-file lint backstop at `git commit`

- [x] ✅ **Task 3.1**: Decide whether to extend the existing commit gate or add a
  sibling handler, and bound the cost of linting staged files on every commit.
  **Decision: sibling PreToolUse handler `staged_lint_gate`, priority 43.**
  Extending `plan_qa_commit_gate` was rejected: plan-tree QA and source lint are
  different responsibilities (SRP) with different options, failure modes and
  rollout schedules. Cost bounds: cheap/syntax tier ONLY (never the extended
  linter); only staged Added/Copied/Modified files that a lint strategy
  handles; a `max_files` cap (default 20) above which the handler stands down
  with an advisory naming how many were skipped; per-file timeout; nested and
  foreign repos exempt (mirroring `plan_qa_commit_gate`). Ships `mode: warn`.
- [x] ✅ **Task 3.2**: If approved, TDD it and ship warn-first; it catches the
  outcome regardless of how the commit was invoked — chained, separate, or from
  a later turn entirely.

### Phase 4: Documentation and rollout

- [x] ✅ **Task 4.1**: Update `docs/guides/HANDLER_REFERENCE.md` and the language
  table in `CLAUDE.md` to include the new YAML/Ansible coverage.
- [x] ✅ **Task 4.2**: Add `config-changes/` and, if a documented truth changed,
  `truth-changes/` manifests under `CLAUDE/UPGRADES/UNRELEASED/` so both
  features are actively promoted on upgrade rather than shipping dormant.

## Dependencies

- Related: Plan 00204 (precision constraint on construct-level rules), Plan 00129
  (`lint_on_edit` / QA-wrapper adjacency). Neither blocks this plan.
- Builds on completed Plans 00054 (lint strategy pattern), 00200 and 00222 (the
  shared shell scanner), 00260 and 00263 (Bash write side-doors and tokenising).

## Success Criteria

- [ ] An Edit that writes an unloadable Ansible playbook is denied at write time
  with the linter's own diagnosis.
- [ ] The motivating multi-line incident command is flagged by the Phase 2 handler.
- [ ] Every false-positive shape in the report's table is ALLOWed, proven by tests.
- [ ] No private bash scanner is added — detection uses `split_unquoted`.
- [ ] Blanket `;` → `&&` enforcement is not implemented, and the reason is recorded.
- [ ] Full QA passes and the daemon restarts RUNNING after each phase.

## Risks & Mitigations

| Risk                                                                          | Impact | Probability | Mitigation                                                                                                                                                                                                                               |
| ----------------------------------------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Verifier/mutator lists cry wolf and the handler gets disabled                 | High   | Medium      | Ship `warn` first; test the report's false-positive table as ALLOW cases before enabling                                                                                                                                                 |
| YAML strategy lints non-playbook YAML (workflows, inventories, vault)         | Medium | Medium      | Narrow path allowlist plus mandatory exclusions; default `exclude_paths`                                                                                                                                                                 |
| `ansible-lint` runs from the wrong project dir and fails for the wrong reason | Medium | Medium      | Resolve the project dir explicitly (Task 1.2); treat a resolution failure as skip-with-advisory, not deny                                                                                                                                |
| Full `ansible-lint` is slow enough to be disruptive on every write            | Medium | Medium      | Cheap `--syntax-check` runs first and short-circuits on failure. NOT opt-in: `extended` runs whenever the tool is installed, as it does for all nine other languages, so the opt-out is `command_overrides: {Ansible: {extended: null}}` |
| Detection reimplements shell parsing and drifts from the shared scanner       | High   | Low         | Task 2.2 mandates `split_unquoted`; add a test asserting newline parity with `;`                                                                                                                                                         |
| Staged-file lint makes every commit expensive                                 | Medium | Medium      | Phase 3 is gated on a cost decision (Task 3.1); it may be dropped                                                                                                                                                                        |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00268-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not yet started.

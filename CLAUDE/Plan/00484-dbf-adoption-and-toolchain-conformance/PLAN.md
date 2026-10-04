# Plan 00484: DBF adoption and toolchain conformance

**Status**: In Progress
**Created**: 2026-10-02
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #65, #67

## Overview

Owner ruling (verbatim): "yes - this repo should fully adopt DBF and should link to it. This
repo also has some claims to actually be a DBF tool, or at least hook into them."

Defence Before Fix (DBF, <https://defence-before-fix.github.io>) is already how this
repository works internally. Its method documents are vendored under
`remote-docs/defence-before-fix.github.io/`. `CLAUDE/Security/` names the Defence for each
defect class. The security routines and the `scripts/qa/` detectors follow the method, and the
DBF plugin is dogfooded here (Plan 00467). None of this is visible publicly: the README and the
`explain-rule` output never name the method (#65, #67). Those two issues, and Plan 00467's
go/no-go, waited on whether to link an external method from the project's public face. The
owner has now decided: yes.

The second half is the larger one. Measured against the vendored
[toolchain specification](../../../remote-docs/defence-before-fix.github.io/raw/TOOLING-SPEC.md),
the daemon is close to a DBF toolchain already:

| Spec               | Daemon                                                                                          |
| ------------------ | ----------------------------------------------------------------------------------------------- |
| bundled defences   | handlers                                                                                        |
| identifiers (§4.2) | rule IDs, resolved offline by `explain-rule`                                                    |
| enumeration (§5)   | the handler listing and the generated `.claude/HOOKS-DAEMON.md`, derived from the active config |
| agent context (§7) | the CLAUDE.md guidance it injects automatically                                                 |
| self-audit (§8)    | dogfooding, and `tests/integration/test_claude_md_guidance_coverage.py`                         |

The open questions are the project record (§6), suppression routes (§4.3, set against the
in-command `MUST_..._BECAUSE` declarations), detector conformance (§4.1, DETECTOR-SPEC), and a
conformance declaration (§9). "Hook into them" means a DBF tool, such as the plugin's
`/dbf` skill, can discover this daemon's defences and its detector entry point. Upstream
plugin issue #4 (discovery skips a project's own detectors) is the same gap seen from the
other side.

Scope stays inside the
[threat model](../../ARCHITECTURE.md#threat-model-the-agent-is-careless-not-hostile). A
conformance claim must say what the daemon does, and must not claim defence against a hostile
agent.

## Goals

- The README and the CLI name DBF and link to it (#65, #67). Every rule's `explain-rule`
  output says which defect class it defends and links to the method.
- A written conformance assessment against TOOLING-SPEC §4–§9. Each MUST and SHOULD is graded
  met, partly met, or not met, with file:line evidence. It is published as the §9.2
  declaration, with its known gaps.
- The gaps the owner accepts as in scope are closed, TDD, through the ledger.
- A DBF tool can enumerate this daemon's defences and find its detector entry point without
  project-specific knowledge.

## Non-Goals

- Rewriting the handlers to fit the spec's vocabulary. The names stay; the mapping is
  documented.
- Recommending the plugin to client projects. That stays in Plan 00467 Phase 2. This plan
  removes its relationship blocker, but its technical no-go reasons (#2, #3, #4 upstream)
  still stand.
- Claiming defence against a hostile agent or against prompt injection.

## Tasks

### Phase 1: Adopt and link (#65, #67)

- [x] ✅ **Task 1.1**: README: name the method, link it, and say in one paragraph how the
  daemon applies it (handlers are defences that run at tool-call time). Place it next to
  "Guardrails, not armour" and keep it consistent with that section. Done: a "Defence Before
  Fix" subsection follows "Guardrails, not armour" in the README.
- [x] ✅ **Task 1.2**: `explain-rule` (and `explain-handler`) print one line naming DBF with
  the link, after `RuleFormatter().verbose(rule)` (`cmd_explain_rule`). TDD. Done: the line
  is `DefenceBeforeFix.EXPLAIN_LINE` in `constants/dbf.py`.
- [x] ✅ **Task 1.3**: The agent tree points to the method from its canonical homes
  (`CLAUDE/Security/README.md`, `CLAUDE/CodeLifecycle/Bugs.md`, `CLAUDE/HANDLER_DEVELOPMENT.md`).
  Each gets one pointer to the vendored spec, not a restatement (DocumentationStrategy.md).
  Done: Bugs.md already carried the section, so its vendored-copy mention now links the path.
- [ ] ⬜ **Task 1.4**: Comment on #65 and #67 with the ruling and this plan. Use
  `Addresses #N`, never a closing keyword. Remove `agent-needs-human`.

### Phase 2: Conformance assessment

- [x] ✅ **Task 2.1**: Assess every MUST and SHOULD in TOOLING-SPEC §4–§9, and DETECTOR-SPEC
  for the detectors the daemon routes. Grade each one met, partly met, or not met, with
  file:line evidence. Write it to `CONFORMANCE.md` in this folder. Check the vendored copy is
  fresh first (`hooks-daemon remote-docs`). Done in [CONFORMANCE.md](CONFORMANCE.md); the
  vendored specs match upstream. Neither level conforms yet: 9 MUSTs are not met at
  project level and 5 at artefact level, giving gaps G1–G14.
- [x] ✅ **Task 2.2**: Fable review of the assessment: is any grade generous, and is any claim
  outside the threat model? Done in [REVIEW-fable.md](REVIEW-fable.md). It makes 5 grade
  corrections (4 down, 1 up), adds new gaps G15 and G16, and puts an owner batch. Neither
  level's verdict changes.
  - **Coordinator correction to G14.** Both documents say the hooks "fail open when the daemon
    is not running". The code says otherwise. A hook first starts the daemon (`ensure_daemon`,
    lazy start). If that fails on an installed project, PreToolUse fails CLOSED and denies
    every call except the recovery command (`.claude/init.sh`, around lines 612–637, Plan 00466
    N24 MA4). Stop and SubagentStop block. Fail-open is limited to named setup states: not
    installed (fresh clone), venv missing, version mismatch, repo unconfigured, and CI. G14
    is therefore mostly met. The declaration should state exactly those states, not a
    blanket fail-open.
- [ ] ⬜ **Task 2.3**: Put the gaps to the owner as one batch: close, accept as a known gap, or
  out of scope. Expected questions:
  - §4.3 against the `MUST_..._BECAUSE` declarations: is an in-command justification a
    project-record entry, or a suppression route that bypasses it?
  - §6.1/§6.2: is `.claude/hooks-daemon.yaml` (`exclude_paths`, `extra_whitelist`) the project
    record, and must every exception carry a justification?

### Phase 3: Close the gaps and hook in

- [ ] ⬜ **Task 3.1**: Close the accepted gaps through the ledger, at most 3 branches at once.
- [x] ✅ **Task 3.2**: A machine-readable enumeration of active defences (§5): rule ID,
  handler, defect class, docs link, and the detector entry point, so a DBF tool can read
  them. Reuse the generate-docs data rather than a second source. Done: `hooks-daemon defences --json`, see [the report](subagent-reports/261004-task-3.2-defence-enumeration-sonnet.md).
- [ ] ⬜ **Task 3.3**: Publish the conformance declaration (§9.2), with its known gaps, from
  the README.

## Success Criteria

- [ ] The README and `explain-rule` name DBF and link to it. #65 and #67 are answered.
- [ ] `CONFORMANCE.md` grades every MUST and SHOULD with evidence, and has survived a Fable
  review.
- [ ] The owner has ruled on every gap. The accepted ones are closed, and the rest are listed
  in the declaration.
- [ ] A DBF tool can list this daemon's defences without project-specific knowledge.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00484-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan filed with the owner's adoption ruling.

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
- [x] ✅ **Task 1.4**: Comment on #65 and #67 with the ruling and this plan. Use
  `Addresses #N`, never a closing keyword. Remove `agent-needs-human`.
  **Owner ruling (2026-10-05):** yes, post it — see [OWNER-RULINGS-261005.md](../00483-threat-model-conformance-audit/OWNER-RULINGS-261005.md) (C2). Done 2026-10-05: comments posted on #65 and #67 ("Addresses", no closing keyword), and `agent-needs-human`
  removed from both.

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
  - **Coordinator call (2026-10-05, under the owner's "go with the clear winners" instruction), for the owner batch in
    [REVIEW-fable.md](REVIEW-fable.md):** G3 close; G10 confirm; G11 follow-up plan (`probe --only` stays here); G16
    grade both levels before publishing; G14 use the corrected wording above, not Fable's "fail open" text. Resolved;
    not owner rulings. G1, G2, G4, DEFSET and Task 1.4 remain with the owner.
  - **Owner ruling (2026-10-05):** all five resolved — see [OWNER-RULINGS-261005.md](../00483-threat-model-conformance-audit/OWNER-RULINGS-261005.md).
    DEFSET (C1): the action guards are outside the Defence set. G1 (B2): no central exceptions file; suppressions stay
    inline, each with its reasoning, delete as many as possible. G2 (B1): keep the `MUST_*_BECAUSE` hatches with the
    hygiene fixes. G4 (B3): reasons on config exceptions now, required at the next major. Task 1.4 (C2): post.
- [x] ✅ **Task 2.3** (answered by the owner rulings of 2026-10-05, B1–B4 and C1, recorded under Task 2.2; the
  coordinator calls there cover G3, G10, G11, G14 and G16): Put the gaps to the owner as one batch: close, accept as a
  known gap, or out of scope. Expected questions:
  - §4.3 against the `MUST_..._BECAUSE` declarations: is an in-command justification a
    project-record entry, or a suppression route that bypasses it?
  - §6.1/§6.2: is `.claude/hooks-daemon.yaml` (`exclude_paths`, `extra_whitelist`) the project
    record, and must every exception carry a justification?

### Phase 3: Close the gaps and hook in

- [ ] ⬜ **Task 3.1**: Close the accepted gaps through the ledger, at most 3 branches at once.
  G4 (B3) is partly closed: reasons accepted, and asked for under `strict_mode` (warning, not error). Planned for the
  next major (breaking config change): a reason required for every project on `exclude_paths`
  and `extra_whitelist`. `CLAUDE/UPGRADES/` keeps no upcoming-major notes, so it is tracked here.
  - **Worklist** ([report](subagent-reports/261009-task-3.1-gap-worklist-sonnet.md), verified against main): G2 and
    G10 are closed, and G3 and G9 mostly. Still open are G1 (detector), G4 (footer), G5, G6, G7, G8, G11, G12, G13
    and G15. Three batches:
    - **3.1a, identifiers and agent context**: G5, G15, G13, the G9 leftovers (`defect_class` is null in every
      `defences --json` row, and `explain-rule --list` has no footer), and the C1 wording fix. `constants/dbf.py`
      `EXPLAIN_LINE` and the README still call every handler a defence, but ruling C1 puts the action guards outside
      the Defence set.
      **Done (3.1a):** G5 (all nine identifier-less deny paths declare a rule and print `BLOCKED [R-...]`; review round 3
      gave `AutoApproveReadsHandler` its own rule and removed the allowlist, so no deny path is exempt), G15 (`explain-rule` resolves check IDs; `test_rule_parity.py`
      walks every `CHECK_ID`), G13 (`IDs:` line per promoted section), G9 (`defect_class` from a declared
      `Handler.defect_class`; `explain-rule --list` footer) and the C1 wording (`EXPLAIN_LINE`, README; `defences`
      lists only the handlers that declare a defect class). Evidence in [CONFORMANCE.md](CONFORMANCE.md); report in
      [the 3.1a report](subagent-reports/261009-task-3.1a-identifiers-sonnet.md). Review round 1
      ([review](subagent-reports/261009-00484-3.1a-review-r1-opus.md)) addressed: `DefectClass` is a closed
      `StrEnum` with a pinned Defence set, `STATEMENT` constants for the QA checks, a deny-carries-an-ID pytest
      plugin (D4.3 now MET for the handler engine), and the Defence membership rulings (coordinator's, not the
      owner's: the post-write linters and `tdd_enforcement` out, `github_auto_close_keywords` in). Merged at
      `758b76a41` after three review rounds, the third verified by the coordinator.
    - **3.1b, QA layer**: the G1 detector (reasons inline, no baseline file, per B2), G6, G7 and G8.
      **Done (3.1b):** G1 (`check_inline_suppressions.py`, six reasonless lines fixed), G6 (`qa-rules.json` and
      `llm_qa.py --explain`, guarded both ways), G7 (runners after detectors; a runner after a failed detector is
      NOT MEANINGFUL) and G8 (first findings with IDs and the absolute report path; `--path FILE` on three
      checkers). Not done: `--path FILE` on the other checkers, and B rows in `hooks-daemon defences` (a
      Defence-membership call for the coordinator). Evidence in [CONFORMANCE.md](CONFORMANCE.md).
    - **3.1c, config and CLI**: the G4 footer, G11 `probe --only`, and G12. Also fix the `exception_entries.py:16`
      docstring, which calls a plain string under `strict_mode` an error. The code makes it a warning.
      **Done (3.1c):** G4 (one router footer asking for a recorded reason; the five inline footers removed), G11
      (`probe --only` checked against every handler the project loads), G12 (`hooks-daemon exceptions`, including
      `pyproject.toml` and `.pre-commit-config.yaml` as a coordinator call), and the docstring. §6.3 graded PARTLY
      MET (inline `nosec`/`noqa`/`type: ignore` not listed). Merged at `bae5d3caf` after two review rounds
      ([report](subagent-reports/261009-task-3.1c-config-cli-sonnet.md)).
    - **3.1d, follow-ups from the three batches**: `defences` gives a project handler no `--only` entry point (its
      event is filed as `project`; see CONFORMANCE G11); `test_single_disable_footer.py` names five files instead
      of globbing every handler; `core/chain.py` compares `probe_only` before normalising dashes; `--path FILE` on
      the remaining checkers; and B rows in `hooks-daemon defences`.
      **Done (3.1d):** project handlers get their real event and config key in `defences` (end to end on this
      repository), the footer test covers every handler file (200, by glob), dashes are normalised once in
      `probe_only_handler`, and `--path FILE` is on `check_british_english.py`; the other checkers are skipped with
      reasons in CONFORMANCE G8. Merged at `41f5db964` after one review round
      ([report](subagent-reports/261010-task-3.1d-follow-ups-sonnet.md)). B rows were left for a ruling.
    - **Coordinator call (B rows), not an owner ruling:** rows only for the batch checkers that are the batch form
      of a write-time Defence handler (`audit_error_hiding`, `check_sensitive_content`,
      `check_inline_suppressions`), each with the same defect class and an `llm_qa.py` entry point.
      `check_british_english` was first listed and then dropped: its handler is advisory and declares no defect
      class, because a spelling convention is not a defect. This
      keeps a Defence tied to a defect class, as ruling C1 does; every checker as a row would make "Defence" mean
      any gate, and no rows would leave §5 short.
    - **3.1e**: those four B rows (with the `Defence` schema fields they need), and the 3.1d review's should-fix
      items: `cmd_defences` loads project handlers twice (`daemon/cli.py:3647-3650`), and the end-to-end test wires
      its own probe check instead of calling `cmd_probe` with sending stubbed out.
      **Done (3.1e):** `batch_defences` in `scripts/qa/qa-rules.json` names each checker's handler; `defences` lists
      one `kind: batch-check` row per defect rule (16 on this repository; `meta: true` plumbing rules excluded, rule
      IDs unique), takes the defect class from the handler's active row, and drops the rows when that handler is off.
      Project handlers are discovered once; the end-to-end test calls `cmd_probe`. §5.3 (project) PARTLY MET. Merged
      at `8098503d7` after two review rounds ([report](subagent-reports/261010-task-3.1e-b-rows-sonnet.md)).
    - **3.1f**: the three 3.1e nits. `defences` checks the registry is an object before collecting, no longer
      catches `AttributeError`/`TypeError`, and on an unusable registry prints one stderr line, still lists the
      handler rows and exits 1 (the registry is broken, so the failure stays visible). An invalid configured regex
      has its own `meta` rule, `public-pattern-invalid`, in both sensitive-content checkers. The 3.1e report's item 1
      names `handler`. ([report](subagent-reports/261010-task-3.1f-nits-sonnet.md))
  - **Coordinator call (under the owner's "go with the clear winners" instruction):** G5–G9, G12, G13 and G15 were
    never put to the owner. Closing them is the default, so they are closed through the batches above. Resolved; not
    an owner ruling. Success criterion 3 ("the owner has ruled on every gap") therefore waits on the owner to confirm
    these calls and the earlier ones for G3, G10, G11, G14 and G16.
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

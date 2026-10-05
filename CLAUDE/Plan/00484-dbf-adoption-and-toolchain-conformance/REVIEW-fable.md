# Plan 00484 Task 2.2: Fable review of CONFORMANCE.md

Reviewed against TOOLING-SPEC 0.2.0 §4–§9, DETECTOR-SPEC 1.0.0 and SPEC 1.0.1 (vendored copies),
and the threat model in `CLAUDE/ARCHITECTURE.md` and README "Guardrails, not armour". Every MET
and PARTLY MET citation was reopened at the cited line on `main`; the cheap commands
(`explain-rule --list`, `explain-rule <ID>`, `explain-handler --list`, `probe --help`) were rerun.
Nothing was written outside this file.

## Verdict

**Reliable, and strict in the right direction.** Of 29 TOOLING rows at two levels and 46
DETECTOR cells, I correct five grades and three evidence figures. Four of the five corrections
move a grade DOWN, so the assessment is not generous overall; the one that moves UP is on a
clause where the cited evidence was wrong. Neither verdict changes: project level and artefact
level are both not conforming, and the artefact-level blockers stay 4.1, 4.3 and 6.2.

The one material miss is a class of identifiers the assessment never looked for: the 52
`CHECK_ID`s of the plan-QA and docs-QA sub-checks, which the daemon prints in deny reasons and
which `explain-rule` cannot resolve. That is exactly the "rule that blocks without explaining"
class TOOLING 8.1 exists to catch, and it was missed because the search was for `R-…` strings
only.

## Grade corrections

| Clause                     | Assessed             | Corrected                   | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| -------------------------- | -------------------- | --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 4.2a (artefact)            | MET                  | **PARTLY MET**              | Plan-QA and docs-QA findings are rendered as `- [block] <check_id> …` (`plan_qa/report.py:30`, `docs_qa/report.py:40`) inside the `R-PLAN-QA-EDIT`/`R-DOCS-QA-EDIT` deny reason. There are 52 `CHECK_ID` constants across `plan_qa/checks/` and `docs_qa/`. `bin/hooks-daemon explain-rule plan-doc-size` → `ERROR: unknown rule ID`. DETECTOR 6.1 says a Message that carries its own remediation resolves the Message, not the Identifier; the identifier presented alone must resolve        |
| 8.1 (artefact)             | MET                  | **PARTLY MET**              | `test_rule_parity.py` audits `Rule` objects from `get_rules()` only (`:162-227`). The 52 check IDs are printed by bundled rules and are outside that audit; no release check guards them. 8.1 covers "every Identifier printed by a Rule the Toolchain … bundles … whatever kind of Detector carries it". DETECTOR 6.5 offers the fix: a family page per umbrella rule listing every member in the installed file                                                                               |
| D6.1 (A)                   | MET                  | **PARTLY MET**              | Same evidence. D6.3 and D6.4 for A fall with it                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| D4.1 (D row)               | NOT MET              | **N/A**                     | `CLAUDE/Security/README.md:15-19` names only `scripts/qa/check_*.py` as Defences; no Defence is routed through ruff, mypy, pyright, bandit or shellcheck. TOOLING 4.1 point 3 lets such a detector "still run as one of the Toolchain's checks, as a formatter or a Runner does", blocking included. G10 is therefore a declaration note, not a gap (see below). 4.1 overall stays NOT MET on A and B                                                                                           |
| 4.3b (artefact)            | NOT MET              | **PARTLY MET**              | The assessment says the hatches send the agent "never to the config". Every deny message ends `To disable: handlers.<event>.<key> (set enabled: false)` — the assessment itself quotes this under 6.2. That IS a direction to the project record (`.claude/hooks-daemon.yaml`), for the whole rule rather than an instance, and with no justification asked — which is 6.2's failure, not 4.3b's. Project level stays NOT MET: `# nosec`, `# shellcheck disable` and B's markers direct nowhere |
| 4.3a evidence              | "232 `# nosec`"      | **62 honoured, ~173 inert** | `run_security_check.sh:38`: `BANDIT_TARGETS=("src/" ".claude/ccy/claude-supervise.py")`; pyproject.toml:266-282 confirms all three bandit surfaces scan `src/` only. 59 `nosec` in `src/` (28 files) + 3 in `claude-supervise.py` are honoured; the ~173 in `tests/` and `scripts/` are never read. All 62 carry a test ID (`# nosec B603 …`), none is bare, and most carry a prose reason. Grade unchanged; G1's size and remedy change                                                        |
| 7.1 evidence               | "96 of 121; 25 lost" | **95 of 121; 24 promoted**  | The 96 includes a false match (`R-4`). 26 IDs are absent from CLAUDE.md: 24 belong to the 11 `promoted_handlers` (config:75-86); 2 are DORMANT and correctly absent — `R-MERGE-TO-MAIN-APPROVAL` (option default `False`, `models.py:2053`, unset in config) and `R-PLAN-CLOSE-APPROVAL` (`close_requires_human_approval: false`, config:1400). Grade unchanged; G13 is 24 IDs. Bonus for 5.1a: `explain-rule --list` lists both dormant rules, so it is not active-only on that axis either    |
| D4.3 (A) "nine deny paths" | a count              | **a lower bound**           | I found no test asserting that every `Decision.DENY` `HookResult` carries `BLOCKED [R-`; the parity test checks declared-rule renderings, and `test_allow_never_carries_deny_headline.py` guards the opposite direction. A handler that declares three rules can deny on a fourth path with none. Grade unchanged (PARTLY MET); the known-gap text should say "at least"                                                                                                                        |

Grades I reopened and confirm as stated: 4.2b, 4.2c, 4.2d, 4.4b (artefact), 5.1a, 5.1b, 5.2, 5.3,
6.1, 6.2a, 6.2b, 6.3, 6.4, 7.2, 8.2, 9, every 4.3 inventory row I could check
(`git_stash.py:38-41`, `root_recursion_guard.py:55-58`, `ancestry_preserving_merge.py:39-42`,
`bash_safe_mode.py:66,260` — a bare substring, no `=` even required — `comment_size.py:104-130`,
`plan_doc_size.py:111-123`, `verdict_log.py:196-209` with `handler: None, rule: None`), the
`llm_qa.py` citations (registry order with `tests` 6th, `DEVNULL` at `:1366-1367`, metric-only
summaries at `:1424-1425`, no short-circuit at `:2622-2658`), `lookup.py:84-88` (classes built with
no config), `docs_generator.py:324-329` against `registry.py:244-262`, `HandlerConfig` at
`models.py:58-78`, `never_want.reason` default `""` at `:2111`, the five-entry deny allowlist at
`test_rule_parity.py:328-354`, and the four rule-less project deny handlers
(`ruff_format_blocker` ×2, `enforce_llm_qa` ×3, `plan_done_requires_holding_area` ×2,
`release_blocker` ×1 `Decision.DENY`; zero `Rule(`).

**5.1c (artefact) MET is defensible but thin.** `explain-rule --list` rows carry no docs route;
the route is one header line in the injected CLAUDE.md. A consumer who runs `--list` directly
gets no pointer. Add a footer line under G9 rather than regrade.

**8.2 MET carries a caveat the assessment should state.** `test_dogfooding_config.py:134-140`
hand-exempts two opt-in handlers. Both ship disabled, so neither is a Bundled defence under
TOOLING §2, and the grade holds — but the exemption list is hand-maintained, which is the 5.2
failure shape applied to a self-audit.

## Missed clauses and missed evidence

Every MUST and SHOULD in TOOLING §4–§9 is in the summary table; I enumerated them against the
text and found no omitted clause. What was missed is evidence, not clauses:

1. **The 52 check identifiers** (above). This also adds a row to the 4.3 inventory: a plan-QA
   or docs-QA finding is silenced by `mode: warn` or `enabled: false` on the umbrella handler,
   which is in the record — so no new bypass route, but the IDs are the gap.
2. **`qa_suppression` does not cover `# nosec`.** `strategies/qa_suppression/python_strategy.py:12-18`
   forbids `type: ignore`, `noqa`, `pylint: disable`, `pyright: ignore`, `mypy: ignore-errors`.
   `nosec` has no hook-time defence at all, which makes G1 the only inline route with zero
   coverage at either placement. `# noqa` and `pyright: ignore` occur 0 times in the tree
   (the hook works); `type: ignore` occurs 23 times in `tests/` and 3 in `src/` (honoured by
   mypy), which is the assessment's own "placement matters" argument in numbers.
3. **4.3's `-->` defect is in `comment_size`, not `plan_doc_size`.** `plan_doc_size.py:118-121`
   strips `-->`; `comment_size.py:126-130` does not strip `-->` or `*/`. G2/G3 should name the
   right handler.
4. **shellcheck scope.** `run_shell_check.sh:42-58` scans `scripts/` and `src/`; the five
   `.claude/skills/**` copies with `shellcheck disable` are deployed duplicates of `src/` skills
   and are not scanned. The 19 figure is right for the scanned roots.

## Scope problems

1. **The assessment never says which handlers are DBF Defences.** It grades "the handler engine"
   as Detector A, but SPEC defines a Detector as reading CODE and Blocking as preventing a
   CHANGE from being accepted. `destructive_git`, `pipe_blocker`, `git_stash`, `bash_safe_mode`
   and the other action guards judge a command, not code, and deny a tool call, not a change.
   Whether they are Defences in the spec's sense is a ruling, and every column-A grade and the
   whole of G2 reads differently depending on it. The declaration must name the Defence set.
   Recommended set: the deny-mode handlers that judge file or commit CONTENT
   (`qa_suppression`, `error_hiding_blocker`, `security_antipattern`, `comment_changelog`,
   `comment_size`, `sensitive_content`, `lint_on_edit`, `tdd_enforcement`, the staged-lint,
   conflict-marker, plan-QA and docs-QA commit gates), with the action guards declared as
   guardrails outside the DBF Defence set. That is consistent with Plan 00259 Decision 2, which
   already confines in-band hatches to actions "whose consequences stay inside the repository".
2. **`method = "1.0.1"` in the draft declaration is an ungraded claim.** TOOLING 9.1 grades a
   project "against this document AND section 7 of the method specification". SPEC §7 says a
   project Conforms if its Defences satisfy 3.1, 3.2, 3.3, 3.5, 3.6 and its recorded decisions
   are discoverable. The assessment grades TOOLING only. Either grade SPEC §7 (cheap: the five
   `CLAUDE/Security/` Defences plus the handler docs) or declare `method` with a known-gap
   line "method-level conformance of existing Defences not assessed".
3. **The draft omits `detector`.** 9.1: a project that ships a Detector is graded "a Detector
   against the detector specification". The handler engine is shipped to consumers and is
   graded in the matrix; the declaration should carry `detector = "1.0.0"` with its D4.2, D4.3,
   D5.2 and D6.1 gaps, or say why it is not a Detector.
4. **In scope, correctly.** Threat-model points 1–4 are right: closing 4.3 by a tree scan under
   `llm_qa.py` judges content not motive; the fail-open note is required and the draft carries
   it; regex hardening against a token inside an `echo` is a hostile shape and stays out; the
   6.2 check cannot verify truth and the declaration must not imply it. No proposed closure
   claims defence against a hostile agent or prompt injection.
5. **One closure is misfiled.** G2's "record handler, rule and reason in the verdict log" is
   telemetry: the log is untracked and capped at 10 MiB (`verdict_log.py:160-162`). It cannot
   satisfy any 4.3 or 6.x clause and should not be listed as part of closing them.

## Gaps G1–G14

| Gap | Recommended option right? | Correction                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| --- | ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| G1  | Yes, resized              | 62 live markers, not 232. Bandit has no per-line config route, so "move each into a reasoned record" means a sidecar file the wrapper applies: run bandit with `--ignore-nosec`, filter against `scripts/qa/bandit_exceptions.json` `{file, test_id, reason}`, and fail any `# nosec` in the scanned roots. Delete the ~173 inert markers in `tests/` and `scripts/`: each claims a suppression nothing reads. Add `type: ignore` ×26 to the same detector; `shellcheck disable` ×19 likewise                                                                                                                          |
| G2  | Reframe                   | The question as posed ("is a one-shot command an Exception?") has a spec answer already: SPEC §4, "nothing an Agent concludes on its own creates one". The real ruling is scope problem 1: are the four command hatches on Defences at all? If outside the Defence set, 4.3 no longer reaches them and the artefact-level in-band routes shrink to the two in-file tokens (G3). Either way: close the no-reason hatch (`bash_safe_mode.py:260`), the `-->`/`*/` closer defect (`comment_size.py:126-130`) and the whole-file-on-Write scope, and apply the 6.2 generic-reason check to all six — hygiene, not a ruling |
| G3  | Yes: close                | Both tokens are inline suppressions on content and live in tracked files; `find-comment-blocks` already lists them. Closing is cheaper than writing the known-gap line                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| G4  | Yes, one addition         | The project already has `strict_mode`. Require the reason under strict mode first, then at the next major. That turns the phased plan into something the dogfooding config enforces now                                                                                                                                                                                                                                                                                                                                                                                                                                |
| G5  | Yes                       | Add: extend the parity test to assert every `Decision.DENY` result carries an ID (the lower-bound point above); otherwise the nine is never shown to be the whole set                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| G6  | Yes                       | —                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| G7  | Yes                       | Keep running every tool (the coordinator wants one run, all results); mark runner results `not meaningful: detector failed` and exclude them from the pass count. The spec asks that they not be "treated as meaningful", not that they not run                                                                                                                                                                                                                                                                                                                                                                        |
| G8  | Yes                       | —                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| G9  | Yes                       | Add a footer to `explain-rule --list` naming `explain-rule <ID>` (5.1c)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| G10 | Not a gap                 | Reclassify as a declaration note. Nothing is routed through D (`CLAUDE/Security/README.md`), so 4.1 point 3 is satisfied, not excused. The owner confirms the statement; no acceptance is needed                                                                                                                                                                                                                                                                                                                                                                                                                       |
| G11 | Yes                       | `probe --only <handler>` is a plan task. The `scan <handler> <paths>` mode is a new surface with its own design (dormancy, options, exclude_paths); recommend a follow-up plan unless the owner wants DBF-tool sweeps from this one                                                                                                                                                                                                                                                                                                                                                                                    |
| G12 | Yes                       | —                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| G13 | Yes                       | 24 IDs, not 25                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| G14 | Yes                       | Out of scope, stated in the declaration. Add the Defence-set statement (scope problem 1) to the same note                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |

### New gaps

| ID  | Gap                                                                                                                   | Clauses          | Recommendation                                                                                                                                                                                                                            |
| --- | --------------------------------------------------------------------------------------------------------------------- | ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| G15 | 52 plan-QA/docs-QA `CHECK_ID`s are printed in deny reasons and resolve nowhere; the release audit does not cover them | T4.2, T8.1, D6.1 | **Close.** Register each check as a member of its umbrella rule (DETECTOR 6.5 family form: the list lives in the installed `Rule`), make `explain-rule <check_id>` resolve, and extend `test_rule_parity.py` to walk `CHECK_ID` constants |
| G16 | `method` declared without a SPEC §7 grade; `detector` not declared                                                    | T9.1, T9.2, D8.1 | **Close** before Task 3.3: grade SPEC §7 for the Defences in `CLAUDE/Security/` and declare `detector = "1.0.0"` with the matrix's A-column gaps                                                                                          |

## Owner batch

One line per decision. Everything not listed is a close within the plan's existing scope
(G5, G6, G7, G8, G9, G12, G13, G15) and needs no ruling.

- **Defence set (decides G2, G14 text):** Are the action guards (destructive git, stash,
  squash, pipe, sed, safe-mode, root-scan) DBF Defences, or guardrails outside the Defence set?
  — Recommended: **outside**; declare the content and commit gates as the Defence set.
  **Owner ruling (2026-10-05):** outside the Defence set; resolved — see [OWNER-RULINGS-261005.md](../00483-threat-model-conformance-audit/OWNER-RULINGS-261005.md) (C1).
- **G1:** Close by moving the 62 live `# nosec` into a wrapper-applied record file with reasons,
  deleting the ~173 inert markers, and failing any inline `nosec`/`type: ignore`/`shellcheck disable` under `llm_qa.py`? — Recommended: **yes**.
  **Owner ruling (2026-10-05):** NO central record file; suppressions stay inline, each with its reasoning, and as many as possible are deleted — see [OWNER-RULINGS-261005.md](../00483-threat-model-conformance-audit/OWNER-RULINGS-261005.md) (B2).
- **G2:** Keep the four command hatches (if outside the Defence set) with the no-reason and
  closer defects fixed and the generic-reason check applied; if inside, declare them a known
  gap? — Recommended: **keep, fix, outside**.
  **Owner ruling (2026-10-05):** keep and fix; resolved — see [OWNER-RULINGS-261005.md](../00483-threat-model-conformance-audit/OWNER-RULINGS-261005.md) (B1).
- **G3:** Close the two in-file `MUST_EXCEED_*_BECAUSE` tokens by listing and reason-checking
  them, or accept as a known gap? — Recommended: **close**.
  **Resolved.** **Coordinator call (2026-10-05, under the owner's "go with the clear winners" instruction):** close.
- **G4:** Accept `{pattern, reason}` alongside bare strings now, require the reason under
  `strict_mode`, and make it mandatory at the next major? — Recommended: **yes**.
  **Owner ruling (2026-10-05):** yes; resolved — see [OWNER-RULINGS-261005.md](../00483-threat-model-conformance-audit/OWNER-RULINGS-261005.md) (B3).
- **G10:** Confirm the statement "no DBF Defence is routed through ruff, mypy, pyright, bandit
  or shellcheck; they run as checks" for the declaration? — Recommended: **confirm**; not a gap.
  **Resolved.** **Coordinator call (2026-10-05, under the owner's "go with the clear winners" instruction):** confirm.
- **G11:** Build the `scan <handler> <paths>` sweep mode in this plan, or file it as a
  follow-up? — Recommended: **follow-up**; `probe --only` stays here.
  **Resolved.** **Coordinator call (2026-10-05, under the owner's "go with the clear winners" instruction):** follow-up plan; `probe --only` stays in this plan.
- **G14:** State in the declaration that hook-time defences deny a tool call, fail open, and are
  not the acceptance gate? — Recommended: **yes**, verbatim from the threat model.
  **Resolved.** **Coordinator call (2026-10-05, under the owner's "go with the clear winners" instruction):** use the coordinator's corrected wording (PLAN.md, Task 2.2), not the "fail open" text above, because it matches the code: defences fail closed except in the named setup states (not installed, venv missing, version mismatch, repository unconfigured, CI), per `.claude/init.sh`.
- **G16:** Grade SPEC §7 and declare `detector` before publishing, or publish `toolchain` only
  with "method and detector levels not assessed" as known gaps? — Recommended: **grade both**;
  it is a short job and the declaration is the claim.
  **Resolved.** **Coordinator call (2026-10-05, under the owner's "go with the clear winners" instruction):** grade both before publishing.

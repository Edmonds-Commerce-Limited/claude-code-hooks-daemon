# Fable review of CONFORMANCE.md (Success Criterion 2)

Reviewed against HEAD `fa40a06f0`, the vendored `remote-docs/defence-before-fix.github.io/raw/TOOLING-SPEC.md`
(TOOLING 0.2.0) and `DETECTOR-SPEC.md` (DETECTOR 1.0.0). Read-only: no code or tracked file other than this
report was changed. Commands run from `/workspace`: `bin/hooks-daemon defences --json`,
`bin/hooks-daemon exceptions --json`, `bin/hooks-daemon explain-rule --list`,
`bin/hooks-daemon explain-rule <ID>`, `./scripts/qa/llm_qa.py --explain <ID>`, plus greps and reads.

## Verdict: SURVIVES WITH FIXES

The grading is honest in direction (strict, two levels, no conformance claim), the table covers every MUST and
SHOULD in TOOLING §4–§9, and the final verdicts (both levels not conforming) are right. But the document is a
palimpsest: the summary table was updated batch by batch while the per-clause detail, the §4.3 route table, the
DETECTOR notes, the grade counts, the freshness section, the surfaces table, the gap table and the draft §9.2
declaration were not. The result contradicts itself in several places, states one tree hash and one spec
version that are no longer true, and has one real generous grade (the project's own Semgrep rules resolve
nowhere) that the §4.2 / D6.1 rows hide. None of this changes a verdict; all of it must be fixed before Task 3.3
publishes the declaration, because the known-gap text as drafted lists gaps that are closed and omits the ones
that remain.

## 1. Coverage

**Every MUST and SHOULD in TOOLING §4–§9 has a row.** I walked the spec: 4.1 (MUST NOT route; three points),
4.2 (resolve / ship together / place to live / correct construction = rows a–d), 4.3 (forbid / direct to record
= a, b), 4.4 (D5.1–5.4 / print unaltered = a, b), 4.5 (order / stop = a, b), 5.1 (list / ID+statement / route =
a–c), 5.2, 5.3, 6.1, 6.2 (require+no default+reject omission = a; hazard+scope+generic check = b), 6.3, 6.4
SHOULD, 7.1 SHOULD, 7.2 SHOULD, 8.1 (+ family pattern = 8.1f), 8.2, 9 (partial MUST NOT be called
conformance), 9.1, 9.2. DETECTOR §4–§7 rows are all in the matrix, including the SHOULDs (4.4, 6.4, 6.5, 7.2).

Two spec obligations have no row and should get one line each (not a new grade, a stated placement):

- TOOLING §6.2 last paragraph: "a Toolchain's Conformance MUST NOT be read as having verified \[the reason's
  truth\]". It is only in Threat-model point 4. Say in the 6.2b row that the declaration will carry this
  wording.
- TOOLING §4.3 second paragraph: a Baseline "is never a file the Detector generates unseen". Covered
  implicitly (owner ruling B2: no baseline file), but the 4.3a row should say "no baseline file exists".

No table row is outside the spec. `8.1f` is a sub-clause of 8.1 and `9` is the §9 preamble; both are
legitimately graded.

**Scope gap in the detector routing table (§"What is graded", row C).** It says "9 bespoke rule IDs in 6 rule
files". `scripts/qa/semgrep/` has 7 YAML files carrying 10 `id:` values (`bounded-reads.yaml` alone has 4).
Correct the count; it feeds finding 2.1.

## 2. Evidence spot-checks (16 rows)

| Row / claim                                                                                                                                  | Checked                                                                                                                                                                                                                                                        | Result                                                                                                                                                                                                                                                                      |
| -------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Header: "current tree on `main` (734695b9b)"                                                                                                 | `git log -1` → `fa40a06f0`                                                                                                                                                                                                                                     | **Stale.** Six batches merged since; pin the hash the review is of                                                                                                                                                                                                          |
| Freshness: "fetched 2026-09-15, stale_after 2026-12-14", "hashes to `64d5dc76…bd3`", "SPEC 1.0.1"                                            | TOOLING-SPEC frontmatter: `fetched_at 2026-10-08`, `stale_after 2027-01-06`, `source_sha256 e88f22b5…`; SPEC.md says "Version: 1.1.0, published 2026-10-02"; refetched in `d95727b89` (v3.69.0 Step 1H)                                                        | **Stale, and material.** The method spec moved 1.0.1 → 1.1.0 after this section was written. The draft declaration's `method = "1.0.1"` is wrong. Re-run the freshness check and say what changed in SPEC 1.1.0 (TOOLING 0.2.0 and DETECTOR 1.0.0 are unchanged in version) |
| Row A: "121 rule IDs (`explain-rule --list`)"; surfaces table "121 rows", "96 of 121"; Method notes "121"                                    | `explain-rule --list` prints 140 IDs; CLAUDE.md carries 138 of them (missing: `R-MERGE-TO-MAIN-APPROVAL`, `R-PLAN-CLOSE-APPROVAL`)                                                                                                                             | **Stale** in four places. Replace 121 → 140 and 96/121 → 138/140, and say why the two are absent (presumably project handlers not promoted, or disabled)                                                                                                                    |
| 4.2a project PARTLY MET: "the rest of the gap is the wrapped third-party tools' own identifiers"                                             | TOOLING §4.2 explicitly excludes third-party native catalogues ("not re-shipped here"); BUT `llm_qa.py --explain pathlib-quadratic-containment` → exit 1 "no scripts/qa checker prints rule"; `explain-rule pathlib-quadratic-containment` → "unknown rule ID" | **Wrong reason, right grade.** The remaining 4.2a gap is NOT third-party IDs (out of scope) but the project's own 10 Semgrep rule IDs, which resolve nowhere. State that; it is a real, undeclared gap                                                                      |
| Matrix C D6.1 MET; 4.2 detail "Semgrep rule IDs, which are theirs to document"                                                               | Same as above. The 10 IDs are the PROJECT's rules (`scripts/qa/semgrep/*.yaml`), not Semgrep's catalogue; D6.1 for a project rule = "print unaltered, lookup is the Toolchain's" (TOOLING 4.2)                                                                 | **Too generous at the TOOLING level.** C D6.1 MET is defensible for the detector alone (it prints the ID unaltered), but the toolchain row 4.2a must count these as unresolved, and 5.3 must note no listing carries them                                                   |
| 4.3 route table: `MUST_SKIP_SAFE_MODE_BECAUSE` "**None.** A bare substring test (`bash_safe_mode.py:260`)"                                   | `bash_safe_mode.py:331` → `command_declares_hatch(command, _ESCAPE_HATCH)`; `utils/escape_hatch.py:76-82` applies `is_acceptable_reason`                                                                                                                       | **Stale and contradicts G2's own "CLOSED" status.** Row must say "reason required; generic reasons rejected (`is_acceptable_reason`)"                                                                                                                                       |
| 4.3 route table: `-->` or `*/` counts as a reason (`comment_size.py:104-130`)                                                                | `comment_size.py:48` imports `is_acceptable_reason`; `:433` deny text says a closer alone is not a reason                                                                                                                                                      | **Stale**, same as above                                                                                                                                                                                                                                                    |
| 4.3 route table: `# nosec` "232 uses (28 files in src/)"; `shellcheck disable` "19"; `type: ignore` "23"                                     | Current tree (excluding `tests/fixtures/cyber-flag`): 56 `nosec`, 24 `shellcheck disable`, 6 `type: ignore`, 11 `pragma: no cover`, 0 `noqa`; SUPPRESSIONS.md says 78 kept; the 4.3a table row says 113                                                        | **Three different inventories in one document.** Pick one counting rule, run it once at the pinned hash, and use it in the route table, the 4.3a row, G1 and SUPPRESSIONS.md                                                                                                |
| A D7.2 (SHOULD) PARTLY MET: "Five of the six hatches need some text. One needs none. None rejects a generic reason"                          | `escape_hatch.is_acceptable_reason` is shared by all six hatches (G2 status, and the code above)                                                                                                                                                               | **Too harsh / stale.** Should be MET (or state what still fails)                                                                                                                                                                                                            |
| A D4.4 (SHOULD) PARTLY MET: "covers the library package only. Project handlers are outside it, which is why four of them deny without an ID" | `tests/unit/test_rule_parity.py:446-475` walks `.claude/project-handlers`; `test_every_denying_project_handler_declares_rules`                                                                                                                                 | **Too harsh / stale.** Should be MET; G5 status in the same document says so                                                                                                                                                                                                |
| A D4.2 PARTLY MET detail: "No route runs one rule alone against supplied input"                                                              | `probe --only <handler>` exists (`synthetic_traffic.py:185`, `chain.py:1073`), G11 marked closed in the same document                                                                                                                                          | **Stale.** Re-grade: `probe --only` is a single-handler harness over a supplied payload. What remains is a "sweep the tree" mode (D5.2), not a harness (D4.2). Note the line cited (`chain.py:1100`) is now 1073                                                            |
| 6.2a NOT MET evidence: `models.py:58-78`, `enabled: bool` at `:72`, `never_want.reason` default `""` at `:2111`                              | `HandlerConfig` is at `:65-80` (`enabled` at `:79`); `NeverWantToolConfig.reason` default `""` at `:2156`                                                                                                                                                      | **Grade correct, lines drifted.** `enabled: false` and `mode: warn` still carry no reason field and `reason` still defaults to `""`, so NOT MET stands                                                                                                                      |
| 6.2 detail: "Every deny message ends with 'To disable: … (set enabled: false)'"; "Exceptions in the live config carry no reason field"       | `core/router.py:38` → `"(set enabled: false and record why beside it)"`; `{pattern, reason}` accepted since G4                                                                                                                                                 | **Stale prose** contradicting the G4 status below it                                                                                                                                                                                                                        |
| 6.3 detail: "No command lists exceptions with their justifications, the in-file hatches, or B's exception files"                             | `hooks-daemon exceptions --json` returns 29 keys including those; `exceptions_listing.py:39` `QA_EXCEPTION_FILES`                                                                                                                                              | **Stale prose** contradicting the 6.3 table row and G12 status                                                                                                                                                                                                              |
| 6.1 project PARTLY MET; detail: "The record does not name them, and neither does any other file"                                             | `QA_EXCEPTION_FILES` names them; `exceptions` lists them; each script loads its own                                                                                                                                                                            | **Unexplained PARTLY.** Either say what is still missing (the record itself, `.claude/hooks-daemon.yaml`, does not name B's files; a constant in `src/` does) or raise to MET                                                                                               |
| 5.1a/b/c PARTLY MET at both levels, with `defences --json` cited as evidence                                                                 | `defences --json`: 48 rows (32 handler, 16 batch-check), every row has `rule_id`, `statement`, `docs`, `defect_class`; active-only via `DocsGenerator.active_handlers`                                                                                         | **Grade not justified by the row.** Under ruling C1 the Defence set IS what `defences` lists, so 5.1 is MET for A, and PARTLY only because (i) the 10 Semgrep rules and (ii) `defences` inherits the tag-gate skip (`docs_generator` vs `registry.py:280-285`). Say that    |
| 8.1 "RELEASING.md:285 requires"                                                                                                              | The full gate requirement is at RELEASING.md:292 (step 1b)                                                                                                                                                                                                     | Line drift                                                                                                                                                                                                                                                                  |
| 9 MET: "README and pyproject.toml make no DBF claim at all (checked by grep)"                                                                | README.md:84-95 now has a "Defence Before Fix" section; it names the method and the Defence set and claims no conformance; `pyproject.toml` has nothing                                                                                                        | **Grade correct, evidence stale.** Rewrite: "README names the method and makes no conformance claim"                                                                                                                                                                        |
| 4.5a/b, 4.4b line cites (`llm_qa.py:898`, `:1455`, `:1623-1625`, `:2688`)                                                                    | `RUNNER_TOOLS` :904, `failure_extras` :1463, `resolve_tools` :1672, `explain_rule` :2705, `mark_not_meaningful` :2929                                                                                                                                          | Grades correct; lines drifted. Prefer function names over line numbers throughout                                                                                                                                                                                           |
| D5.2 B: "`check_authored_path_stat.py:300-303` still fails as vacuous on a file"                                                             | `:302-304`: `scan_tree(scan_root) if scan_root.is_dir() else []` then `vacuous_scan_failure`                                                                                                                                                                   | Confirmed; 16 of 32 checkers accept `--path`, matching the G8 narrative                                                                                                                                                                                                     |

**Row 4.1 reasoning.** The evidence column still names "D cannot host bespoke rules" as a reason 4.1 fails. G10
is marked "Accept by declaration: no DBF Defence is routed through them" and the plan records the coordinator's
"G10 confirm". Under TOOLING 4.1 point 3 a detector no Defence is routed through does not fail the clause. The
row should rest on A (D5.2: no tree sweep) and B (D5.2: 16 checkers directory-only), not D. The matrix cell "D
4.1 NOT MET (see gap G10)" should read "not routed (G10)".

**Semgrep as a hidden gap.** This is the one finding that adds a known gap rather than tidying one. The 10
bespoke Semgrep rules block under `llm_qa.py`, carry a `message:` in their YAML, but are keyed on nothing a
practitioner can look up (`--explain` and `explain-rule` both refuse them), and appear in no listing. Either
register them in `qa-rules.json` (with `test_qa_rules.py` discovering YAML `id:` values) or declare it under
4.2 and 5.3 at project level. Today it is declared under neither.

## 3. Known gaps: are they stated plainly?

**The draft §9.2 text (lines 676-704) is now mostly false.** It carries its own "edit after the owner's
rulings" caveat, but the document is the thing Success Criterion 2 names, and the Task 3.3 author will copy
from it. Of the 7 project gaps listed, 4 are closed (4.5; 5.3's "four project handlers"; 4.2's "resolve to no
documentation"; 4.1's "9 deny paths"). Of the 4 artefact gaps, 3 are closed (five handlers without an ID;
`MUST_SKIP_SAFE_MODE_BECAUSE` no reason; "no listing carries identifiers"). The gaps that DO remain are absent
from the draft:

- artefact 4.1 / DETECTOR 5.2: a content handler cannot be run over an existing file or tree (the sole
  remaining reason artefact 4.1 is NOT MET, and the one a consuming DBF tool most needs to know);
- artefact 4.4a PARTLY: same cause;
- project 4.2 / 5.3: the 10 bespoke Semgrep rule IDs resolve nowhere and are listed nowhere;
- 6.2a: `enabled: false` and `mode: warn` carry no reason field; reasons on `exclude_paths` /
  `extra_whitelist` are optional until the next major;
- 6.2b: no generic-reason check on config exceptions (only on the hatches and inline directives);
- 5.2: `explain-rule --list` is not config-derived and every listing skips `enable_tags`/`disable_tags`;
- 4.3 at both levels, in the form owner rulings B1/B2 chose (hatches and reasoned inline directives are kept
  by design) — the draft says "not forbidden" without saying it is a ruling.

The `notes` entry "the hook layer fails open when the daemon does not answer" contradicts PLAN.md's
coordinator correction to G14 (PreToolUse fails CLOSED on an installed project except the recovery command;
fail-open is limited to named setup states and other events; `.claude/init.sh:648-690, 1085-1105, 3142-3165`).
Threat-model point 2 ("The hook layer fails open by design") and the G14 row carry the same error. The
declaration must state the named fail-open states, not a blanket fail-open — the plan already says so; the
document has not been updated.

Gaps hidden in prose rather than the table: the Semgrep resolution gap (prose at line 240 waves it off as
"theirs"); the tag-gate inheritance of `defences` (only in the 5.1–5.3 surfaces table, which omits the
`defences` row entirely); and the `MUST_*_BECAUSE` verdict-log recording that G2 defers to "a separate item"
with no owner.

## 4. Internal consistency

01. **Verdict sentence vs table.** "Seven clauses are NOT MET (4.1, 4.3a, 4.3b, 4.4a, 5.3, 6.2a and 6.2b)" —
    the table grades 5.3 PARTLY MET and the counts row says 6. Delete 5.3 from the sentence.
02. **DETECTOR matrix counts.** Counting the 45 A/B/C cells gives MET 23, PARTLY 10, NOT 2, N/A 10; the table
    says 22 / 11. (B D5.3 was raised to MET "since Task 3.1b" and the count was not updated.) Note the 4.2
    section says "counts 11 PARTLY MET, 6 NOT MET" for TOOLING project, which does match the TOOLING table.
03. **G2 says CLOSED; the 4.3 route table, A D7.2 and Threat-model point 3 still describe the pre-G2 code.**
04. **G4/G12 say closed; §6.2 and §6.3 per-clause detail still describe the pre-G4/G12 code.**
05. **G5 says closed and "no allowlist"; A D4.4 and D5.2-A detail still say four project handlers deny without
    an ID and the parity test covers the library only.**
06. **G11 says closed; A D4.2 detail still says no single-rule route exists.**
07. **D cell in matrix row 4.1 "NOT MET" vs G10 "accept: not routed".**
08. **Three suppression inventories** (route table, 4.3a row, SUPPRESSIONS.md) disagree.
09. **Spec versions**: header says SPEC 1.0.1 while the vendored SPEC.md is 1.1.0; draft declaration repeats
    1.0.1.
10. **"121" vs 140 rules**, "96 of 121" vs 138 of 140, "9 Semgrep IDs in 6 files" vs 10 in 7.
11. **Row 9 evidence** says the README makes no DBF claim; Task 1.1 added a DBF section (it makes no
    conformance claim, which is what matters).
12. **G-numbering**: G15 and G16 are named in PLAN.md and in the Task 3.1a status but have no row in the "Gaps
    for the owner" table (G1–G14). Add rows or a pointer to REVIEW-fable.md.
13. The 5.1–5.3 surfaces table has no row for `hooks-daemon defences`, the surface the summary table relies on.

## Required fixes (in priority order)

1. Re-pin the review: HEAD hash, spec versions (SPEC 1.1.0), fetch date and sha, the 140/138/10/7 counts, one
   suppression inventory.
2. Add the Semgrep rule-ID gap to 4.2a (project), 5.3 (project) and the known-gaps list; or register the IDs.
3. Rewrite the draft §9.2 known-gaps to the post-3.1f state listed in section 3 above, including the
   artefact-level DETECTOR 5.2 gap and the B1/B2 "kept by design" wording, and apply the G14 fail-closed
   correction to `notes`, Threat-model point 2 and the G14 row.
4. Bring the per-clause detail (4.3 route table, 6.2, 6.3, A D4.2, A D4.4, A D7.2, Threat-model point 3) into
   line with the G-status paragraphs; regrade A D4.4 and A D7.2 to MET (or say what still fails).
5. Fix the "seven NOT MET" sentence and the DETECTOR matrix counts (23/10/2/10).
6. Drop D from the 4.1 failure reasons; mark the matrix D cell "not routed (G10)".
7. State what keeps 6.1 and 5.1a–c PARTLY at project level (tag gates; Semgrep; the record not naming B's
   files), or raise them.
8. Add the two missing obligations as one-line rows (6.2 "not verified truth" wording; 4.3 "no generated
   baseline").
9. Replace line-number cites with function names where they have drifted (`llm_qa.py`, `models.py`,
   `chain.py`, RELEASING.md).

Nothing above is outside the threat model; the document's refusal to claim hostile-agent defence is correct
and consistent, apart from the fail-open wording in item 3.

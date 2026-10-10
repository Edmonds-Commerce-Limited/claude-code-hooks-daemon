# Change log: fixes to CONFORMANCE.md after the Fable review

Review: `261010-conformance-fable-review-fable.md` (SURVIVES WITH FIXES). Base `fdd2b8710`. Each fact was
re-derived on the tree before it was written. Edited: `CONFORMANCE.md`, and one reconciliation paragraph in
`SUPPRESSIONS.md`. No code changed.

## Re-derived facts

| Fact              | Value found                                                                                                                                                   |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Pin               | `fdd2b8710`                                                                                                                                                   |
| Vendored specs    | `fetched_at` 2026-10-08, `stale_after` 2027-01-06, TOOLING `source_sha256` `e88f22b5…a27a`; SPEC.md says 1.1.0 (2026-10-02); DETECTOR 1.0.0, TOOLING 0.2.0    |
| Rule IDs          | `explain-rule --list` 140; CLAUDE.md carries 138 (absent: `R-MERGE-TO-MAIN-APPROVAL`, `R-PLAN-CLOSE-APPROVAL`)                                                |
| Semgrep           | 10 `id:` values in 7 files; both `llm_qa.py --explain` and `explain-rule` refuse `pathlib-quadratic-containment`                                              |
| `defences --json` | 48 rows (32 handler, 16 batch-check)                                                                                                                          |
| Suppressions      | `check_inline_suppressions.py` `suppressions_found` 113 = 65 `nosec` + 12 `pragma: no cover` + 36 `shellcheck disable`; 0 `type: ignore`, `noqa`, `nosemgrep` |
| Checkers          | 32 `check_*`/`audit_*`; 16 take `--path`; 4 judge one file (magic_values, error_hiding, shell, british_english)                                               |

## Findings

| Finding                                                               | Action                                                                                                                                                    |
| --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Header pinned to `734695b9b`                                          | Fixed: `fdd2b8710`; line cites replaced by function names throughout                                                                                      |
| Freshness section stale (date, sha, SPEC 1.0.1)                       | Fixed: facts above, with what SPEC 1.1.0 changed (clause 8.7 deferred-fix record); draft `method` is now 1.1.0                                            |
| Counts 121 / 96 of 121 / 9 rules in 6 files                           | Fixed: 140, 138 of 140 with the two absent IDs, 10 in 7                                                                                                   |
| Semgrep IDs resolve nowhere (hidden gap)                              | Declared, not fixed: 4.2a reason rewritten, 5.3 and C D6.1 (now PARTLY MET) noted, new row G17, in the draft known gaps                                   |
| Draft §9.2 mostly false                                               | Rewritten to the real remaining gaps per level; closed gaps removed; B1/B2 "kept by design" wording and the "no baseline" point added                     |
| "Fails open" in notes, threat-model 2, G14                            | Fixed to fail-closed with the named fail-open states, verified in `emit_hook_error` in `.claude/init.sh`                                                  |
| 4.3 route table stale (hatches, nosec/shellcheck/type: ignore counts) | Fixed: hatches reject generic reasons, counts from the tool, `check_inline_suppressions.py` noted                                                         |
| §6.2 / §6.3 detail stale                                              | Rewritten (G4 and G12 facts)                                                                                                                              |
| A D4.2, A D4.4, A D7.2 stale                                          | Regraded MET (`probe --only`; parity test walks project handlers; all six hatches share `is_acceptable_reason`)                                           |
| 6.1 unexplained PARTLY                                                | Kept PARTLY, with the reason stated (the record does not name B's files)                                                                                  |
| 5.1a/b/c justification                                                | Reasons stated (tag-gate inheritance; Semgrep and other B checkers are not rows); artefact 5.1b raised to MET (every `defences` row has ID and statement) |
| 4.1 evidence rests on D                                               | Fixed: rests on DETECTOR 5.2 (A no sweep, B 4 of 32); matrix D cell reads "not routed (G10)"                                                              |
| "Seven NOT MET" sentence, matrix counts                               | Fixed: five NOT MET at project level, four at artefact level; matrix 25 / 8 / 2 / 10; TOOLING project 7/12/5/5, artefact 14/6/4/5                         |
| Row 9 evidence                                                        | Fixed: README names the method, no conformance claim                                                                                                      |
| Two missing obligations                                               | Added: 6.2 "not verified truth" wording in the 6.2b row and the draft; "no baseline file exists" in 4.3a                                                  |
| G15 / G16 had no rows                                                 | Added rows G15 (closed) and G16 (open for Task 3.3); G17 added for Semgrep                                                                                |
| 5.1-5.3 table lacked `defences` row                                   | Added; 121 and 96 of 121 corrected                                                                                                                        |
| Line cites (`llm_qa.py`, `models.py`, `chain.py`, RELEASING.md)       | Replaced by function or section names                                                                                                                     |
| Three suppression inventories                                         | One counting rule (the detector's), used in the route table, 4.3a, G1 and `SUPPRESSIONS.md`                                                               |

## Declined or departed from the review

- **6.2b stays NOT MET (review item 3).** Declined, and regraded the other way: the review says there is
  no generic-reason check on config exceptions, but `config/exception_entries.py` calls
  `is_acceptable_reason` on every `{pattern, reason}` entry and raises a config error. 6.2b is now PARTLY MET
  at both levels, with the reason-less forms (`enabled: false`, `mode: warn`, bare strings) left to 6.2a.
- **B D4.2 left PARTLY MET and C D4.2 fixture-test claim not re-checked**, as the review did not raise them.
- Gap-row G5/G6 etc. keep their original wording above the status paragraphs, as before.

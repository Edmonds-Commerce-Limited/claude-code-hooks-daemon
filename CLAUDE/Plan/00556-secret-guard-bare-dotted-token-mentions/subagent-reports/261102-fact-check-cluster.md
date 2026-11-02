# Fact check: Plan 00556 diff (cluster of #141-#146)

## REFUTED (most consequential first)

- C4 "all of them [#141-#146] land in `secret_file_matching.py` / `secret_file_guard.py`":
  REFUTED for #141. `_AWK_WRITING_PROGRAM_RE` (write_protected_paths.py:156), its use
  (:1118) and `_text_naming` (:642) all live in
  `src/claude_code_hooks_daemon/handlers/pre_tool_use/write_protected_paths.py`. Issue #141's
  own header says "Handler | write_protected_paths". The other five issues do concern
  secret_file_guard. Effect on the plan: Task 3.2 must name `write_protected_paths.py`, and the
  Phase 3 intro should not say all issues are in the two secret files. Task 3.2 also describes
  the fault as only the awk check, but the issue names a second fault: `_text_naming`
  returns the glob for any text when the glob has no literal fragment.

## Claims

| #   | Claim                                                                                                                                                                     | Verdict              | Evidence                                                                                                                                     |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Owner approved fixing every secret-guard false positive (#141-#146), conditioned on every existing true-positive test still denying; journal `122834Z-decision-0dbcad.md` | VERIFIED             | JOURNAL/2026-11-02/122834Z-decision-0dbcad.md, item 1                                                                                        |
| 2   | That decision means option (b) for #145                                                                                                                                   | UNVERIFIABLE-HERE    | The journal does not name (b). Choosing (b) is the plan's inference. The commit message of 9eef1ea58 says "option (b)", but that is history. |
| 3   | GitHub Issue header lists #145, #146, #141, #142, #143, #144                                                                                                              | VERIFIED             | All six exist and are OPEN (gh issue view)                                                                                                   |
| 4   | #146: consumer command with `2>&1` denied, plain `>` allowed                                                                                                              | VERIFIED             | Issue #146 Expected/Observed. Code: secret_file_matching.py:3109 lists `>&`, `&>` as redirections                                            |
| 5   | #141: awk write check reads `>=` and regex `\|` as redirect or pipe                                                                                                       | VERIFIED             | write_protected_paths.py:156 regex `>\|\|&?\|system\s*\(`; issue #141                                                                        |
| 6   | #141 is a "wildcard-only `write_protected_paths` glob" case                                                                                                               | VERIFIED             | Issue #141 title                                                                                                                             |
| 7   | #142: bare `**` judged as dot-matching globstar; `*` and `**/*` inconsistent                                                                                              | VERIFIED (per issue) | Issue #142 body. I did not locate the index code (no `globstar` string in secret_file_matching.py), so the code location is unconfirmed.     |
| 8   | #143: dotted module path in Python string literal treated as file mention                                                                                                 | VERIFIED             | Issue #143. Import-statement exemption exists: `_without_import_module_paths` at secret_file_matching.py:598                                 |
| 9   | #144: grep-pattern-only exemption lost on compound command                                                                                                                | VERIFIED             | Issue #144; `is_grep_pattern_only_mention` at secret_file_matching.py:3335                                                                   |
| 10  | Task 3.5 example `grep 'id_rsa' d; cat id_rsa` must stay denied                                                                                                           | UNVERIFIABLE-HERE    | A requirement, not a current-state claim                                                                                                     |
| 11  | Option (b) "allows the false positive"; existence/index/operand conditions keep `cat app.secret` denied                                                                   | UNVERIFIABLE-HERE    | Describes planned behaviour                                                                                                                  |
| 12  | Phase 1 and Phase 2 sections are ordered with Phase 3 between them                                                                                                        | VERIFIED (cosmetic)  | PLAN.md lines 70, 80, 99: Phase 3 appears before Phase 2                                                                                     |

Counts: 12 items: 8 VERIFIED, 1 REFUTED, 3 UNVERIFIABLE-HERE (item 12 is a layout note, counted among the verified).

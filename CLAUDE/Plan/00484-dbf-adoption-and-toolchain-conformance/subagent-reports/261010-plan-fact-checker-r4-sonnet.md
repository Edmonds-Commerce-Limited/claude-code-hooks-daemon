# Fact check r4: Plan 00484 (narrowed B rows)

Summary: 6 claims: 6 verified, 0 refuted, 0 unverifiable.

| #   | Claim                                                                                                                  | Verdict  | Evidence                                                                                                  |
| --- | ---------------------------------------------------------------------------------------------------------------------- | -------- | --------------------------------------------------------------------------------------------------------- |
| 1   | `audit_error_hiding`, `check_sensitive_content`, `check_inline_suppressions` are the batch form of write-time handlers | VERIFIED | `scripts/qa/` has all three; handlers `error_hiding_blocker`, `sensitive_content`, `qa_suppression` exist |
| 2   | those handlers are Defence handlers with a defect class                                                                | VERIFIED | `defect_class` = `DefectClass.ERROR_HIDING`, `SENSITIVE_CONTENT`, `QA_SUPPRESSION` in the three handlers  |
| 3   | each has an `llm_qa.py` entry point                                                                                    | VERIFIED | `scripts/qa/llm_qa.py` TOOL_REGISTRY entries `error_hiding`, `sensitive_content`, `inline_suppressions`   |
| 4   | `check_british_english`'s handler is advisory                                                                          | VERIFIED | `british_english.py`: `HandlerTag.ADVISORY`, returns `Decision.ALLOW` with context                        |
| 5   | that handler declares no defect class                                                                                  | VERIFIED | grep for `defect_class` / `DefectClass` in `british_english.py`: no match                                 |
| 6   | `check_british_english` was first listed and then dropped                                                              | VERIFIED | the diff removes it from the list (a document-internal fact)                                              |

# Callout: a targeted QA run that selects test files and executes none fails and says why

**Plan**: 00474
**Audience**: operators

`llm_qa.py changed` (the `changed_tests` check) now reports a run that selected test files but executed no tests as a failure that names the pytest exit code, the number of files selected and the tail of pytest's own output, instead of a bare `0 passed, 0 failed, 0 skipped` line. A genuinely empty selection, where no test file maps from the change, is unchanged and is not this failure.

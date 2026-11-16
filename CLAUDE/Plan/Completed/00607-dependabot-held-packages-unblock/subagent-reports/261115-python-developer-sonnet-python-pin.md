# Semgrep interpreter pin (Plan 00607 follow-up)

Defect: under uv, semgrep 1.185.0 on Python 3.10-3.12 has no `semgrep-core`; on 3.13 it does. `uv tool run` without `--python` picked 3.10 here.

Fix:

- New pin file `scripts/qa/semgrep-python.txt` (`3.13`), beside `semgrep-version.txt`.
- `scripts/qa/run_semgrep_check.sh` reads it (override `QA_SEMGREP_PYTHON_FILE`), fails closed with "no semgrep python pinned" when absent or empty, and passes `--python`.
- `tests/support/semgrep_tool.py` does the same and raises `RuntimeError` on a missing or empty pin.
- `.github/actions/setup-env/action.yml` cache key now hashes the python pin. No other caller builds the semgrep command.
- `CLAUDE/QA.md` explains why 3.13 is pinned.

TDD: 6 new tests (`tests/unit/qa/test_semgrep_tool_helper.py`, `TestSemgrepResolution` additions) failed first (6 failed), then passed.

Real gate: after `uv cache clean semgrep`, `bash scripts/qa/run_semgrep_check.sh` exited 0 ("No semgrep violations found"). The five rule-test files, the wrapper tests and the CI action test passed (45 passed).

## 22:33 · decision · — — Semgrep fault does not reproduce; gate passes from main

Written by the session that delivered Plan 00607, which moved semgrep to `uv tool run --from semgrep==1.185.0`.

The "Failed to find semgrep-core" fault recorded at 22:20 does not reproduce in this container at 2026-11-15 ~23:00 UTC. All of the following were run from the main checkout at `4b90e1cd6`:

- `bash scripts/qa/run_semgrep_check.sh` alone: exit 0, "No semgrep violations found".
- Six concurrent `uv tool run --from semgrep==1.185.0 semgrep --version`: all 1.185.0, exit 0.
- Three concurrent full scans (`run_semgrep_check.sh`, each with its own `QA_OUTPUT_DIR`): all exit 0, no violations.
- Main CI run 43766285856 (the semgrep gate and the semgrep rule tests from a fresh venv): success.

The fault was therefore transient, or specific to the environment of the session that hit it. A likely trigger is the `uv cache clean semgrep` racing an in-flight `uv tool run`, but that was not reproduced. The semgrep gate is no longer a reason to hold the branch `agent-a85cf266bd3c1c30d-57f43a44`. Re-run `scripts/qa/run_semgrep_check.sh` on it before the merge. If the fault returns, capture `env`, `uv cache dir` and the full stderr, and record them here.

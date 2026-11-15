# Fact check: Plan 00607 (archived path)

14 claims: 14 verified, 0 refuted, 0 unverifiable.

| #   | Claim                                                                                                            | Verdict  | Evidence                                                                                                                          |
| --- | ---------------------------------------------------------------------------------------------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Commit f4f390f1d is the implementation                                                                           | VERIFIED | `git log`: "Plan 00607: run semgrep from a pinned uv tool env, drop safety..."; ancestor of main                                  |
| 2   | Commit 3076e216c is the review fixes                                                                             | VERIFIED | "Plan 00607 review fixes: rule tests use the pinned uv semgrep..."; ancestor of main                                              |
| 3   | Commit 8d82b3069 declares anyio directly                                                                         | VERIFIED | Subject "Declare anyio as a dev dependency..."; pyproject.toml:63 `"anyio>=4.16"`; ancestor of main                               |
| 4   | Commit 55d78799c holds coverage at 7.13.5 (28.4s vs 9.5s, py3.13 shard)                                          | VERIFIED | Subject matches; pyproject.toml:54-57 `coverage==7.13.5`; ancestor of main                                                        |
| 5   | safety, mcp, opentelemetry-api absent from uv.lock                                                               | VERIFIED | `grep '^name = "<pkg>"$' uv.lock` finds none of the three (semgrep also absent)                                                   |
| 6   | filelock is at 4.2.10                                                                                            | VERIFIED | uv.lock:685-686                                                                                                                   |
| 7   | coverage 7.13.5 in lock                                                                                          | VERIFIED | uv.lock:482-483                                                                                                                   |
| 8   | scripts/qa/semgrep-version.txt exists                                                                            | VERIFIED | Contains `1.185.0`                                                                                                                |
| 9   | tests/support/semgrep_tool.py exists and is the shared helper; the gate runs `uv tool run --from semgrep==<pin>` | VERIFIED | File exists and reads the version file (line 13). run_semgrep_check.sh:62 `tool run --quiet --from "semgrep==${SEMGREP_VERSION}"` |
| 10  | venv.sh adds `--extra dev` only for a self-install                                                               | VERIFIED | scripts/install/venv.sh:1638-1641: `extra_args=(--extra dev)` only when the dir is not `.claude/hooks-daemon`                     |
| 11  | CLAUDE/QA.md notes the pin does not lock transitive dependencies                                                 | VERIFIED | CLAUDE/QA.md:720-729                                                                                                              |
| 12  | CI cache key updated                                                                                             | VERIFIED | .github/actions/setup-env/action.yml:49 hashes `scripts/qa/semgrep-version.txt`; test_ci_setup_env_action.py:49 asserts it        |
| 13  | Main CI run 43766285856 succeeded                                                                                | VERIFIED | `gh run view 43766285856 --json conclusion` returned `{"conclusion":"success"}`                                                   |
| 14  | Open Dependabot alerts are 0                                                                                     | VERIFIED | `gh api '.../dependabot/alerts?state=open' --jq length` returned `0`                                                              |

Supporting checks:

- `safety` is unused. A narrow search for run, import or pin forms outside CLAUDE/Plan and tests/fixtures/cyber-flag found no usage. The only mention is a Routine/00003 run note (CLAUDE/Routine/00003-dependency-updates/RUNS/2026.md) that records `safety` capping filelock.
- pyproject.toml:74-78 comments record why semgrep and safety are absent.
- Plan 00608's journal holds the "Failed to find semgrep-core" record (two entries under CLAUDE/Plan/00608-.../JOURNAL/2026-11-15/).
- subagent-reports/261115-python-developer-sonnet.md exists.
- Not independently verified: runs 43759794234 and 43763172628 failing, the `QA: 43/43 PASSED` count, and the 28.4s/9.5s timings. These come from the commit messages and the plan.
- Not checked: the "19 alerts (1 high, 15 moderate, 3 low)" and "13/4/2" per-package alert counts, which describe past state and cannot be checked from the current tree.

## REFUTED

None.

## 06:24 · finding · — — Task 1.1: real linter run (bundle in place, not installed); probes fixed

`actions-qa` is not on PATH here and was not installed. `gh release download v0.2.0 -R LongTermSupport/actions-qa-ci` fetched `actions-qa-ci_0.2.0_linux_amd64.tar.gz` and `checksums.txt` into `untracked/scratch/aqa-dl/`; sha256 `dd5f6238...694eb2` equals the published one. The bundle holds `bin/actions-qa`, `bin/shellcheck`, `bin/zizmor` and LICENSES. `actions-qa version`: `method 1.1.0, toolchain 0.2.0, 16 known gaps`. (`--version` is not a flag: usage text, then the help names the exits "0 clean, 1 findings, 2 refused, 3 toolchain fault, 4 no verdict".)

Runs in a scratch repository (`git init`), `actions-qa check --file .github/workflows/<f>.yml`, no `--format`:

- `ok.yml` (the strategy's ALLOW probe content): `0 findings`, exit 0.
- `faulty.yml` (job with no `runs-on`): `.github/workflows/faulty.yml:5:3 actionsqaci.actionlint.syntax-check "runs-on" section is missing in job "build"`, `rule-doc actionsqaci.actionlint.syntax-check`, `1 finding`, exit 1.
- `ci.yml` (the Ansible probe's content `on: push` + `jobs: {}`): 3 findings (docsOnlyPush, pushConcurrency, actionlint "jobs section should not be empty"), exit 1.

Same three files at the real acceptance path inside this worktree (`untracked/acceptance/.../.github/workflows/`), run from `/`: all exit 2, `actions-qa: no lane analyses <path>`. A file outside any repository: exit 2, `--file ... is in no repository`. Separating the cause: a non-ignored nested `sub/.github/workflows/x.yml` gives exit 2; a gitignored root `.github/workflows/ignored.yml` gives exit 1. So the tool analyses only the nearest repository root's `.github/workflows/`; gitignore is irrelevant. A run took about 0.03s.

Driven through `lint_on_edit` itself (handler instance, PATH holding only a symlink to `actions-qa`, so the bundle's shellcheck did not shadow anything): with the fixtures in a plain subdirectory all three ALLOW with "did not reach a verdict ... exit 2 ... NOT checked"; with each fixture root `git init`ed, ok ALLOW silent, faulty DENY (R-LINT-FAILURE), and the old Ansible probe DENY.

Changes, test first: each workflow probe's setup now `git init -q`s its fixture root; the Ansible "not claimed" probe carries `CLEAN_WORKFLOW_SAMPLE` (exported by the workflow strategy, measured clean), so its ALLOW holds with or without the linter; a test skipped unless `actions-qa` is on PATH runs every probe's content through the real tool and asserts exit 0 for ALLOW and 1 for DENY (passed here with the bundle on PATH). After the change, driving the handler again: flat ALLOW/ALLOW/ALLOW (unchecked, as designed for a non-root path), nested ALLOW/DENY/ALLOW.

DESIGN.md section 1 records the measured behaviour; section 4.1 now flags for the owner the two builder decisions the design did not name: the commit gate running the linter (Task 2.1) and a nested workflow directory being accepted then refused by the tool with exit 2.

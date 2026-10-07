# Code Review: v3.69.0 release gate, src/ minus core/, daemon/, handlers/

Scope: `git diff v3.68.0..HEAD -- src/ ':!core/' ':!daemon/' ':!handlers/'`. That is 65 files, +5327/-1403 lines, covering utils/, install/ (including the ccy supervisor deploy and launcher), qa/, config/, constants/, docs_qa/, plan_qa/, remote_docs/, rule_explain/ and issue_report/. There were no changes under `supervise/` in this range. The ccy launcher shell script, `.claude/ccy/claude-supervise`, was also read because it is the asset `install/ccy_supervisor.py` deploys.

## Verdict

**PASS. No blockers.** There are 7 NON-BLOCKING findings below. Each one was checked by reading the code. The probe scripts behind findings 1-3 are kept under `untracked/scratch/review-rest/`.

## Checks run

- Every package module imports cleanly: a `pkgutil.walk_packages` import of all of `claude_code_hooks_daemon` had 0 failures. So the large deletions in `shell_expansion.py`, `shell_segmentation.py` and `secret_file_matching.py` leave no dangling references.
- Targeted pytest on 16 test files for the new and changed modules (github_issue_validity, protected_file_index, protected_pathspecs, work_queue, limit_events, stand_in_cron, autonomy, escape_hatch, fake_values, plan_fact_check, effective_handlers, ccy_supervisor, suite_shards, exception_entries, bash_flags, recursive_search): **621 passed**. Output is in `untracked/scratch/review-rest/pytest-targeted.txt`.
- Tests exist for every new module. Each new public symbol is referenced by at least one test file. The private helpers are covered through their public callers: `_migrate_wrapper_to_launcher` via `wrapper_migrated` in `tests/unit/install/test_ccy_supervisor.py`, the raw-YAML fallback in `tests/unit/utils/test_secret_redaction.py`, and set-aside in `tests/unit/utils/test_plan_fact_check.py`.
- Added lines contain no TODO, FIXME, HACK, breakpoint or stray print.
- Config probe: `{pattern, reason}` entries are reduced to plain patterns before any handler sees them. `guard_config_drift` reads the raw YAML and goes through `entry_pattern`. A placeholder reason fails validation, which is the stated intent.
- Security: the only new subprocess is `gh`, run in list form with a timeout and no shell. Logins read from GitHub are validated against the login grammar before they reach a message. YAML is read with `safe_load` throughout. The approval marker read now reports UNREADABLE instead of crashing.

## Non-blocking findings

### 1. `find_under` spawns one `git check-ignore` per ignored protected file on the hot path (Confidence: 90%)

**Location:** `src/claude_code_hooks_daemon/utils/protected_file_index.py:136-142` (the call) and `:187-200` (`_root_defeats_ignore`)

**Problem:** For an ignore-honouring search (`rg`, `ag`, i.e. `TreeView.UNIGNORED`), each ignored entry under the root calls `self._root_defeats_ignore(base)`. That runs `run_git(... "check-ignore" ...)` every time, even though the answer depends only on `base`. Secrets are normally gitignored, so a plain `rg foo` in a project with N ignored protected files makes N git subprocess calls inside a PreToolUse call. Each call has a 5 s timeout, and none of them finds anything. The module docstring says the opposite: "the answer comes from an index ... consulted in memory".

**Evidence:** `untracked/scratch/review-rest/probe_index_git_calls.py` builds 40 ignored `svc*/.env` entries and gets `git check-ignore calls for one rg command: 40`.

**Fix:** Compute `_root_defeats_ignore(base)` at most once per `find_under` call, lazily and cached in a local before or inside the loop. Better still, memoise it per `(index, base)` on the index. Add a test that counts `run_git` calls for N ignored entries and asserts at most 1.

### 2. `deliver_pending` is not atomic: concurrent hook events deliver the same fact-check twice (Confidence: 80%)

**Location:** `src/claude_code_hooks_daemon/utils/plan_fact_check.py:349-376` (and `set_aside_pending` at `:250-259`). It is called from `handlers/post_tool_use/plan_fact_check_feed.py:121` on every PostToolUse while a record is pending.

**Problem:** The sequence `pending_folders()` -> `read_pending` -> `write_diff` -> `record_checked` -> `clear_pending` takes no lock. The daemon dispatches hooks on concurrent threads, and parallel tool calls produce simultaneous PostToolUse events. Two threads can therefore both read the record and both return the instruction, which breaks the "once per record" contract. When the record is unreadable, the second thread's `path.replace(aside)` raises an uncaught `FileNotFoundError` from the handler. The impact is limited because the feature is report-only and off by default for clients.

**Evidence:** `untracked/scratch/review-rest/probe_fact_check_race.py` forces the two threads to interleave with a barrier after `read_pending` and gets `instructions delivered for ONE pending record: 2`.

**Fix:** Claim each record atomically before delivering it. For example, `os.replace(pending, pending + ".delivering")` and only the thread whose rename succeeds delivers. Alternatively, hold a module-level `threading.Lock` around the loop. Catch `FileNotFoundError` in the set-aside path. Add a two-thread test.

### 3. `rg -r/--replace` value is read as the pattern, so the real pattern becomes the search root (Confidence: 85%)

**Location:** `src/claude_code_hooks_daemon/utils/recursive_search.py:62-69` (`_OPTIONS_TAKING_VALUE`) and `:189-201` (cluster handling: `char in "rR"` sets recursive and consumes nothing)

**Problem:** For rg, `-r` is `--replace` and takes a value. Neither `-r` nor `--replace` is in the value-taking set. So in `rg -r X needle`, `X` is dropped as the pattern and `needle` is placed as the only root. The real read of `.` is never judged. This is a false negative on an ordinary command shape. It is not an adversarial bypass.

**Evidence:** `untracked/scratch/review-rest/probe_rg_replace.py` prints:
`'rg needle' -> ['/workspace']`, `'rg -r X needle' -> ['/workspace/needle']`, `'rg --replace X needle' -> ['/workspace/needle']`.

**Fix:** Make value-taking options depend on the tool. For `TOOL_RG`, treat `-r` and `--replace` as taking a value, and do not treat `-r`/`-R` as the recursion flag (rg recurses by default anyway). Add the three probe commands as test rows.

### 4. `index_for` docstring contradicts its retry behaviour (Confidence: 90%)

**Location:** `src/claude_code_hooks_daemon/utils/protected_file_index.py:331-333`

**Problem:** The docstring says a failed build "is not retried until the refresh interval has passed". The code retries after `RETRY_AFTER_FAILURE_SECONDS` (30 s), not `REFRESH_AFTER_SECONDS` (600 s), and the constant's own comment explains why. A reader tuning either constant will be misled.

**Fix:** Change the docstring to say a failed build is retried after `RETRY_AFTER_FAILURE_SECONDS`.

### 5. `check_open_issues` silently truncates at 100 open issues (Confidence: 75%)

**Location:** `src/claude_code_hooks_daemon/utils/github_issue_validity.py:75` (`_LIST_LIMIT = "100"`) and `:486-509`

**Problem:** `--list-eligible` runs on one `gh issue list --limit 100`. On a repository with more than 100 open issues, eligible issues past the 100th are left out and nothing says so. The docstring says "There is no partial answer", but this is one.

**Fix:** When `len(data) == int(_LIST_LIMIT)`, either raise `GhError` or return a truncation flag that the CLI prints. Alternatively, page with `--limit` set to a large ceiling and report when the ceiling is hit.

### 6. The ccy wrapper migration rewrites a custom-path wrapper to a launcher that may not exist (Confidence: 70%)

**Location:** `src/claude_code_hooks_daemon/install/ccy_supervisor.py:244-258`

**Problem:** `_migrate_wrapper_to_launcher` replaces `claude-supervise.py` with `claude-supervise` on any active `CCY_CLAUDE_WRAPPER` line. That includes a user line pointing at a custom directory such as `/opt/tools/claude-supervise.py --arm --`. The launcher is only deployed to `.claude/ccy/`, so after the upgrade that user's wrapper can name a file that does not exist, and ccy cannot start `claude`. The default armed line resolves to the ccy directory and is safe.

**Fix:** Migrate only when the line names the deployed path: the default `$(cd "$(dirname ...)" && pwd)/claude-supervise.py` form, or a path that resolves into `target_ccy_dir`. Otherwise leave the line alone and add a message recommending the launcher. Add a test with a custom absolute path.

### 7. `unlisted-fake-value` sweep logs a skipped unreadable document only at DEBUG (Confidence: 70%)

**Location:** `src/claude_code_hooks_daemon/docs_qa/checks/unlisted_fake_value.py:123`

**Problem:** Commit c168ac6af says the check "logs an unreadable document it skips", but it logs at `debug`, which nobody sees in practice. A document the sweep could not read is reported the same way as a clean one.

**Fix:** Log at WARNING. Better, return an ADVISE `Finding` naming the unreadable path, the same way `_registry_finding` handles an unreadable registry.

## Positive observations

- The pathspec narrowing in `protected_pathspecs.py` is a careful superset: it falls back to the full listing for any pattern it cannot prove, and it documents its one known gap.
- `GIT_TIMED_OUT` (124) is now separate from `_GIT_UNAVAILABLE` (127), and the only consumer that branches on it was checked.
- `work_queue` refuses to overwrite a file it cannot read, and the re-brief reports that as UNREADABLE instead of empty.
- `escape_hatch.is_acceptable_reason` is now the single shared hygiene check for hatch reasons, used by the plan size check and by config exception entries.
- The ccy launcher (`.claude/ccy/claude-supervise`) degrades to an unsupervised `claude` instead of crashing on an unsupported Python.

# Release code review: v3.69.0, PreToolUse handlers

Scope: `git diff v3.68.0..HEAD -- src/claude_code_hooks_daemon/handlers/pre_tool_use/`
(33 files, +2292 / -840), plus the matching tests. Read-only review. No full suite was run.

**Verdict: PASS. No blockers.** Six non-blocking findings follow. Each gives file:line, severity and a fix.

## How this was checked

- Read every hunk of the diff. Read the new handlers in full: `host_command_guard.py`,
  `github_issue_assignment_guard.py`, and the remote-delete path in `destructive_git.py`.
- Ran these targeted tests. All passed.
  - destructive_git (remote delete merged, remote ref deletion, base), host_command_guard and
    github_issue_assignment_guard: 373 passed.
  - bash_safe_mode, verification_result_gate, plan_journal_guard, plan_number_helper,
    project_containment, quarantine_artefact_read_guard, secret_file_guard_advisory,
    guard_config_commit_gate, conflict_marker_commit_gate, upgrade_approval_guard,
    sensitive_content_fake_values, daemon_docs_guard, comment_size, root_recursion_guard,
    git_stash and ancestry_preserving_merge: 1760 passed.
- Ran live probes in `untracked/scratch/review-v369/`. They are kept as evidence:
  - `probe_push_delete.py` with `mkrepo.bash`: builds a real repository with a bare remote.
    It holds a merged branch, an unmerged branch and a tag.
  - `probe_host.py`, `probe_plan_mkdir.py`, `probe_sed.py`, `probe_vgate.py`,
    `probe_glob_index.py`, `probe_guard_script*.py` and `probe_push_prune.py`.

## Checklist results

- **Tests for each changed handler.** Every handler whose logic changed has new or changed tests.
  - The sed_blocker change (segment-aware commit exemption) is covered by
    `test_segmentation_defects_00483.py` and `test_heredoc_grammar_chain.py`.
  - The flaggable_content_channel_guard change is a pure extraction into
    `utils/recursive_search.py`. Its existing tests still apply.
  - lsp_enforcement, merge_to_main_approval, reference_repo_freshness, subagent_full_qa_blocker
    and pipe_blocker only change mechanically: the `shlex` to `linear_shlex` swap and removed
    `nosec` comments.
- **Priorities.** `HOST_COMMAND_GUARD = 10` is in the safety range. `GITHUB_ISSUE_ASSIGNMENT_GUARD = 53`
  is in the workflow range. Both are correct.
- **Debug code, TODOs and new suppressions.** None in the added lines. A grep for TODO, FIXME,
  print(, breakpoint, noqa, type: ignore and nosec found nothing.
- **Security anti-patterns.** No shell=True and no string-built argv. `git ls-remote` and
  `rev-parse` get argv lists. The remote and branch names are first checked against
  `_LITERAL_BRANCH_NAME`, and `GIT_TERMINAL_PROMPT=0` is set.
- **destructive_git remote delete.** I checked it against a real repository:
  - Allowed: `--delete merged`, `:merged`, `-d`, `-u ... :merged` and `refs/heads/merged`.
  - Denied: an unmerged branch, a tag (`:v1`), the default branch, `:HEAD` (stopped by the
    ls-remote check), a mix of merged and unmerged, and any compound with a second destructive
    rule.
  - Not matched: `my-delete-branch`, `HEAD:refs/heads/x` and `--dry-run`.
  - When the check cannot finish it denies, as it should.
- **Fail-open changes in secret_file_guard, project_containment and quarantine_artefact_read_guard.**
  These follow owner ruling A1, are documented, and are tested in
  `test_secret_file_guard_advisory.py`. A literal mention is still denied: probed through both
  the Bash route and the Write-script route, including with shell constructs the reader cannot parse.
- **escape_hatch helper.** It keeps IGNORECASE and requires an exact quoted value. It is used
  the same way by all five in-command hatches. This is a sound change that removes duplication.

## BLOCKERS

None.

## NON-BLOCKING

### N1. A glob is silently allowed while the protected-file index is not built (no advisory). Confidence: 90%

**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/secret_file_guard.py:1394`.
The same gap exists in `quarantine_artefact_read_guard.py:337`.

**Problem:** The docs say an index that is not built yet is allowed WITH a loud advisory. Both the
module docstring and `get_claude_md` promise this ("an index not built yet -- is ALLOWED with a
loud advisory"). That holds for the recursive-search and Grep-directory paths, which return
`_NO_INDEX_REASON`. It does not hold for a glob. `index = self._index(patterns) if
_MAY_GLOB.search(command) else None` passes `None` through, and `find_protected_mention_detail`
then skips the index check for that glob without saying so. The call is a plain ALLOW with no
context.

**Evidence:** `probe_glob_index.py` used a scratch directory holding a file named like the
`.vault-` default pattern.
- Command: `head untracked/scratch/review-v369/k*/.*`
- Result with a cold index: `allow`, context empty.
- Result with a warm index: `deny`.

**Why it matters:** After every daemon restart there is a window where glob reads of protected
files pass with no warning at all. That contradicts the documented contract, and the agent is
not told that the call went unjudged.

**Fix:** In `_evaluate`, when `_MAY_GLOB` matched, the index was `None` and no mention was found,
return `(_NOT_JUDGED_PATTERN, <a glob-specific no-index reason>, _ADVISORY_ROUTE)` instead of
`None`. Do the same in quarantine `_bash_mention`. Add a test: cold index, a glob that reaches a
protected file, assert ALLOW with the advisory.

### N2. host_command_guard misses common docker spellings. Confidence: 80%

**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/host_command_guard.py:178-245`
(`_option_values`, `_docker_creation_arguments`).

**Problem:** `-v` is found only as a standalone word or as `-v<value>`. A short-flag cluster
ending in `v` is the usual way to type `docker run -it` plus a volume, and it is not seen.
`docker compose run` is also not treated as a creating subcommand.

**Evidence:** From `probe_host.py`:
- `docker run -itv /:/host alpine` returns `[]`.
- `docker compose run -v /:/h svc` returns `[]`.
- `docker run -v /:/host alpine` is denied.

**Fix:** In `_option_values`, treat a short cluster whose last letter is a value-taking option
(`v`) as taking the next word. Add `compose run` to the docker reading, or document it as out of
scope in the docstring's table. Add a test for each.

### N3. Remote-ref deletion through `git push --mirror` / `--prune` is not covered. Confidence: 75%

**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/destructive_git.py:113`
(`_GIT_PUSH_DELETE_PATTERN`).

**Problem:** Owner ruling A6 makes deleting a ref on the remote human-only. The deny text says
"do not look for another spelling of it". But `git push --mirror <remote>` and
`git push --prune <remote> <refspec>` both delete remote refs, and neither matches.

**Evidence:** From `probe_push_prune.py`, `matches()` returns False for both
`git push --mirror origin` and `git push --prune origin 'refs/heads/*:refs/heads/*'`.

**Fix:** Add `--mirror` and `--prune` as markers in `_GIT_PUSH_DELETE_PATTERN`. Keep them out of
`_PUSH_LONG_FLAGS` so the merged-branch allowance never applies to them, and they stay denied.
Add tests.

### N4. host_command_guard false positives on harmless shapes. Confidence: 70%

**Location:** `host_command_guard.py:294-312` (`_token_is_consumed`) and `:51` (`PYPI_HOSTS`).

**Problem:**
- `gh auth token > /dev/null` is denied, although nothing reaches the transcript. A redirect is
  not a printing consumer.
- `pip install --index-url https://pypi.python.org/simple x` is denied as non-PyPI.
  `pypi.python.org` is PyPI's own legacy host and redirects to `pypi.org`.

**Evidence:** `probe_host.py`.

**Fix:** Treat an output redirect of the token step to a file or `/dev/null` as consumed (a file
write is not the transcript). Add `pypi.python.org` to `PYPI_HOSTS`. Add a test for each.

### N5. Magic strings in the new push-delete reader. Confidence: 70%

**Location:** `destructive_git.py:502-536` (`_remote_delete_targets`).

**Problem:** `"--delete"` and `"d"` are inline literals. The same strings are also inside
`_PUSH_LONG_FLAGS` / `_PUSH_FLAG_LETTERS`, which is a second copy beside the regex at line 113.

**Fix:** Name `_DELETE_LONG = "--delete"` and `_DELETE_LETTER = "d"` once and use them in all
three places.

### N6. sensitive_content re-reads the fake-values YAML on every matching write. Confidence: 70%

**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/sensitive_content.py`
(`_fake_values`, called from `_find_public_pattern_match`).

**Problem:** Each call that matches a public pattern runs `load_fake_values()`, which reads and
parses `.claude/fake-values.yaml` from disk. Nothing is cached, not even by mtime. It is not
wrong, but it is per-event disk and YAML work on a hot safety path, and other readers of this
registry in the code base cache theirs.

**Fix:** Cache the registry keyed on the file's `(st_mtime_ns, st_size)`, as
`github_issue_assignment_guard._issues_in_header` does.

## Observation outside the diff (not graded)

In this session the LIVE daemon's `subagent_full_qa_blocker` added an `R-SUBAGENT-FULL-QA`
advisory to `rm -r <dir>` and to a script containing `set -e`. It labels them
`unrecognised-interpreter-inline-code`, reading `-r` and `-e` as inline-code flags. I could not
reproduce this by calling the handler directly, either at v3.68.0 or at HEAD (my payload may
lack the sub-agent fields), so I have not attributed it to this release. It is worth a ledger
entry: the advisory is headed "WHY BLOCKED" on ordinary commands.

## Positive observations

- `destructive_git`'s merged-branch allowance is careful. It requires the tracking ref to be an
  ancestor AND `ls-remote` to show the live tip equal to it. It checks the default branch, tags
  and tag-name ambiguity, and is only judged when it is the sole matched rule.
- `utils/escape_hatch.py` and `utils/commit_location.py` remove real duplication: five hatch
  regexes and four `_is_foreign_repo` copies.
- `github_issue_assignment_guard` keeps `matches()` free of network calls and file reads apart
  from one header read cached by mtime. A failed lookup is an advisory and is never a deny.

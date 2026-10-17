# Code review A: pre_tool_use handlers (v3.69.0..9513c3d45)

Release v3.70.0, Step 10 Code Review Gate, run early. A read-only review: no
tracked file was edited. The probe scripts are kept as evidence under
`/workspace/untracked/scratch/cr-a/`, and a v3.69.0 copy of `src/` (made with
`git archive v3.69.0 src`) is at `untracked/scratch/cr-a/old/src` so behaviour
can be compared with the previous release.

## Scope covered (files read)

Read in full, or read diff by diff with the surrounding code, and probed live:

- `write_protected_paths.py`: new, read in full. Probe: `probe_wpp.py`, `probe_wpp2.py`.
- `resume_guard.py`, `subagent_context_budget.py`: new, read in full.
- `curl_pipe_shell.py`: full diff. Probe: `probe_cmds.py`, about 60 shapes.
- `pip_break_system.py`, `sudo_pip.py`: full diff. Probe: `probe_cmds.py`.
- `root_recursion_guard.py`: full diff. Probe: `probe_root.py`.
- `destructive_git.py`, `secret_file_guard.py`, `sed_blocker.py`: diff. Probe: `probe_git.py`.
- `sensitive_content.py`: full diff. Probe: `probe_sc.py`, run against HEAD and v3.69.0.
- `worktree_file_copy.py`: probed only (`probe_wfc.py`, HEAD and v3.69.0). Its diff was not read.
- `subagent_full_qa_blocker.py`: diff hunks outside the large new Python-reachability block. I read the handler class changes (`exempt_agent_types`, the lock probe), `_first_full_run` (a positive match now beats an unseen one), `_run_verdict` (an unknown option is read both as a flag and as a value), `_container_args_after_image`, `_read_new` (secret-file paths are left unseen, and a binary over budget is probed instead), and the `_INLINE_CODE_FLAG_TEXT_TOOLS` additions.
- `constants/priority.py` diff: priority bands.

Priority bands: all correct. `WRITE_PROTECTED_PATHS` is 18 (safety, tagged
SAFETY+BLOCKING, so a crash fails closed through the chain).
`SUBAGENT_CONTEXT_BUDGET` and `RESUME_GUARD` are 39 (workflow, cost gates that
fail open on purpose, as their docstrings say). The four new advisories are 60
(advisory). `AGENT_DISPATCH_RECORDER` is 46.

## DEFECTS

### D1. sensitive_content no longer scans a commit message or gh body file written earlier in the same Bash command (fail-open regression). CONFIRMED

- Location:
  - `src/claude_code_hooks_daemon/handlers/pre_tool_use/sensitive_content.py:1040`: the loop over `_metadata_commands`.
  - `src/claude_code_hooks_daemon/handlers/pre_tool_use/sensitive_content.py:1450-1474`: `_metadata_commands`.
- What changed: v3.69.0 used the WHOLE command as the haystack whenever it
  wrote git metadata or a gh body. HEAD keeps only the segment that records
  metadata (ledger 00474 N364/N341, which stopped a term in an unrelated `cd`
  from denying a commit). A heredoc body is kept only when its opener line
  matches that segment. So when one segment writes the message or body file
  and a later segment commits or publishes it, the text holding the term is
  dropped. `read_message_files` then finds no file on disk at PreToolUse time
  and skips it ("git fails on a missing file itself"), but the earlier segment
  creates the file, so git does read it.
- Failing inputs. With a public pattern `ZZPROBETERMZZ`: v3.69.0 denied every
  command below and HEAD allows every one (`probe_sc.py`, run on both trees):
  - `cat > m.txt <<'EOF'` / `ZZPROBETERMZZ` / `EOF` / `git commit -F m.txt`
  - `printf 'ZZPROBETERMZZ' > m.txt && git commit -F m.txt`
  - `echo ZZPROBETERMZZ > m.txt; git commit -F m.txt`
  - `cat > b.md <<'EOF'` / `ZZPROBETERMZZ` / `EOF` / `gh pr create --title t --body-file b.md`
- Why it matters:
  - This is the shape this project tells agents to use: "write the message to
    untracked/scratch/ and `git commit -F` it", in subagent_context_budget's
    deny text and in the CLAUDE.md guidance.
  - A commit message is not staged content, so the commit-time staged scan
    does not see it either. The term reaches history, and only a history
    rewrite removes it.
  - The gh case publishes to GitHub, which cannot be retracted. The handler's
    own docs call this the leak surface that cannot be undone.
- Why the tests miss it:
  - `test_sensitive_content_metadata_scope.py` pins the narrowing (a term in
    an unrelated `cd` is allowed).
  - `test_sensitive_content_same_command.py` covers staged FILE content
    written in the same command, never a message or body FILE written in the
    same command.
  - No test writes `-F`/`--body-file` content and consumes it in one command.
- Remediation:
  - In `_metadata_commands`, keep every segment that WRITES a path named by a
    recording command's `-F`/`--file`/`--body-file`/`-F` value. Use the shared
    `get_written_file_paths`/`scan_bash_write_targets` accessor to match
    written paths against the paths `read_message_files` would read, and keep
    the heredoc bodies those segments open.
  - Or simpler: when a recording command names a message or body file that
    does not exist yet and the same command writes that path, add the whole
    command as a haystack (the v3.69.0 behaviour), but only for that case.
  - Add tests for the four inputs above (deny), plus the N364 case
    (`cd /tmp/<term> && git switch -c clean`, allow) to keep the narrowing.

No other defect was confirmed in the code I read.

## NON-DEFECTS

- N1. `write_protected_paths.py:739`: `hook_input.get(TOOL_INPUT, {}).get(key)`
  raises AttributeError when `tool_input` is present but `None`. The handler is
  SAFETY+BLOCKING, so the chain turns the crash into a deny (fail closed, not
  open), and Claude Code never sends `null` there. Remediation: guard with
  `isinstance(tool_input, dict)` as `_judge`'s peers do, so a malformed event
  gets the handler's own verdict rather than a SYSTEM ERROR deny. Low.
- N2. `sudo_pip.py`: `sudo nice pip install x` and `sudo <wrapper> pip ...`
  (wrappers other than `env` and the shells) are allowed. This is not a
  regression: v3.69.0's pattern missed them too. Remediation if wanted: run
  the post-elevator text through `peel_command_wrappers` before the pip
  pattern, as `curl_pipe_shell._command_start` does.
- N3. `curl_pipe_shell.py`: `curl URL | xargs bash` is allowed, as it was
  before. xargs hands the downloaded words to bash as file names, not as code,
  and this sits within the careless-agent threat model. No action is needed.
- N4. `root_recursion_guard.py`: `cd / && grep -r x .` is allowed. The guard
  judges the scan root token, not the directory reached by a `cd`. This gap
  already existed. Remediation (optional): follow a literal `cd` as
  `write_protected_paths._runs` does.
- N5. `write_protected_paths.py` is 1,354 lines, with its own `cd` tracking
  (`_runs`, `_split_sequence`, `_CD_*` regexes) that partly duplicates the
  shared shell-segmentation utilities (`split_unquoted_spans`,
  `peel_command_wrappers`). Probes found no wrong verdict: 50 write and read
  shapes, including `cp X/app.yaml conf/`, `cp -t`, `rm -r con*`, `cd sub && >
  ../f`, for loops and `bash -c`. It is a maintainability cost, not a defect.
  Suggestion: move `_split_sequence` and the cd-following into
  `utils/shell_segmentation` so `root_recursion_guard` (N4) can reuse them.
- N6. The `subagent_full_qa_blocker.py` exempt path (`_exempt_run`) allows the
  run when cwd is missing or not a git checkout (`LockState.UNKNOWN`), and
  relies on the pytest sink to enforce the lock. This is documented in the
  allow text, so it is a design choice. If that is wrong for llm_qa.py's
  non-pytest steps, deny on UNKNOWN for exempt agents instead.
- N7. Inline `"BLOCKED [R-SUBAGENT-FULL-QA]: ..."` in `_exempt_run` builds its
  headline by hand, unlike the other denies, which use
  `RuleFormatter`/`under_rule`. Remediation: use
  `GatingResult(...).under_rule(_RULE)` so the rule id is attached
  structurally.

## Not reviewed

Honestly skipped or only skimmed, because of the size of this slice (about
11,000 lines; this agent's context budget ran out):

- `subagent_full_qa_blocker.py`: the roughly 1,200-line new Python
  reachability analysis (`_parsed_reach`, `_files_run_in_process`,
  `_python_strings` and related, diff lines 436-2000), not read line by line.
- `worktree_file_copy.py`: diff not read, only probed. HEAD matches or beats
  v3.69.0 on 10 shapes, and now catches `cp -t src/ <wt-file>`.
- `project_containment.py`, `tdd_enforcement.py`, `lsp_enforcement.py`,
  `issue_filing_gate.py`, `github_auto_close_keywords.py`,
  `gh_issue_comments.py`, `gh_pr_comments.py`, `staged_lint_gate.py`,
  `conflict_marker_commit_gate.py`, `pipe_blocker.py`, `plan_number_helper.py`,
  `merge_qa_advisor.py`, `daemon_docs_guard.py`, `ancestry_preserving_merge.py`,
  `subagent_worktree_write_guard.py`, `remote_docs_*`, `docs_qa_*`,
  `plan_qa_*`, `comment_size.py`, `error_hiding_blocker.py`, `git_stash.py`,
  `git_message_backtick.py`: not reviewed.
- New advisories `spawn_rate_advisor.py`, `review_round_advisor.py`,
  `subagent_tier_advisor.py`, `workflow_fanout_advisor.py`,
  `agent_dispatch_recorder.py`: not reviewed. They are advisory or sensor
  only, never deny, so the risk is lower.
- `upgrade_approval_guard.py` was deleted (1,527 lines). I did not check that
  nothing still references its HandlerID or RuleID, or depends on it as a
  safety control.
- Missing tests per behaviour change: checked only for sensitive_content (D1).
  A test file exists for each new handler I read (`test_write_protected_paths.py`,
  `test_resume_guard.py` and `test_subagent_context_budget.py` are named in
  the acceptance tests), but I did not read them.

A second reviewer should take the "Not reviewed" list, starting with
project_containment, tdd_enforcement, pipe_blocker and worktree_file_copy,
which are blocking guards.

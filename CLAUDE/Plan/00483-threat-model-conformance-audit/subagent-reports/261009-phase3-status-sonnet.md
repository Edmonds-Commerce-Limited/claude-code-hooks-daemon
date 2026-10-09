# Plan 00483 Phase 3 status audit (read-only), 2026-10-09

Against /workspace main at 04c76317d. Sources: PLAN.md, INVENTORY.md, TRIAGE-*.md, OWNER-RULINGS-*.md,
RULINGS-owner-delegated-fable.md, ledger 00474 NIGGLES.md + CARRIED-REFIX-BRANCHES.md, the 00466 index in
Completed/, `bin/hooks-daemon handlers`, `scripts/qa/dangerous-invocation-corpus.yaml`, and 50 re-run
INVENTORY false-positive probes (`untracked/scratch/p483-fp-rerun.txt`, live daemon, main thread).

## 1. Task 3.1 / 3.2 branches

`git branch -a --merged main` and `git branch -a` list none of these names: every branch is merged and its
local and origin ref is deleted. None is open or gone-unmerged. Merge commits (from `git log --merges main`):

| Branch                          | Merge commit                                                                                                                       |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| worktree-p483-inscope           | a248be4c2                                                                                                                          |
| worktree-p483-leak              | 3495e36b9                                                                                                                          |
| worktree-p483-segment           | 6f9cd976b                                                                                                                          |
| worktree-p483-config            | fec3aa703                                                                                                                          |
| worktree-p483-secret            | 9b2e15be1                                                                                                                          |
| worktree-p483-mkdir             | 76bf848aa                                                                                                                          |
| worktree-p483-paths             | c953b0c62                                                                                                                          |
| worktree-p483-glob              | 2ba5b72a2                                                                                                                          |
| worktree-p483-recur             | f152ea9d9                                                                                                                          |
| worktree-p483-ordin             | cd7638c73                                                                                                                          |
| worktree-n130-walk              | 012915bd9 (its capped walk was then removed by the A1/A2 merge dc5c9263b; N130 is now answered by the cached protected-file index) |
| worktree-p483-x1-rebind-heredoc | 3644f831e                                                                                                                          |
| worktree-p483-fp-batch2         | 9d182f299                                                                                                                          |

Also merged: worktree-p70-regex-operand (0bfca745d), worktree-p483-ledger (56677e3c6), quoted-text-fps
(4ebc33247), n154-n230 (c7271043f), n55 (ae62d27d1), phase4-docs (90a8c0d43), Phase 2 A1/A2/R2 (dc5c9263b),
Task 2.2 A6 (745dc2d68). PLAN.md Task 3.1 and 3.2 text still says "fixed on branch ..." for all of them and
leaves both tasks unticked; they should read "merged at <hash>".

## 2. In-scope ledger entries still open

Almost nothing in-scope and open remains as CODE. What is open is mostly stale or missing RECORDS:

| Entry            | State today                                                                                                                                                                            | Smallest fix                                                                                                                                                                                              |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| N170, N130, N136 | CARRIED-REFIX-BRANCHES.md lines 126, 690, 800 still say "On main: Open" but they merged (9b2e15be1, 012915bd9/dc5c9263b, 9b2e15be1)                                                    | Edit three status lines to Fixed with the merge hash (N130: "superseded by the protected-file index, A2")                                                                                                 |
| N124 residual    | Row says "Open: other regex-text tools such as `find -regex` and a `python3 -c` regex" (line 604). Not fixed; the A1 rule (deny only on a positive finding) may already cover it       | Re-probe `find . -regex '.*decision:.*'` and `python3 -c "import re; re.findall(r'probe:.*decision:','x')"`; if allowed, mark Fixed by A1, else add the regex-operand exemption for `find -regex/-iregex` |
| N79              | 00466 index "Open"; ordinary-command corpus is now about 357 rows (R2 gate), above the 200 asked                                                                                       | Mark remedied (R2 / dc5c9263b)                                                                                                                                                                            |
| N222             | In Progress (perf tests remedied; ~15 bound-honoured wall-clock tests open). The guard half (wall-clock scan deadline) was removed by A1 (cap or deadline now allows with an advisory) | Re-scope to the test half only: switch the remaining wall-clock asserts to a load-scaled helper (the N344 helper N95 already uses)                                                                        |
| N260             | Partly fixed: plugin flag and daemon-state differences between local gate and CI remain                                                                                                | Make `check_project_handler_tests.py` pass the same pytest flags as `.github/workflows/qa.yml:498`                                                                                                        |
| N28              | Deferred by owner ruling A4 (new walker needed); not a defect to fix now                                                                                                               | None; keep deferred                                                                                                                                                                                       |
| N98              | Fixed 7c525415e (00466 index says Fixed)                                                                                                                                               | None                                                                                                                                                                                                      |
| N229, N75        | Narrowed ebaa51151 (ruling A4)                                                                                                                                                         | None                                                                                                                                                                                                      |
| N76              | Dismissed (A4)                                                                                                                                                                         | None                                                                                                                                                                                                      |
| N240, N62, N74   | No change (Fable rulings; N74 closed by A2)                                                                                                                                            | None; N240 needs its two `script` corpus rows, check they exist                                                                                                                                           |

Open 00474 entries that are not Phase 3 audit entries (ordinary ledger work, listed so nobody mistakes them for
this plan's): N381, N380 (fixing), N378, N375, N376, N371, N370, N369, N367, N364, N363, N361, N360, N353, N348
(partly). N363, N364, N370 are in-scope false positives in guards (pipe blamed on `bash`, `git config --get-regexp user.name` read as a write, sed guard denying a `git -C` commit message), so they also count under Task 3.2.

Ledger-recording gap (Task 2.3, still unticked): the 67 entries triaged from 00466 have no recorded dismissals.
The 00466 index in Completed/ still shows N16..N259 as Open/In progress, and 00474 NIGGLES.md has no
"Dismissed (threat model)" rows for N45, N57, N68, N71, N72, N77, N78, N89 (8 dismissals) nor "No change" rows for
N62, N74. The 00474 carried entries are recorded correctly (about 15 dismissal lines in CARRIED-REFIX-BRANCHES.md).
PLAN.md also still says the 00466 entries stand at "67 open"; 22 are fixed on main and several landed since.

## 3. Task 3.2: in-scope false positives still unfixed

Re-run today of the INVENTORY probes (50 commands; 7 now allow, 43 still deny). Still denied and in scope
(ordinary command, or text that only mentions the target):

- destructive_git: `git clean -nd build-final/`, `git clean -n && rm -f foo.txt` (dry run denied as -f);
  `git checkout main && git log -- src/x.py`; `git restore --source=HEAD~1 --staged src/x.py`;
  `git reset HEAD src/x.py && ls --hard`; `git log --grep='git reset --hard'`; a quoted `<<'EOF'` body or
  `gh ... --body-file -` mentioning `git reset --hard`.
- git_stash: `awk '/git stash/ {print}' f`, `git log -S'git stash'`, `git stash --help`.
- curl_pipe_shell: `curl ... -o out.json && cat out.json | python3 -m json.tool`, `curl ... | python3 -c ...`,
  `curl | perl -pe`, `wget -qO- url | python3 -m json.tool` (a pipe into a non-shell interpreter).
- worktree_file_copy: `grep -rn 'mv untracked/worktrees/...' docs/`, `echo "cp untracked/worktrees/..."`,
  `ls untracked/worktrees/foo/src/ && cp README.md src/`, `mv untracked/worktrees/foo/notes.txt tmp.txt; ls src/x`.
- root_recursion_guard: `find / -maxdepth 1 -name tmp`, `rg "/home" src/`, `grep -rn "/" src/ --include=*.py`,
  `rg foo ~/.bashrc`, `find /sys/class/net -maxdepth 1`, `grep -r foo /proc/self/status`,
  `find $HOME/proj -name x`, `grep -rl x --include=*.py ~/projects`.
- A quoted heredoc fed to a `while read ... done <<'EOF'` loop is scanned as code: this audit's own probe loop was
  denied three times on its body text (a `git reset --hard` line, a `| head` line, a `mkdir CLAUDE/Plan/...` line,
  a `curl | bash` line). Same family as X-1 but for the `while`/`for` loop receiver; not in INVENTORY.
- Deliberate and NOT counted: `sed` word deny (the deny text says it is deliberate), and `| head`/`| tail`
  denies (documented pipe_blocker policy).
- Not re-run (Parts C and F, unverified today): ancestry_preserving_merge, git_message_backtick,
  github_auto_close_keywords mention FPs; pip_break_system, sudo_pip, gh_issue/pr_comments, npm_command raw-text
  matching; subagent_full_qa_blocker script-chain FP; conflict_marker_commit_gate fail-closed on
  `cd "$(git rev-parse --show-toplevel)" && git commit`; the `R-CONFLICT-MARKER-COMMIT` denial on d-h1/d-h4 above.
- Fixed since INVENTORY: X-1 (cd/source/export), fp-batch2 (`${x:-"..."}`, /dev/null, $PWD), quoted-text-fps
  (curl_pipe_shell echo, chmod digits, daemon-dir cd, plan-number ls), Issue #70 regex operand, N36/N49/N58/N60/N65/N97.

## 4. Success Criteria

| Criterion                                                                        | Verdict                   | Evidence                                                                                                                                                                                                                                                                                                                                                                        |
| -------------------------------------------------------------------------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| No open ledger entry or `UNCOVERED-open` corpus row is left unclassified         | NOT MET (corpus half met) | `UNCOVERED-open` appears once in the corpus, in the header legend (line 18); zero open rows, 19 `UNCOVERED-accepted`. Classification of all 55 + 67 + 9 is done in TRIAGE-\*.md, but the 00466 rows were never written back (section 2), and 00474's own post-triage entries (N353..N381) were not triaged under the test                                                       |
| Each dismissal is recorded both in the ledger and, for a command, in the corpus  | NOT MET                   | Carried dismissals are in the ledger and have rows. The 8 dismissals + 2 no-change from 00466 (N45, N57, N62, N68, N71, N72, N74, N77, N78, N89) have no ledger row; the command-shaped ones (N57, N77, N89, N78) have no corpus row (Task 2.3 is the open task)                                                                                                                |
| Every blocking guard has a verdict in INVENTORY.md                               | NOT MET                   | 76 files in `handlers/pre_tool_use/`; INVENTORY.md has no mention of `write_protected_paths` (new today, Plan 00499, priority 18), `host_command_guard` (A6, 745dc2d68) or `github_issue_assignment_guard`. 24 handlers are file-level triage only, marked UNVERIFIED. The Part A-F verdicts also pre-date the A1/A2 removal (about 1,390 lines gone) and need a freshness note |
| Every in-scope false positive found has a narrowing fix merged or a ledger entry | NOT MET                   | 43 of the 50 INVENTORY probes still deny (section 3) and only the secret/quoted-text/X-1/batch-2 families have fixes. Many of the remaining ones have no ledger entry (INVENTORY holds them but Task 3.2 asked for ledger entries or fixes)                                                                                                                                     |

Goals line "in-scope defects found are fixed through the ledger": met for every Task 3.1 branch above.
Phase 4 and Task 3.3 are done. Open questions 1 to 5 all show an owner ruling; none blocks.

## 5. Remaining work in at most 3 batches, by value

1. Records and inventory close-out (docs only, no code, one branch). Write back the 00466 dismissals/no-change/fixed
   statuses to ledger 00474 (one section) and the 00466 index; fix the three stale CARRIED status lines (N170, N130,
   N136); add the corpus rows for the command-shaped 00466 dismissals; add INVENTORY tables for `write_protected_paths`,
   `host_command_guard`, `github_issue_assignment_guard` and a dated freshness note on Parts A-F; file ledger entries
   for each unfixed false positive in section 3; tick Tasks 2.3, 3.1; update Success Criteria. This alone flips
   three of the four criteria and is cheap.
2. Git-guard narrowing (code, TDD, one branch): destructive_git and git_stash. Dry run (`git clean -n`), `git log -- path`, `git restore --source/--staged`, `ls --hard`, `-S`/`--grep`/awk text, `--help`, and quoted-heredoc or
   `--body-file -` bodies and `while ... done <<'EOF'` receivers are data. Reuse the command-position segments
   already used by N241 and X-1. Highest user-visible value because these hit everyday review commands.
3. Remaining raw-text guards (code, TDD, one branch): curl_pipe_shell (pipe into a non-shell interpreter),
   worktree_file_copy (grep/echo mention, `ls ... && cp` not touching the worktree), root_recursion_guard
   (pattern operand `rg "/home"`, `/proc/self/status` file reads, `find / -maxdepth 1`, `~/file`), plus the Part C/F
   guards re-probed first (ancestry, backtick, auto-close, pip, npm, gh comments, full_qa script chain) and the
   N363/N364/N370 entries. Run the effort budget rule (net non-positive lines) and the ordinary-command gate, and add
   each fixed shape as an `a*-` gate row.

# Plan 00483 Task 3.2: the audit's "not re-run" guards, re-probed 2026-10-11

Read-only against main at b8095b83d (this worktree's tip). No source changed. Follows
[261011-task-3.2-recheck-sonnet.md](261011-task-3.2-recheck-sonnet.md).

## 1. Which guards were "not re-run"

[261009-phase3-status-sonnet.md](261009-phase3-status-sonnet.md) section 3 lists them: ancestry_preserving_merge,
git_message_backtick, github_auto_close_keywords (Part C); pip_break_system, sudo_pip, gh_issue_comments,
gh_pr_comments, npm_command (Part F); the subagent_full_qa_blocker script chain (Part F); and the
conflict_marker_commit_gate `cd "$(git rev-parse --show-toplevel)" && git commit` denial. The last is the same as
probes d-h1 and d-h4, already filed as N402. INVENTORY.md sections 7, 8, 12 (Part C) and Part F sections 1, 4, 5, 7, 8
hold the probe commands; every guard except npm_command lists FP commands, and for npm_command the inventory says the
deny path was never verified.

## 2. How they were run

Same method as the re-check: `Config.load` of this worktree's `.claude/hooks-daemon.yaml`,
`cli._build_initialised_controller`, `controller.process_event(HookEvent(PreToolUse))`, `PYTHONPATH=<worktree>/src`, the
whole chain, first decision and deciding handler reported, `cwd` = the worktree. The sub role sends
`agent_id=manual-probe-agent` (what `probe --as sub` sends). Driver `untracked/scratch/nr_inproc.py`, corpora
`nr_corpus.tsv` and `nr_corpus2.tsv` (untracked, not committed); 91 commands, each with an expected verdict, including
true-positive controls. Commands were written to files, not run.

## 3. Results

All controls behave: the real `git merge --squash`, `gh pr merge --squash`, a double-quoted backtick message,
`git commit -m "fixes #3"`, `pip install --break-system-packages x`, `sudo pip install x`, bare `gh issue view 5`,
`gh pr view 7`, `run_all.sh` and `llm_qa.py all` as a sub-agent all deny. No guard denied a command that an ordinary
agent writes with no mention of the target text. The false positives are all "text that only mentions the target".

| Guard (rule)                                    | Ordinary command denied (id)                                                                                                                                                                                                                                                                                                | Allowed (good)                                                                                                                                                                                      |
| ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ancestry_preserving_merge (R-GIT/GH-...-SQUASH) | `git commit -m "never use gh pr merge --squash"` (anc1); `grep -rn 'git merge --squash' docs/` (anc2); `echo 'gh pr merge --rebase is blocked here'` (anc3); `cat <<'EOF'` body mentioning `gh pr merge --squash` (anc9); `git commit -F - <<'EOF'` body mentioning `git merge --squash` (anc10)                            | `git merge --no-ff`, `gh pr merge 12 --merge`, `git log --grep='merge --squash'`                                                                                                                    |
| git_message_backtick (R-GIT-MESSAGE-BACKTICK)   | the canonical idiom `git commit -m "$(cat <<'EOF'` with `` `foo` `` in the quoted-heredoc body (bt1); `git commit -m 'document the -m "`x`" flag'` (bt2)                                                                                                                                                                    | plain, `-F file`, `-F - <<'EOF'` with backticks (bt7), single-quoted backticks (bt8), escaped (bt9)                                                                                                 |
| github_auto_close_keywords (R-GH-AUTO-CLOSE)    | `echo "git commit -m 'fixes #3'"` (ac7); `python3 - <<'EOF'` whose body prints that text (ac9)                                                                                                                                                                                                                              | `grep 'fixes #3'`, `git log --grep='closes #4'`, `Addresses #123`, `Refs #3` (ac3 ac4 ac5 ac6 ac10 ac11)                                                                                            |
| pip_break_system (R-PIP-BREAK-SYSTEM-PACKAGES)  | `pip install --user x && echo --break-system-packages` (pip1); commit message, `grep`, `echo`, `# comment` mentions (pip2 pip3 pip4 pip5); `cat > notes.txt <<'EOF'` and `git commit -F - <<'EOF'` bodies (pip8 pip9)                                                                                                       | `pip install requests`                                                                                                                                                                              |
| sudo_pip (R-SUDO-PIP-INSTALL)                   | `git commit -m "do not sudo pip install"` (sp1); `echo "sudo pip install x"` (sp2); `grep -rn "sudo pip install" docs` (sp3); `git commit -F - <<'EOF'` body (sp7)                                                                                                                                                          | `sudo apt-get install -y python3-pip`, `sudo systemctl restart nginx`, `sudo -u bob pip list`                                                                                                       |
| gh_issue_comments / gh_pr_comments              | `git commit -m "docs: gh issue view note"` (ghc1); `grep -n "gh pr view" notes.md` (ghc2); `echo "gh issue view 5"` (ghc3); `gh issue view 5 --json=comments` (ghc5, comments ARE requested); `gh pr view 7 --jq '.title \| length' --json comments` (ghc8, comments requested); a second `-m "see gh issue view 5"` (ghc9) | `--comments`, `--json title,comments`, `gh issue list`, a commit body that also says `--comments` (ghc12)                                                                                           |
| subagent_full_qa_blocker (R-SUBAGENT-FULL-QA)   | `python3 <script>` where the script imports `subprocess`, runs `ruff check .` and holds a `TOOLS = [..., "pytest"]` list (fq1, MATCHED pytest-whole-suite)                                                                                                                                                                  | `bash` script that only echoes the name, `tar -c`, `ssh -c`, `docker run -e`, `pytest tests/unit/x.py`, `llm_qa.py changed ...`, `ruff`, `black`, `bin/hooks-daemon status`, `python3 -m json.tool` |
| npm_command (R-NPM-\*)                          | none. Mentions in `git commit -m`, `echo`, `grep` (npm1 to npm3) allow; this repo does not trigger the deny path (the guard is a workflow advisory)                                                                                                                                                                         | `npm run llm:lint`, `npm install`, `npm --version`                                                                                                                                                  |
| conflict_marker_commit_gate                     | `cd "$(git rev-parse --show-toplevel)" && git commit` (cm3), `cd $PROJ && git commit` (cm4): N402                                                                                                                                                                                                                           | no-cd, `cd src &&`, `git add -A &&`, `git -C <path> commit`, a message mentioning the marker                                                                                                        |

The fq1 deny reproduces the INVENTORY finding (Part F, FP 1) on current main: the script-file chain is not narrowed. The
advisory noise the inventory also recorded (`tar -c`, `ssh -c`, `docker run -e`) does not deny and is not a verdict.
A pipe in `gh ... --comments | head -5` denies by pipe_blocker, documented policy (ghc13).

## 4. In-scope false positives and their ledger cover

Existing entries: the conflict gate cases (cm3, cm4) are N402. N400 and N401 are the probes of the first re-check and
did not recur in these guards. No existing 00474, 00466 or 00483 TRIAGE entry covers any other row above (searched
NIGGLES.md and the 00483 TRIAGE and RULINGS files for each guard name; N385 is the opposite direction, careless
spellings the guards ALLOW, and N94 is the auto-close verdict cache). So six new entries are proposed, numbered by the
coordinator. All six are the same class, a regex over the raw command text with no knowledge of quoting, heredocs or
`echo`/`grep` arguments, which the in-tree fix pattern (`command_position_segments`, `strip_inert_spans`, the batch (b)
heredoc sink rule) already answers for other guards.

- **P4. `git_message_backtick` denies the canonical `git commit -m "$(cat <<'EOF' … `x` … EOF)"` idiom and a `-m "…"`
  quoted inside a single-quoted message.** Evidence: bt1, bt2 (INVENTORY probes bt_heredoc and bt_sq_dq, reproduced on
  b8095b83d); bt7 to bt9 allow. Impact: highest of the six, since this is the heredoc form agents are told to use
  and a Markdown message with a code span is ordinary. Remedy: judge the `-m` value from the shell quote context (the
  quoted-delimiter heredoc body of a `$(cat <<'EOF'…)` is literal, a `-m "` inside single quotes is not an option);
  gate rows for the heredoc form.
- **P5. `ancestry_preserving_merge` denies any text that mentions `git merge --squash`, `gh pr merge --squash` or
  `--rebase`.** Evidence: anc1, anc2, anc3, anc9, anc10; `git log --grep=` already allows. Remedy: match at command
  position per segment, and read a quoted `-m`/`echo`/`grep` argument and a quoted-heredoc body as data
  (`strip_inert_spans` is what `merge_to_main_approval` already uses).
- **P6. `github_auto_close_keywords` denies a quoted `echo` and a `python3 - <<'EOF'` body that only print a closing
  keyword.** Evidence: ac7, ac9 (INVENTORY heredoc-body mention); real messages and `grep`/`git log --grep` mentions
  behave. Lower impact. Remedy: scan the message of a real `git commit|merge|tag`, `gh pr create|edit` segment, not
  text of the segment before it or a heredoc fed to a non-git receiver.
- **P7. `pip_break_system` and `sudo_pip` deny commands that only mention the flag or `sudo pip install`.** Evidence:
  pip1 to pip5, pip8, pip9, sp1 to sp3, sp7. The `.*` crosses `&&`, `;`, `#` and quotes. Remedy: `command_position_segments`
  with the install tokens read in the same segment (as `dangerous_permissions` does), and heredoc bodies as data.
  Keep the INVENTORY gaps (`pip --break-system-packages install`, env var, `sudo -u USER pip install`) as separate
  misses, not part of this entry.
- **P8. `gh_issue_comments` and `gh_pr_comments` deny commands that mention `gh issue view` / `gh pr view` and
  commands that do request the comments in a spelling the guard misses.** Evidence: ghc1, ghc2, ghc3, ghc9 (mention);
  ghc5 (`--json=comments`), ghc8 (a `|` inside a quoted `--jq` cuts the segment before `--json comments`). Remedy:
  command-position match, quote-aware segment end, and accept `--json=comments` and the `--json` field list. The
  two handlers differ only by names, so one shared helper fixes both.
- **P9. `subagent_full_qa_blocker` denies an ordinary `python3 script.py` run as a whole-suite test run.** Evidence: fq1
  (script imports `subprocess`, runs `ruff check .`, lists `"pytest"` in a constant), the INVENTORY fq_py_a and fq_py_b
  probes; the shell-script counterpart allows. Sub-agent role only, but the deny is hard and the script is ordinary
  dev tooling. Remedy: in the script-file chain require the program string to be the argument of the process call (not
  any literal in the file), or report UNSEEN as an advisory for a script, as the guard already does for other opaque
  commands. This may be addressed by, or may conflict with, the open decision on this 5,300-line handler
  ([RULINGS-owner-delegated-fable.md](../RULINGS-owner-delegated-fable.md), N96).

No gate for P4 to P9 means the guard stays at its present behaviour: each denies the careless agent who writes a
commit message, comment or note ABOUT the blocked command, and the deny tells the agent to rewrite; it costs a retry,
not a lost action. That is the same cost class as N400 and N401.

## 5. Task 3.2 and criterion 4

With this re-probe every guard the audit marked "not re-run" has been re-probed on current main. Criterion 4 is NOT met:
six proposed entries (P4 to P9) have neither a merged fix nor a ledger entry, so it stays unticked until the
coordinator files them in 00474 NIGGLES.md (or rules some of them correct denies). Task 3.2 as its text defines it
(every in-scope false positive narrowed or filed) is not complete for the same reason, and also because N400 to N402
and P4 to P9 are filed or proposed, not fixed; the text's condition is "narrow each guard", so the task closes when
those entries are fixed or the owner rules them.

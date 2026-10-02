STOPPING BECAUSE: the round 3 review is finished and I've sent it to team-lead.

My verdict is **do not merge** branch `worktree-n245-pathspec` at c5d04262f. The branch fixed everything round 1 asked for, but it changed the plan QA commit gate, and that gate now checks less than main does.

**Round-1 findings: all resolved.** B1, B2, B3, S1 and S2 are fixed, with probe evidence for each. The branch's own targeted tests pass (662).

**The three named gates (sensitive_content, remote_docs, staged_lint): no regression.** I ran each one against real git on 27 ordinary commit forms. Every time main blocked a commit that really did carry the bad content, the branch blocks it too. The branch only lets through commits main blocked when the real commit was clean, which is the intended narrowing.

**Blocking: the plan QA gate regressed.** The branch report says the docs QA, plan QA and guard config gates keep their earlier narrowing and that this matches main. That is true for docs QA and guard config, but not for plan QA:
- **Main:** for any commit that names paths, the plan QA gate read the files on disk.
- **Branch:** it now reads the last commit plus the named files, without the certainty check the other three gates use. The change is in `src/claude_code_hooks_daemon/plan_qa/context.py:353,357` and `plan_qa_commit_gate.py:121,128`.
- **Effect:** in each of these commands, the commit really records a PLAN.md with `Status: Blocked`. Main's gate sees `Blocked` and the branch's sees `In Progress`:
  - `cd CLAUDE/Plan && git commit -m x 00001-first/PLAN.md`
  - `git -C CLAUDE/Plan commit -m x 00001-first/PLAN.md`
  - `git commit -m x CLAUDE/Plan/README.md && git commit -m y`
- **Fix:** have plan QA use the same certainty check (`read_commit_form`, ideally via `commit_facts`), and fall back to main's disk read when the reading is not certain. Add those three cases as real-git tests.

**Follow-up (not blocking):**
- When the command starts with `cd` into a subdirectory, sensitive_content now resolves the named path from the repo root. That gives a new false positive: `cd sub && git commit -m x f.txt` is blocked because the root-level `f.txt` has the term (main allowed it). The fix is to resolve the path from the directory the command changes into.
- The remote_docs gate doesn't stand down when the command runs inside a nested worktree, as staged_lint does. Main had the same wrong-repo problem, so this isn't a regression.
- The check that every named path matches something costs two git calls per path, separately in each gate: about 0.25s per gate for 60 paths on a tiny repo.
- Several gaps exist on main as well and aren't regressions: `-am` in staged_lint and remote_docs, `git add X && git commit`, `bash -c 'git commit'` in sensitive_content, and an unstaged edit to a named path in a brand-new repo.

Nothing new needed dismissing under the threat model.

Files are in /workspace/untracked/scratch/n245rev3/:
- probe3.py
- probe_pqa.py
- probe_fp.py
- out_main.txt
- out_branch.txt
- rd2_main.txt
- rd2_branch.txt
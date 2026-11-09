# Fact check: NIGGLES.md N591 (plan 00474)

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | Tip 9aecfe3f4 is an ancestor of origin/main | VERIFIED | `git merge-base --is-ancestor 9aecfe3f4 origin/main` exit 0 |
| 2 | It was merged and pushed as 29920b2b0 | VERIFIED | 29920b2b0 "Merge Plan 00571 Phase 3 handoff", parents dbc11a463 + 9aecfe3f4; ancestor of origin/main. Push timing before the command: UNVERIFIABLE-HERE |
| 3 | Branch name agent-a2809a4ad9ef0a871-8d56f967 pointed at 9aecfe3f4 | UNVERIFIABLE-HERE | branch is gone locally and on origin (`git branch -a --list '*a2809*'` and `ls-remote` empty); 9aecfe3f4 is contained only by main/origin/main and two unrelated agent branches |
| 4 | Denied with R-GIT-PUSH-DELETE-REMOTE "not merged into the default branch" | PARTLY VERIFIED | Rule exists (destructive_git.py:924); the wording matches remote_branch_proof.py:217 "`X` is not merged into `<default>`". The denial itself is not reproducible from the tree |
| 5 | Same push alone, moments later, was allowed | UNVERIFIABLE-HERE | session history only |
| 6 | Earlier delete-branch X && git push --delete X chain was allowed | UNVERIFIABLE-HERE | session history only |
| 7 | Suspect: guard judges local ref/worktree state the earlier statements remove | PLAUSIBLE, NOT SUPPORTED | prove_remote_merged (remote_branch_proof.py:267) reads only remote-tracking refs (`refs/remotes/origin/<name>`) via for-each-ref --merged; it does not read the local branch or the worktree. A missing tracking ref gives a different message (line 180). Another cause fits: a stale local origin/main or tracking ref when the command ran, since the guard runs before the command. Only the "parse picks wrong target" suspect, or staleness, can fit |

REFUTED: none.
Note: the proposal's first suspect conflicts with the code reading above; worth adding the stale-tracking-ref hypothesis.

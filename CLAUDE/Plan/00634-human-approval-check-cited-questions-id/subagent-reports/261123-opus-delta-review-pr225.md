# Plan 00634 delta review: PR #225 after the first independent review

Scope: `ab8fc0d11..536707a79` (commits c899fe15c, cb1907266, fc63f34b2, 861562894,
24dcb2e78, 536707a79) in worktree `agent-a6328547e60968275-2a1ab764`. Light runs only.
Probe scripts are under `untracked/scratch/s-20261121T111743Z-0a12d28f/pr225-probe/`.
The probes compared the base `sets_world_writable` (from ab8fc0d11) against the head version.

## Verdict

**Safe to merge.** None of the changes to the existing handlers produces a realistic false
positive. Seat-before-classify does not fail open. Targeted tests pass: 570 passed across
human_approval_check, the detector seams, utils/human_approval, dangerous_permissions,
merge_to_main_approval and the destructive_git branch-delete and remote-ref tests.
Everything below is LOW, and nothing blocks the merge.

## (b) False positives in the existing handlers (the high-cost class)

All of these are still allowed, so no regression:

- chmod 755, 644, 0755, u+x, +x, go-w, `-R u=rwX,go=rX`, `a+r,u+w`, `o-w,a+r`, `g=u`, `ugo=rx`
- umask 022, 0022, 077, 002, 027, 0027, bare `umask`, `umask -S`, `umask -p`, `umask -S u=rwx,g=rx,o=`
- install -m 755/0644/`-d -m 0750`/`-o root -g root -m 0755`
- npm/pip/go (`-mod=mod`)/cargo/uv/make/brew/cmake `--install`/`python3 -m pip install`, `ansible-playbook install.yml -m 2026`
- setfacl `u:bob:rwx`, `u:otto:rw`, `u:o:rw`, `g:ops:rw`, `o::r-x`, `o::r`, `mask::rw`, `--set ...,o::-`, `other::r-x`
- Quoted prose: `git commit -m '... install -m 777 ...'`, a `gh pr create --body` naming setfacl/umask, `echo 'umask 000'`, `printf`
- gh: `gh pr view`, `gh -R o/r pr view|list|diff`, `gh -R o/r pr merge-queue`, `gh -R o/r issue view`, `gh --repo o/r api x`

The only detections that are new relative to base:

- `umask 0`/`1`/`4`, including inside `bash -c`, a subshell, or with a trailing comment. These
  are all correct: each leaves the world-write bit unmasked.

- Two contrived shapes:

  1. `chmod 644 a=wx`: a filename shaped like a mode.
  2. `ls /usr/share/install -m 2026`: `(?:^|[\s/])install\s` at dangerous_permissions.py:62
     accepts `install` as a PATH component of another command's argument.

  Neither is realistic. Optionally anchor `install` to command position (`(?:^|/)install`
  at the start of the segment).

Already present on base, not introduced here: `chmod 644 v1.0.2026` and
`chmod 640 report-2026.txt` are denied, because the octal mode regex has no
token-start anchor (`\b` matches after `.` or `-`). This bit this very review: the live
handler denied a probe command that contained that text. Worth a separate niggle.

gh change (merge_to_main_approval.py:69-74): the `-R`/`--repo` groups are non-capturing,
so `group(1)` still slices the segment after `merge`. Target extraction is unchanged:
`gh -R o/r pr merge 5` gives target `5`.

## (a) False negatives still open, for shapes from the first review's finding 3

Now caught:

- chmod: `a=rwx`, `o=rwx`, `ugo+w`, `00777`, `u+x,o+w`, `go+w`
- install: `install -m 777`, `install --mode=a+w`
- setfacl: `o::rwx`, `o:rw`, `d:o::rwx`
- umask: `umask 000`, `umask a=rwx`
- `gh -R`/`--repo`/`--repo=` placed before `pr` or `merge`
- gh api: `pulls/N/merge`, `/merges`
- Moves of main: `fetch . x:main`, `update-ref refs/heads/main`, `branch -f main`, `checkout main && merge`, `checkout - && merge`
- `send-pack` (push)
- Deletes: `tag -d`, a gh api DELETE of `git/refs`, `rm .git/refs/...`

Still missed, in rank order:

1. `git -C /workspace merge x`, issued from a worktree cwd, gives `[]`. The merge is
   still judged against the hook's cwd, not against `-C` (finding 3, last bullet). Not fixed.
2. Permission:
   - `install -m777` and `install -Dm777`: no space, or a combined short flag. The pattern
     at dangerous_permissions.py:62 needs `-m` as its own token start.
   - `setfacl -m o::7`: numeric ACL perms, :64.
   - `chmod 0o777`, `chmod o=u`, `chmod =rwx`: the last depends on umask.
3. `gh --hostname h pr merge 5`: only `-R`/`--repo` are allowed between `gh` and `pr`
   (merge_to_main_approval.py:70).
4. `git cherry-pick abc` on a feature-branch cwd gives `[]`. This is correct: the merge is
   judged against the checkout.

## (c) Seat before classify (human_approval_check.py:372-409)

- **No team:** unchanged. An empty runtime returns False before any probe (:385).
- **Unreadable seat stays armed:** UNRESOLVED is armed by `is_armed` (utils/human_approval.py:324).
- **Exceptions:**
  - An exception from `resolve()` itself is still silent (:392-398).
  - That is acceptable: `TeamSeatResolver.resolve` is documented never-raises
    (teamchat_seat.py:706), and the code is unchanged from before the delta.
  - A classify exception for an armed seat now returns True, and `handle` then refuses
    (:403-409, :423-429). The test at test_human_approval_check.py (finding-4 block) covers both sides.
- **Cost (LOW):**
  - Every Bash call in a teamchat-runtime session now resolves the seat (TTL-cached).
  - For an armed seat, every Bash call also runs `default_branch(cwd)`: 1-3 git
    subprocesses, even for `ls`. `moves_main` calls it unconditionally (:249-250).
  - The handler ships `enabled: true, mode: advise`.
  - Suggestion: compute `defaults` lazily, only once a run is a switcher, mover or ref-writer.
- **Behaviour (LOW, new handler only):** `git fetch origin main:main` and
  `gh api repos/o/r/commits?merges=1` classify as MERGE_MAIN. `_GH_API_MERGE` matches
  `merges` anywhere after `api` (:162-164). It fails closed and is advise-only today.

## (d) The changed test

`test_no_act_never_asks_the_resolver` became `test_no_act_is_silent_for_an_armed_seat`
(test_human_approval_check.py, TestArming). The old assertion that the resolver is never
called is now false by design, so dropping it is correct. The new test still asserts that
`git status` gives False for an armed COORDINATOR. With the order inverted, that is the
meaningful property, so the test was not weakened.

Event id (finding 6): `_EVENT_ID` (utils/human_approval.py:62) now excludes `/`, `.` and
`~`. Rejection only refuses a cite, so it fails closed.

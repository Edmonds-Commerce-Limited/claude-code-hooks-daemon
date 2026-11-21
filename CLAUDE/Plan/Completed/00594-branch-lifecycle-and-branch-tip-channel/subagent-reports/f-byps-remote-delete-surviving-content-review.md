# F-BYPS review: the remote-delete tier (Plan 00594 Task 3.8, after Plan 00626)

Check: `F-BYPS`. Delta: branch `agent-a20c91c23eca4e56e-43e33957` at `b0c596d5f` compared with `origin/main`.
Guard: `core/remote_branch_proof.py` (surviving-content tier), `core/branch_cleanup.py`
(`delete_remote_branches`, `_push_deletes`), `handlers/pre_tool_use/destructive_git.py`
(`_remote_delete_note`), `daemon/cli.py` (`delete-branch --remote-only`).
Question: does any in-scope route reach a remote delete of a branch that holds unique content without passing the proof?

Totals: 4 findings (High 0, Medium 2, Low 2). 7 angles looked at and found clean or dismissed.

## Finding 1 (Medium, introduced by this diff): the tracking default sets the merge base but is never confirmed live

- **Citation.** `remote_branch_proof.py:465-467`: `merge-base tracking_default tracking_ref` is the base the
  net change is diffed from. At `:758-761` and `:779`, `content_anchors[name] = finding.holders`, and the
  live check (`_live_tip_problems`, `:832-846`) confirms only these anchors. `finding.holders` is only the
  holders that matched a path (`:487-490`), so when every path is held by an integration line, the
  default's sha is never compared with `ls-remote`.
- **What it allows.** Suppose remote `main` was rewound (a human force-push, or another clone's) and dropped
  commit C, which added file X. The local `origin/main` was not fetched and still contains C, and `feat`
  was branched after C. `merge-base(origin/main, feat)` is then at or after C, so X is not in the diff.
  If `feat`'s own changes are all held on `release/1`, the proof accepts `feat` and the live check passes,
  because only `release/1` is anchored. The delete then loses X, whose only remaining copy was `feat`.
  The ancestry tiers do not have this gap: their anchor is the default (`:779` fallback).
- **Threat-model test.** In scope. The agent types an ordinary `git push origin --delete feat` or
  `delete-branch --remote-only feat` against a stale checkout. Nothing is hidden from the daemon and no
  parser is defeated. The input is ordinary repo state that the proof claims to verify.
- **Class.** A proof input that decides the verdict, here the merge base, is read from a remote-tracking ref
  that the live re-check does not confirm. The rule: every ref whose sha the proof reads must be in the anchor set,
  not only the refs that were credited.
- **Why tests miss it.** `test_a_default_moved_on_the_remote_since_the_fetch_refuses` (`test_surviving_content_proof.py:348`)
  moves the default where the default is also the holder that gets credited. It is therefore anchored, and the test passes.
  No test moves or rewinds the default while an integration line holds all the content.
- **Detector hypothesis.** In `_merged_tracking_tips`, every ref passed to a git call as a proof input
  (`merge-base`, `--merged=`, `ls-tree`) must appear in `anchors[name]`. You could assert this
  structurally by recording the refs read for each name and comparing them with the anchors in a unit test. Likely
  false positives are refs read only to list candidates (`for-each-ref` over the namespace).
- **Confidence.** Medium; this comes from reading the code and was not executed. To settle it: clone A pushes `main`
  with C, `feat` from C, and `release/1` holding `feat`'s own change. Clone B force-pushes `main` back to before C.
  In A, without fetching, run the proof on `feat`. Expected: refused. Predicted actual: accepted with
  `surviving-content`. Fix shape: always include the default in `anchors[name]` for this tier.

## Finding 2 (Medium, pre-existing, overlaps F-GAP): `gh` deletes a remote branch with no proof

- **Citation.** No handler under `handlers/pre_tool_use/` reads `gh pr close --delete-branch` / `-d` or
  `gh api -X DELETE repos/{o}/{r}/git/refs/heads/<name>` (searched `delete-branch`, `pr close` and `DELETE`;
  the only hits were docs strings and unrelated handlers). `destructive_git._remote_delete_note`
  (`destructive_git.py:869`) judges only `git push` invocations.
- **What it allows.** `gh pr close 42 --delete-branch` on an unmerged PR deletes the head branch on GitHub.
  The proof never runs, so it does not matter whether the content is unique.
- **Threat-model test.** In scope. It is the documented, ordinary way to close an abandoned PR, the
  operative text is literal, and it has a working purpose. It is not recorded in
  `dangerous-invocation-corpus.yaml` (grep found no `gh pr close` or `git/refs` rows).
- **Class.** A protected outcome that can be reached through a second client (`gh`, a REST call) for which the guard has no
  parser. The guard is keyed on the git spelling, not on the outcome.
- **Why tests miss it.** The tests drive `git push` shapes only. A route with no handler appears in no diff
  and no test.
- **Detector hypothesis.** Add corpus rows (`UnenumeratedSpelling` Defence) for `gh pr close N -d`,
  `gh pr close N --delete-branch`, `gh api -X DELETE .../git/refs/heads/x` and `gh api --method DELETE ...refs/heads...`,
  each expecting a deny. False positives: `gh pr merge --delete-branch` after a real `--merge` (the
  branch is merged; the proof would accept it). It should be judged, not denied blindly.
- **Confidence.** High that nothing judges it (grep), medium on the exact gh flag spellings. To settle it, drive
  the rows through `scripts/qa/check_dangerous_invocation_corpus.py`.

## Finding 3 (Low, pre-existing, widened by the tier): `ls-remote` reads the fetch URL and the delete goes to the push URL

- **Citation.** `utils/remote_refs.py:101-106` runs `git ls-remote <remote>`, which uses `remote.<r>.url` / `insteadOf`.
  A raw `git push <remote> --delete x` allowed by the hook uses `remote.<r>.pushurl` / `pushInsteadOf`.
  There is no `pushurl` handling anywhere in `src/` (grep).
- **What it allows.** In a triangular setup (fetch from upstream, push to a fork), the proof confirms upstream's
  `feat` and holder tips. The hook-path delete (no lease) then removes the fork's `feat`, which may hold
  different, unpushed-upstream commits. On the leased route, the lease makes the fork's `feat` tip match
  the proven sha, so commits are not lost there. The holders are still unverified on the push side,
  but the content survives upstream.
- **Threat-model test.** In scope. The configuration is pre-existing repo state, and the typed command is ordinary.
- **Class.** The verification and the mutation address different endpoints of the same remote name.
- **Why tests miss it.** Every fixture's remote is one bare repo with no `pushurl`.
- **Detector hypothesis.** Refuse (fail closed) when `git remote get-url --push <r>` differs from
  `git remote get-url <r>` in the remote-delete proof. False positives: SSH-push/HTTPS-fetch to the same repo,
  which is common, so this check would be noisy unless the URLs are normalised.
- **Confidence.** Low to medium. To settle it: build a fixture with `pushurl` set to a second bare repo whose `feat` differs.

## Finding 4 (Low, pre-existing): the hook route deletes without a lease, and no route leases the holders

- **Citation.** `destructive_git.py:909` proves at PreToolUse, and the agent's own `git push --delete` then
  runs unleased. `branch_cleanup._push_deletes` (`:1246-1254`) leases only the deleted refs, not
  the anchors (holders).
- **What it allows.** A commit that another agent pushes to `feat` between the hook verdict and the push is
  lost (hook route only). A holder that is force-rewritten between the proof and the push loses the
  credited content on either route.
- **Threat-model test.** The first case is in scope (concurrent agents, ordinary command) and the window is narrow. The holder case
  needs a force-push, which `R-GIT-PUSH-FORCE` already gates (though it allows `--force-with-lease`).
- **Class.** A proof/act race (TOCTOU) between a guard verdict and an unleased mutation.
- **Why tests miss it.** The tests are single-actor and sequential.
- **Detector hypothesis.** Any allowed remote-mutating command whose verdict depends on a remote sha that
  the command itself does not lease. False positives: every allowed `git push` (noisy as a general rule).
  It is precise if restricted to delete verdicts: the hook could deny raw deletes outright and point to `--remote-only`,
  which it already recommends.
- **Confidence.** High that the race exists, and low on its practical frequency.

## Looked at, nothing found (or dismissed)

- **Refspec injection.** `named_ref_problem` (`remote_branch_proof.py:152-159`) uses the ASCII
  `LITERAL_BRANCH_NAME`, so `:`, globs, whitespace and unicode are refused. `+x` and `heads/x` map to tracking
  refs that do not exist and are refused. Unknown push flags are `_Unverifiable` (`destructive_git.py:844-852`).
  A source-bearing refspec is not a delete. `ls-tree` uses `--literal-pathspecs` and `--`.
- **Tags compared with branches.** A local tag with the same name is refused (`:672`). A remote-only tag plus a live branch
  makes git reject the delete as ambiguous. The live check requires `refs/heads/<name>`, and `_push_deletes` uses a full `refs/heads/`.
- **`ls-remote` failure, timeout, empty or partial output.** `run_git` maps a timeout to a nonzero exit
  (`git_repo.py:256`). A failed chunk adds nothing, and a missing name or anchor is refused (`:837`, `:845`). This is fail-closed.
- **Same-batch vouching.** `doomed` covers `names` plus `also_deleting` (`:739`). The hook passes the whole
  multi-push batch (by name, which is conservative across remotes). The sweep (`branch_cleanup.py:1168`) proves
  its batch in one call, so `names` is already doomed. A same-command `--force-with-lease` rewrite of a
  holder is not a delete, and it destroys the holder's own content anyway: that belongs to the force-push guard, so it is dismissed here.
- **Stale or renamed symbolic default.** `resolve_remote_default_branch` reads only `origin/HEAD`. A stale HEAD
  naming the old default keeps that branch refusable as `default`, so content it holds survives until it is itself proven against the
  new default. No loss is reachable, except through Finding 1's rewind case.
- **Offline fallbacks.** The tier is never cached. `ProofUnavailableError` leaves the branch unproven (`:751-757`).
  A local `main` fallback is refused (`:885-900`). `--remote-only` rejects `--dry-run`/`--protected-ref`.
- **Net-diff only.** A file added then changed or removed within the branch loses its intermediate revisions.
  Dismissed as designed: the tier is defined on tip content, and test `:164` pins it. It should be stated in the
  release note so nobody reads `surviving-content` as "no history lost".

# Plan 00624 Phase 2 design: park without a branch commit

Owner's design 1. Phase 1 (`subagent-reports/repro-findings.md`) shows #210 and #211
already fixed on main; this phase removes the cause: the marker on the branch.

## Shape

- `branch-park <name>` writes the SAME marker commit as today (tree = tip's tree,
  same `Park branch:` message and trailers, `commit-tree -S` when `commit.gpgsign`
  is true) but points `refs/parked/<name>` at it. `refs/heads/<name>` is untouched.
- A ref park **stands** while the marker is a park message (not `Unpark branch`) and
  its FIRST parent is the branch tip.
- **Fast-forward only, no force push anywhere:** a re-park or unpark marker has
  parents `[tip, previous marker]` when a previous marker exists, so the ref only
  ever fast-forwards. `--clear` writes an `Unpark branch` marker on the ref (never a
  delete push, which `R-GIT-PUSH-DELETE-REMOTE` would judge).
- Push: `git push --atomic <remote> <name> refs/parked/<name>` for a local branch
  (keeps today's "park pushes the branch"); `refs/parked/<name>` alone for a
  remote-only branch (no local branch is created any more). Retry hint:
  `git push <remote> refs/parked/<name>` (no `+`, so no force-push guard).
- The git-config park record (`branch.<name>.hooksDaemonParked*`) is still written,
  with `sha` = the tip, so every existing local overlay keeps working unchanged.
- `branches.park.marker: ref | branch` (default `ref`); `branch` keeps the old
  on-branch commit for a forge that refuses custom ref namespaces. `park_branch`
  takes `on_branch: bool`; legacy-fixture tests pass `on_branch=True`.

## Readers (one accessor)

- `read_park_records` merges config records with ref parks (one
  `for-each-ref refs/parked/` with `%(objectname) %(parent)` + trailers): a ref park
  yields `ParkRecord(sha=first parent, reason, parked_at=committer time, by)`. On
  conflict the newer `parked_at` wins; a newer `Unpark` marker cancels.
- Overlays that today require a LOCAL ref must also accept a remote-tracking row whose
  tip equals `record.sha` (a park made in another clone):
  `branch_inventory` (~line 1228, `local.sha == row.sha` guard) and
  `branch_creation._with_standing_park` / its `standing` filter (~line 402,
  `ref.local`). That is pool placement only.
- `branch_stop_guard._handed_over_by_park` and `announce_ended_parks` already go
  through the record; no change.
- `--clear` order: standing ref park -> Unpark marker on the ref; record-only park ->
  clear record (today); tip carries a legacy `Parked-Reason` trailer -> legacy signed
  `Unpark` commit on the branch (compat); nothing parked -> error, no commit.
- Old on-branch markers stay readable: all tip-trailer readers and the `park-carried`
  / `empty-commits-only` proofs are unchanged.

## Visibility in other clones

Hook paths are offline. Add `git_sync.fetch_parks(root, remote)`:
`git fetch --no-tags --quiet <remote> +refs/parked/*:refs/parked/*`, a separate
fail-silent call after `fetch_all` in `git_upstream_checker` (session start), so a
missing namespace never fails the main fetch. Do not edit the client's remote config.
Not yet verified against a real forge that a custom `refs/parked/*` namespace is
accepted and is outside signed-commit rulesets; record it as unverified in the note.

## Safety (no loosening)

- A park ref only moves a branch between pools / exempts it from dormancy, exactly
  as a forged on-branch marker can today. It must never feed a merged or deletable
  proof: `utils/remote_refs.holder_of` must skip `refs/parked/` (otherwise an
  `ls-remote` listing would read the marker, which descends from the tip, as
  `remote-held`). Branch-safety containment scans only `refs/remotes/<remote>`, so it
  is unaffected; add a test that pins it.
- Tests: an unmerged parked branch is still `unproven` in `classify_branch` and
  refused by `prove_remote_merged`; `holder_of` ignores a park ref.

## Test plan (RED first, new file `tests/unit/core/test_branch_park_ref.py`)

Tip unchanged and ref marker shape; pushed ref on the bare remote; inventory PARKED
with reason (local, and remote-only from a second clone after `fetch_parks`);
re-park fast-forwards with the new reason; same reason refused; clear writes Unpark
and the branch reads unparked; new work after a park ends it; signed marker with the
fake-gpg helper from `test_branch_park_signing.py`; legacy on-branch park still
parked and its clear signed; remote-only park and its push-failure retry; the
safety tests above. Then re-run the existing park test files and switch tests
that assert an on-branch marker to `on_branch=True`.

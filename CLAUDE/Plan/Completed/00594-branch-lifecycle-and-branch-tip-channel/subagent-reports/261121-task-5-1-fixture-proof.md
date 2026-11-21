# Task 5.1: branch-channel proof in the offline client fixture

Branch `plan-00594-finish`. Fixture `scripts/dummy-client-repo.sh create --bare-remote`
(commits 357106069, 4d359721a), proof `scripts/dummy-client-branch-channel-proof.sh`
(ad178f1f9, 98102a235). Run on 21 November against fixture HEAD 4d359721a, tagged
`v3.76.0` in the bare remote only.

## How it is offline

- The daemon dir is a plain clone (`--no-hardlinks`, no alternates) of
  `untracked/dummy-client-repo-remote.git`. The bare is seeded by a fetch INTO it from
  this repository by path, so nothing is configured in, pushed from, or run in this
  repository. Its `origin` is that absolute path. The helper refuses any URL, any
  relative path and any non-bare repository.
- `create` and the proof ran with `GIT_ALLOW_PROTOCOL=file` (any https/ssh git access
  fails) and `UV_OFFLINE=1`. The upgrade's helper-download base URL is an unusable
  `file://` path. The tracked branch and its moves were made in a scratch clone of the
  bare and pushed to the bare.

## Result: every step passed (exit 0)

| Step                           | Asserted                                                                                                                                                       |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0 start                        | stamp `v3.76.0`, daemon dir on the tag                                                                                                                         |
| 1 track `proof/branch-channel` | daemon dir on tip `13e9c60`, `tracked_ref`, `tracked_sha` and `last_release_tag=v3.76.0` recorded                                                              |
| 2 report                       | "Tracked ref proof/branch-channel has not moved since 13e9c60"; the way back names v3.76.0                                                                     |
| 3 move on the remote           | "tracked ref proof/branch-channel moved 13e9c60..fd86a69"                                                                                                      |
| 4 failed listing               | "not checked (the remote could not be read)"                                                                                                                   |
| 5 re-track                     | daemon dir and `tracked_sha` follow to `fd86a69`; `last_release_tag` kept; reported not moved                                                                  |
| 6 `upgrade.sh --release`       | back on the tag, stamp `v3.76.0`, tracking metadata cleared                                                                                                    |
| 7 sha pin, then `--release`    | the full sha is recorded as the ref; "Pinned to commit 13e9c60; a pin never moves." with the listing pointed at a missing path; back on the release afterwards |

The run also started with a `--release` return from the state an earlier, failed run
left, so the one-step return was exercised three times.

## What this does not prove (findings)

1. **The move check does not list the client's origin.** `version_check._remote_tip`
   lists the fixed GitHub URL from cwd `/`, while `upgrade.sh` fetches `origin`. The
   report steps therefore rewrote that URL to the bare with a global-scope
   `url.<bare>.insteadOf` in a private `GIT_CONFIG_GLOBAL`, for the handler subprocess
   only (never in the upgrade's environment). The report LOGIC is proven against a real
   listing. Whether a client on a mirror origin is told about the right remote is not
   proven. This is by design (see the `_REMOTE_ONLY_CWD` comment). It is recorded here
   for the owner, not changed.
2. **The tip cache.** It is keyed by ref and installed sha with a TTL, so within the TTL
   a cached "has not moved" hides a move. The proof ran the handler with a zero TTL and
   emptied the tip cache before each report. A real session sees a move only after the
   TTL ends.
3. **The pre-deploy gate asked for the reading confirmation** on every branch install
   (9 UNRELEASED notes). The proof answered with the digest the gate printed, as a
   client is told to. `--release` did not ask.
4. The handler was driven in-process (`VersionCheckHandler().handle(...)`) under the
   fixture's venv interpreter. A real session start through the running daemon was not
   used, because a SessionStart through the daemon could not carry the URL rewrite
   without putting it in the daemon's environment.
5. No client seat report exists. Per DESIGN §7.1 that is evidence to add later, not a
   gate.

## Re-running

```
GIT_ALLOW_PROTOCOL=file UV_OFFLINE=1 scripts/dummy-client-repo.sh create --bare-remote
scripts/dummy-client-branch-channel-proof.sh
scripts/dummy-client-repo.sh destroy
```

`destroy` does not remove the bare remote; the next `create` replaces it.

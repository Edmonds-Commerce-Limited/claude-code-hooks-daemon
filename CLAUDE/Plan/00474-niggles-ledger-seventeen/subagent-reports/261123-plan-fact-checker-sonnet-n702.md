# Fact check: N702 (branch-park parks on a stale local tip)

Result: 8 claims, 7 verified, 0 refuted, 1 unverifiable.

| #   | Claim                                                                                                          | Verdict           | Evidence                                                                                                                        |
| --- | -------------------------------------------------------------------------------------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `park_branch` is at `core/branch_park.py:656-729`                                                              | VERIFIED          | def at 656, last return at 729                                                                                                  |
| 2   | It resolves `refs/heads/<name>`                                                                                | VERIFIED          | :684-685 rev-parse of `{_HEADS}{name}`                                                                                          |
| 3   | It writes the park commit on that tip, moves the ref, records the park                                         | VERIFIED          | :706 `_write_park_commit(repo, old, ...)`, :707 `update-ref`, :713 `_record_park`                                               |
| 4   | It then runs a plain `git push`                                                                                | VERIFIED          | :719-726 `git push <remote> <name>`, no force                                                                                   |
| 5   | It never fetches and never compares the local tip with `<remote>/<name>`                                       | VERIFIED          | grep "fetch" in the file hits only :605 and :622 (comments, in `_park_remote_only`). Nothing in :656-729 compares the two tips. |
| 6   | The only `remote_ref` use is the no-local-branch path, :686-697                                                | VERIFIED          | defined :686, used :692 and :696, both inside `if verified.returncode != 0`                                                     |
| 7   | A failed push returns a `ParkResult` carrying `push_error` and a retry line (:727-728), leaving the local park | VERIFIED          | :727-728; fields at :72-80 match; ref already moved at :707                                                                     |
| 8   | The fedora-desktop.1 report sequence, and "not on the v2 path"                                                 | UNVERIFIABLE-HERE | The plan flags the report as unverified itself. No file here settles it.                                                        |

Nothing REFUTED.

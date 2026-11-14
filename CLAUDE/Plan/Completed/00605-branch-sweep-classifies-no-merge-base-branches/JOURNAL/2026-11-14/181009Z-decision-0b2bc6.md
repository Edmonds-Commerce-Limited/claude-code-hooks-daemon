## 18:10 · decision · — — follow-up: work-queue done caches the issue it just finished

Third follow-up, found at the first stop after closing #203.

R-STOP-IDLE-WITH-WORKABLE-ISSUE denied the stop, naming #203 as workable even though it was closed. The issue-sdlc runbook runs `work-queue done` (Step 7) before it closes the issue (Step 8). `work-queue done` calls `refresh_workable_cache` while the issue is still open, so it caches the issue it has just finished as the next workable one, and printed "next workable issue: #203 - start it now". Nothing drops a closed issue from the cache: `remove_workable` is called only from `issue_validity_cli`. Running `issue-validity --list-eligible` rewrote the cache to empty, which is correct because every open issue carries `agent-needs-human`.

Fix: `work-queue done` should leave out the issue named in the queue entry (`issue-<N>-...`), or the runbook should close the issue before `done`. A regression test should finish a queue entry for an issue that is still open and assert the cache does not list it. This waits for a branch, like the other two follow-ups.

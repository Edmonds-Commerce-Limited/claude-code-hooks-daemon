# Fact check: N596 entry (NIGGLES.md diff)

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | Failing assertion at test_provision_sh.py:1349 | VERIFIED (as call site) | Line 1349 is `state = _outcome(fresh, MAIN_VERSION)` in test_a_pulled_upgrade_is_synced_after_the_hook_has_answered (def at 1324). |
| 2 | `_state` is at line 1117 and asserts "no state recorded at ..." | VERIFIED | Line 1117: `assert path.is_file(), f"no state recorded at {path}"`; `_state` def at 1114. |
| 3 | `_outcome` reaches `_state` | VERIFIED, line 1278 | `_outcome` def at 1272; calls `_state` at 1278. |
| 4 | Failure came "via `_outcome` -> `_state`" with the file missing | REFUTED as written (logically inconsistent) | `_state` is called at 1278 only inside `if path.is_file():` (1277). A never-written file therefore cannot trip line 1117 through `_outcome`; it would time out with "the background sync to X did not finish within 60.0s" (1282). The only other `_state` call (1344) is guarded by `not state_after_hook.exists() or`. So the 1117 message can only occur if the file existed at 1277 and vanished before 1278's read (e.g. non-atomic rewrite/removal), or the quoted message is misattributed. The "detached sync not yet written the file" explanation does not fit that message. |
| 5 | `_outcome` waits by a bounded poll (not single read) | VERIFIED | 1274-1282: deadline loop, 0.1s sleep, returns on non-"running" status. |
| 6 | Its bound uses scaled_seconds | REFUTED (the entry leaves it open; answer is no) | `_outcome` default `timeout: float = 60.0` bare number; no `scaled_seconds` or `load_scaling` import anywhere in test_provision_sh.py (grep of "scaled_seconds"/"load_scaling" found none). `scaled_seconds` exists at tests/load_scaling.py:64. |
| 7 | Forwarder starts the sync detached (`setsid ... &`) after the hook answers | VERIFIED (detached) | .claude/hooks/session-start:25-28: `setsid bash .../provision.sh --background < /dev/null > /dev/null 2>&1 &` (nohup fallback at 28). The test's `answered_first` check (1343-1345) asserts the hook answers before the sync finishes; ordering relative to the hook's answer was not traced in the script beyond the backgrounding. |
| 8 | CI run ids, shard counts, timings (42421806919, 313 passed/1 failed, 1,491 s) | UNVERIFIABLE-HERE | Needs `gh run view`. Commit 83044eb95 exists in recent git log (HEAD is 845988931). |

## Consequence for the plan
Claim 4: the Proposal ("poll to a scaled bound for the state file to exist AND reach terminal state") already matches what `_outcome` does apart from the unscaled 60 s. The assertion text recorded in Evidence does not come from a missing file via `_outcome`; recheck the actual CI log (it may be line 1344/1117 or a vanish race) before choosing the fix.

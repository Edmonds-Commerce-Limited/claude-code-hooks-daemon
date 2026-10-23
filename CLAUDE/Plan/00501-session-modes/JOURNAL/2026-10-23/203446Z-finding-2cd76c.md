## 20:34 · finding · —   — Second goal-loop true positive

Second goal-loop true positive (Task 7.3 count: 2 of 3).

The coordinator session c61663f0 looped on the supervisor's goal for Plans 00476 and 00501 after both were done or
blocked (journal 203356Z): every stop was a declared `[awaiting-human]` stop and the goal evaluator returned the same
"not verified as totally blocked" verdict each time. `hooks-daemon mode-history` in observe mode:

- 20:33:41 `would-enter goal-blocked -- cycles=3 threshold=3 declared=1/3 window=30m span=1270s similarity=0.16,0.25`
- 20:34:08, 20:34:16, 20:34:24 `would-enter goal-blocked -- cycles=2 threshold=2 declared=2/2` (fingerprint
  1a15f28d7a7d), alternating with `near-miss ... cycles=1`.

A real loop, correctly flagged: no false positive. Observation for the 7.3 tuning: in observe mode the detector logs a
fresh `would-enter` on each further pair of declared stops (every few seconds here) rather than once per loop, so the
observe log grows with the loop; worth deciding whether observe should log once per fingerprint as act enters once.

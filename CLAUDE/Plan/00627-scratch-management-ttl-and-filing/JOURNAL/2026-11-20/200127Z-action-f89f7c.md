## 20:01 · action · —

Task 3.8 precondition, unit 1 of the design handoff: removal's proof now reads the events file.

`remove_claimed` and `resume_claimed` take required keyword arguments `clock` and
`retention_hours` (no defaults, so a caller cannot forget them). `_removable` refuses, under the
store lock, an archive whose events file has a torn tail, whose id is incomplete, whose effective
expiry (keeps included) is at or before now, or when the clock raises or returns a naive instant.
The rule lives in a new public `require_not_due` in `scratch_archive_expire.py` (raising the new
`Due`), so `_Hold` and `_keeps` stay private.

Resume: a refused archive is skipped when the whole tree verifies against it (rename-back is
safe), and leaves a partly removed tree `stuck` ("a human restores from it").

Tests: expired event, retention-due, keep extending the expiry, not-yet-due, null expiry, torn
events tail, raising and naive clocks, resume intact-and-due (renamed-back), resume partial-and-due
(stuck, tree and archive untouched). The batch tests pass a clock before their records are due.

Residual: expiry does not know a leftover `.sweeping-` claim; Task 3.8 must run `resume_claimed`
before `expire_due`. DESIGN section 13 row closed with the how.

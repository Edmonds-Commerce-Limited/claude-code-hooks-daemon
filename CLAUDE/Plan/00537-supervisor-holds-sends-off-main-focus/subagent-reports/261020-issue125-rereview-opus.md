# Issue #125: re-review verdicts (code-reviewer, Opus)

The reviewer replied inline; these are its verdicts as recorded by the coordinator.

## Re-review of 25f9d3a45..1ef47d451: CHANGES REQUIRED

- **I1 approved.** A payload held at apply time skips `import_state`, the bookkeeping and `line.clear()` for every
  family. The worker re-imports the host's machine state each tick, so nothing is sent twice after the hold ends.
- **C1 had one must-fix.** `feed()` settled a pending Esc against the host's READ time. A split arrow whose second
  half was read 0.5 s or more late was therefore taken as a bare Esc: the arrow was missed (probe case G), or a
  live hold was released (case H).
- **Suggestion, taken.** A non-arrow CSI split across reads, such as the bracketed-paste start
  `ESC[200 | ~` (case I), cleared the hold.

## Re-review of 3afb238dc (head 951eb22b9): APPROVE

- Probe cases G, H and I all read HELD, and the test file passes (89 tests).
- `_fd_readable` fails toward hold: when stdin cannot be checked, it reports bytes waiting.
- Non-blocking: an `ESC [` or `ESC O` prefix that never completes holds until the next key. A lone Esc just
  before stdin closes never settles, which is harmless because no human is left to clear it.

The probes are working files in `untracked/`, which is not tracked: `261020-issue125-review-probe.py` and
`261020-issue125-rereview-probe.py`. Their cases are carried as tests in
`tests/unit/supervise/test_main_focus_hold.py`.

## 12:34 · decision · —

Phase 4 was decided by a sub-agent under the owner's delegation of 2 November 2026: "pick clear winners using sub agent, raise with me if its really not clear". Each decision had a clear winner, so nothing was raised with the owner. The full reasoning is in `subagent-reports/261102-phase4-winners.md`.

- **Task 4.1:**
  - accept the partial defence;
  - do not build the wider data-flow rule now;
  - confirm all three calibrations.
- **Task 4.2:**
  - confirm stand-in rulings 1 and 2;
  - a client install may not read the daemon logs while the daemon is down.

The logs ruling rests on three facts:

- The daemon's output goes to `/dev/null`, so no daemon log file exists.
- A failed build is already fail-open.
- The directory also holds payload captures.

These follow-ups became Task 4.3:

- `status` reports `.daemon-down-stops.log`.
- `untracked/hook-errors.log` is denied while the daemon is down.
- `diagnose` prints the tail of the build log.

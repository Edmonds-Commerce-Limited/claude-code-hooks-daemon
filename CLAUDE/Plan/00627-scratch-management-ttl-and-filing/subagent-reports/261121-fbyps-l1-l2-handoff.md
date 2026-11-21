# F-BYPS L1/L2 fixes (pressure-mode consent) handoff

Source review: `untracked/agent-reports/fbyps-00627-pressure-consent.md` (main checkout).
Branch `agent-acff915e4bf3b86e6-0a26f829`, both commits pushed.

## Commits

- `01886ee60` L2: an unbound `Pressure` (`consented=None`) now packs NO not-yet-due entry.
  `_candidate` (what the question counts and `consent_to` binds) is split from `_pressured`
  (the apply gate, which requires a bound consent set). `pressured_count` counts candidates,
  restricted to the consented set when bound. The core test helper `pressed()` now binds consent
  explicitly from what is on disk (`on_disk()`); no test relies on an unrestricted None.
  Test: `test_pressure_passed_straight_through_without_consent_packs_nothing_not_due`, which was red
  before the fix. A due entry in the same run is still archived.
- `183ca58f3` L1: consent is keyed by identity. `Pressure.identities` holds `(path, BirthStamp)`
  pairs (device, inode, birth time from `utils/birth_time.py`), read by `consent_to` through an
  `open_dir` fd per report part. A session part must still match its recorded identity.
  `_apply_row` requires, for a not-due row, the current `birth_stamp(root_fd, name)` to equal the
  consented stamp. `record_claim` then ties that inode to the fingerprint. It fails closed: a stamp
  that is None or unreadable at the prompt leaves the entry out of `consented`, and the question does
  not count it. The same at the run gives `refused`.
  Tests:
  - `test_an_entry_replaced_under_the_same_name_after_consent_is_not_packed`: the replacement is
    built under another name and renamed into place, so it gets a new inode. Red before the fix
    (`archived`).
  - `test_the_same_entry_is_still_packed`: the positive control.
  - `test_no_birth_time_packs_nothing_not_due[consent|apply]`.
  - `test_an_entry_whose_identity_cannot_be_read_is_not_consented_or_counted`.

## QA (targeted)

- black, ruff, pyright and `audit_error_hiding` are clean on both touched files.
- semgrep is clean on the source file. The test file has one pre-existing
  `pathlib-quadratic-containment` hit at the `snapshot()` helper (`path.relative_to`). That line is
  from fb3188bcca and was not touched.
- `tests/unit/core/test_scratch_archive*.py`, `test_scratch_sweep.py` and
  `tests/unit/daemon/test_cli_scratch_*.py`: 741 passed, 5 skipped.
- The full gate was not run. That is for the coordinator.

# Plan 00601 findings

## Task 1.1: is a main-thread usage-limit stop recorded with its reset time?

A `rate_limit` stop is recorded, but not with a reset time.

- `stop-failures.json` holds records of `session_id`, `error` (for example `rate_limit`), `recorded_at` and `resolved_at`. No field carries a reset time.
- `usage-snapshot.json` holds the reset time separately, as `resets_at` per window (`seven_day` seen in this checkout), with `used_percentage` and `observed_at`.
- The reset time can therefore only be joined at read time, to the usage window that is at its limit. When no live snapshot exists the stop has no reset time at all, so a consumer must treat `resets_at` as optional.

The implementing agent reported this answer in one sentence; its own longer write-up was refused by the Write tool and was never saved. The details above are what this session verified directly (the record fields and the snapshot shape). The `five_hour` window and the exact join rule are still to be checked against the writers in `handlers/stop_failure/stop_failure_recorder.py`, `utils/stop_failure_records.py` and `core/usage_snapshot.py`, and the session-state command's own tests (`tests/unit/core/test_session_state_document.py`) pin the join the command performs today.

## Task 1.2: records the command reads

| Record                   | File in `untracked/`                |
| ------------------------ | ----------------------------------- |
| session-mode transitions | `session-mode-transitions.jsonl`    |
| stop events              | `stop-events.jsonl`                 |
| stop failures            | `stop-failures.json`                |
| usage snapshot           | `usage-snapshot.json`               |
| usage-ceiling pause      | read through the `usage-pause` verb |

The command reads them through `core/session_state_document.py`; consumers never read the files.

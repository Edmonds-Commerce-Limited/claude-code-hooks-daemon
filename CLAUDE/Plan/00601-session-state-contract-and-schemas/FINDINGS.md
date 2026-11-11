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

## Task 3.3: cost per call

Measured on this daemon's own `untracked/` (4.1 GB directory; `stop-events.jsonl` 1.0 MB, so the bounded 256 KiB tail is fully used), best of 10-15 in-process runs, interpreter start-up excluded:

| What                                                                     | Best      |
| ------------------------------------------------------------------------ | --------- |
| `build_session_state`, session with a recorded stop                      | 0.45 ms   |
| `build_session_state`, unknown session (scans the whole 256 KiB tail)    | 1.65 ms   |
| `cmd_session_state --json` end to end, before the fix (daemon running)   | 36.5 ms   |
| `cmd_session_state --json` end to end, after the fix                     | 25.4 ms   |

The document build is not the cost. The profile showed `get_project_path` running twice per call (once for the untracked directory, once inside the IPC helper), and each run validates the whole config through pydantic (about 25 ms, mostly 11,842 snake-case regex substitutions). The command now resolves the project once, for `--json` and for every poll of `--watch` (before, `--watch` paid it on every poll). Pinned by `TestPerCallCost` in `tests/unit/daemon/test_cli_session_state.py`.

The remaining ~25 ms is that one config validation, shared by every `hooks-daemon` command; it is under the 100 ms target and is not changed here.

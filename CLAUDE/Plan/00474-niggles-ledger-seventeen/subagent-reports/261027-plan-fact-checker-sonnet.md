# Fact check: N541 entry in NIGGLES.md

| #   | Claim                                                                                                 | Verdict  | Evidence                                                                                                                                                                                                                      |
| --- | ----------------------------------------------------------------------------------------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `spawn_detached` now uses `subprocess.Popen(start_new_session=True)`                                  | VERIFIED | `src/claude_code_hooks_daemon/install/relay_repair.py:169-175`                                                                                                                                                                |
| 2   | A regression test makes `posix_spawn` reject `setsid`                                                 | VERIFIED | `tests/unit/install/test_relay_repair.py:448-467`: `no_setsid` raises NotImplementedError when `setsid` is passed, patched over `os.posix_spawn`. The test asserts the child is a session leader. The test suite was not run. |
| 3   | The release note exists                                                                               | VERIFIED | `ls` shows `CLAUDE/UPGRADES/UNRELEASED/release-notes/005-relay-repair-on-uv-managed-python.md` (untracked, as the task said). Its content was not read.                                                                       |
| 4   | The session-start relay check calls `start_relay_repair`, which catches only OSError around the spawn | VERIFIED | `handlers/session_start/relay_binary_checker.py:141` calls it. `relay_repair.py:230-236` wraps `spawn_fn` in `except OSError` only. This is why the old NotImplementedError escaped.                                          |

No REFUTED claims.

Not checked: the ledger's statements about the uv 3.12.16/3.13.18 builds and the Debian 3.11 venv are external and UNVERIFIABLE-HERE.

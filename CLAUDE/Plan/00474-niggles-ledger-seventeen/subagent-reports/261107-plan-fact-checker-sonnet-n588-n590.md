# Fact check: NIGGLES.md N588, N589, N590 (Plan 00474)

Scope note: the diff touches only NIGGLES.md (N588-N590 added, plus an N58x status flip to fixed). It has no PLAN.md hunk.

## REFUTED

None.

## Table

| #   | Claim                                                                                                               | Verdict           | Evidence                                                                                                                                                          |
| --- | ------------------------------------------------------------------------------------------------------------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | N590: `bin/hooks-daemon --version` prints the usage text and refuses the flag                                       | VERIFIED          | Ran it: rc=2, usage text, "error: unrecognized arguments: --version"                                                                                              |
| 2   | N590: no top-level `--version` exists (so an argparse action is to be added)                                        | VERIFIED          | The only `--version` in cli.py is line 13200, on the `release-notes` subparser; `build_parser` is at cli.py:11373                                                 |
| 3   | N589: `restart` prints "restart does not build a venv; it reuses this one"                                          | VERIFIED          | paths.py:3154-3155 (`venv_lock_drift_lines`), called from cli.py:2850 via `_warn_if_venv_not_built_for_source`, called at cli.py:2834 inside `cmd_restart` (2796) |
| 4   | N589: the message names repair and does not repair                                                                  | VERIFIED          | cli.py:2850 passes `daemon_cli_command("repair")`; the function only prints to stderr                                                                             |
| 5   | N589: `lock_hash` is compared with `pyproject.toml` plus `uv.lock`                                                  | VERIFIED          | paths.py:3142-3147; metadata.py hash inputs, lines 150-172                                                                                                        |
| 6   | N589: SessionStart reports "DAEMON VENV NOT BUILT FOR THIS SOURCE"                                                  | VERIFIED          | The text is at paths.py:3153; `unproven_venv_advisor.py:85` is a SessionStart handler that emits it                                                               |
| 7   | N589: issues #148 and #168 exist with the described titles                                                          | UNVERIFIABLE-HERE | The issues are on GitHub; `gh issue view 148 168` settles it                                                                                                      |
| 8   | N589: every other seat shares the checkout and must run restart, then repair, then restart                          | UNVERIFIABLE-HERE | A desktop-team report, not checkable from the tree                                                                                                                |
| 9   | N588: `scripts/upgrade.sh:975-983` fills `modified_files` from `git status --porcelain` over the whole project tree | VERIFIED          | upgrade.sh:975-983 runs `cd "$PROJECT_ROOT" && git status --porcelain \| awk '{print $NF}'`; line 1347 emits it                                                   |
| 10  | N588: the comment says the project agent filters by daemon-owned prefixes                                           | VERIFIED          | upgrade.sh:976-977                                                                                                                                                |
| 11  | N588: 33 unrelated files plus 4 upgrade files were all listed (37), and commit e9607df9c                            | UNVERIFIABLE-HERE | The evidence is in the client repository (fedora-desktop)                                                                                                         |
| 12  | N588: the client's bash-limits gate exempts files listed in `modified_files`                                        | UNVERIFIABLE-HERE | The gate is in the client repository                                                                                                                              |

Minor note on claim 9: `awk '{print $NF}'` takes the last field, so a rename line records only the destination path. This does not contradict the entry.

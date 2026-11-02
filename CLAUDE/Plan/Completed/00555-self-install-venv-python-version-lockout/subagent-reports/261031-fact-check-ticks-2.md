# Fact check: Plan 00555 ticks (round 2)

Scope: claims added by the diff at untracked/plan-fact-check/00555-self-install-venv-python-version-lockout.diff.
Note: the diff itself only changes Tasks 2.4 and 3.1. Task 3.3 and the release-note success criterion are not in the diff; they were checked from PLAN.md lines 112-124 as asked.

## REFUTED

None.

## Table

| #   | Claim                                                                                              | Verdict           | Evidence                                                                                                                                                                                                               |
| --- | -------------------------------------------------------------------------------------------------- | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `paths.py diagnose-venv` exists                                                                    | VERIFIED          | src/claude_code_hooks_daemon/daemon/paths.py:3576 `diagnose_venv_start`, :3624 `_cli_diagnose_venv`, :3727 subcommand "diagnose-venv"                                                                                  |
| 2   | it is stdlib-only                                                                                  | VERIFIED          | paths.py imports (lines 11-30) are all standard library                                                                                                                                                                |
| 3   | wired into `init.sh` `validate_venv`                                                               | VERIFIED          | init.sh:1675 validate_venv calls `_venv_start_diagnosis` (1691, 1707, 1715, 1723); :1759 runs `paths.py diagnose-venv`                                                                                                 |
| 4   | wired into the `start_daemon` timeout path                                                         | VERIFIED          | init.sh:2174 "Daemon startup timeout", then :2180 `_venv_start_diagnosis ... >&2`                                                                                                                                      |
| 5   | report subagent-reports/261031-task-2.4-start-diagnosis.md exists                                  | VERIFIED          | file present and tracked                                                                                                                                                                                               |
| 6   | Task 2.4 output covers interpreter version, venv version_info, sys.path site-packages, fix command | UNVERIFIABLE-HERE | Only the function exists in view; I did not read the body at paths.py:3576-3620 or run it. Tests exist: tests/unit/daemon/test_paths_diagnose_venv_start.py, tests/integration/test_init_sh_validate_venv_diagnosis.py |
| 7   | the orphan `venv-workspace-py311-2a519198` "had already been reaped"                               | VERIFIED          | `ls untracked/venv*` shows only venv-workspace-py313-0d6d49c6; no 2a519198 directory                                                                                                                                   |
| 8   | live daemon venv is `venv-workspace-py313-0d6d49c6`                                                | VERIFIED          | same listing                                                                                                                                                                                                           |
| 9   | `create_venv_at_path` adds `--extra dev` for a self-install only                                   | VERIFIED          | scripts/install/venv.sh:1340 function; :1445-1449 adds `--extra dev` unless dir is `.claude/hooks-daemon`; used in the three `uv sync` calls at :1472, :1480, :1498                                                    |
| 10  | `_repair_venv_locked` adds `--extra dev` for a self-install only                                   | VERIFIED          | src/claude_code_hooks_daemon/daemon/cli.py:2893 and :2908 `[uv, "sync"] if is_client_daemon_dir(daemon_dir) else [uv, "sync", "--extra", "dev"]`                                                                       |
| 11  | an existing venv gains extras only at next rebuild or `repair`                                     | VERIFIED          | the only `--extra dev` sites are the build and repair paths above; nothing else syncs                                                                                                                                  |
| 12  | report subagent-reports/261031-task-3.1-dev-extras.md exists                                       | VERIFIED          | present and tracked                                                                                                                                                                                                    |
| 13  | Task 3.3: note exists at CLAUDE/UPGRADES/UNRELEASED/release-notes/010-venv-python-version-drift.md | VERIFIED          | file listed in the directory and tracked by git (10 lines)                                                                                                                                                             |
| 14  | Success criterion: a release note is recorded in CLAUDE/UPGRADES/UNRELEASED/                       | VERIFIED          | same file                                                                                                                                                                                                              |

## Observations

- The Task 3.1 text says the orphan was pruned; the actual state is that it is absent. The plan's wording "had already been reaped" is accurate.
- The release note's contents (10 lines) were not read for accuracy against Tasks 2.4 or 3.1.
- Searches excluded tests/fixtures/cyber-flag.

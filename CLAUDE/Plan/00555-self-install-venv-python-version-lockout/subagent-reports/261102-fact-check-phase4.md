# Fact check: Plan 00555 Phase 4 diff

Scope: the claims the Phase 4 diff adds or changes.

Result: 12 claims, 8 verified, 2 refuted, 2 unverifiable.

## REFUTED (most consequential first)

- **C9**: "`untracked/hook-errors.log`: nothing writes the file". This is false.
  `log_error_to_file` in `src/claude_code_hooks_daemon/core/front_controller.py:228-290`
  appends to `untracked/hook-errors.log` (`:256`, `:279`). It is called on a handler
  crash at `:148` and `:197`. The file is absent on disk now, but only because no
  hook has crashed. It is not unwritten. The "latent" reasoning is wrong: the log
  is a live risk, and it may hold hook input. Task 4.3 should say "written only
  when a hook crashes".
- **C8**: "the self-install daemon-down read rule also denies `untracked/hook-errors.log`".
  The wording implies the rule does so today. `_is_protected` (`init.sh:463-499`)
  denies only `untracked/events*`, `payload-capture`, `stop-events*`, `logs/hooks/*`,
  the snapshot globs, `.claude/` under lockdown, and so on. `hook-errors.log` is not
  in that list. Reword it as a gap to close, not a current behaviour.

## Table

| #   | Claim                                                                                                                                                             | Verdict           | Evidence                                                                                                                                                                                                                                      |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | The daemon's output goes to `/dev/null` at `cli.py:939-948`                                                                                                       | VERIFIED          | `cli.py:939-948` dup2s devnull onto stdout and stderr                                                                                                                                                                                         |
| 2   | "The daemon writes no log file to disk"                                                                                                                           | UNVERIFIABLE-HERE | The comment at `cli.py:943-944` says the logs are in memory (`MemoryLogHandler`). I did not search every writer. `hook-errors.log` (C9) is a daemon-side file log of hook errors, so the claim is true only for the daemon's own process log. |
| 3   | "The same directory also holds payload captures and the hook-verdict log"                                                                                         | VERIFIED          | `utils/private_io.py:4-6` names `payload-capture/`, the verdict log and the stop-event log. `init.sh:488-494` protects them.                                                                                                                  |
| 4   | "A failed build is already fail-open, so the build log is readable when it matters"                                                                               | UNVERIFIABLE-HERE | `init.sh:1087`, `:3892` and the `hooks-daemon` template (`_print_last_build`) print the build log path. I did not trace fail-open for the whole failure path.                                                                                 |
| 5   | `.daemon-down-stops.log` is written (stand-in ruling 1 intended it to be reported)                                                                                | VERIFIED          | Written at `init.sh:794`. The stand-in ruling `261031-stand-in-ruling-fable.md:221` describes the log and `:262` its trace use.                                                                                                               |
| 6   | "Nothing reads" `.daemon-down-stops.log`                                                                                                                          | VERIFIED          | `git grep` finds it only in `init.sh` (writer and prune at `:665`, `:794`, `:810`) and in tests. Nothing in `src/` references it.                                                                                                             |
| 7   | `diagnose` does not yet print the venv build log tail                                                                                                             | VERIFIED          | `diagnose_venv_start` (`daemon/paths.py:3526-3574`) prints the version, cfg, sys.path, importable and fix lines. It prints no build log.                                                                                                      |
| 8   | Daemon-down read rule denies `hook-errors.log`                                                                                                                    | REFUTED           | See above.                                                                                                                                                                                                                                    |
| 9   | Nothing writes `hook-errors.log`                                                                                                                                  | REFUTED           | See above.                                                                                                                                                                                                                                    |
| 10  | CI builds a fresh venv in every job                                                                                                                               | VERIFIED (mostly) | `.github/workflows/qa.yml:133` and `:333` run `uv sync --frozen ... --python`. I read no cache step in the lines inspected, but did not confirm all jobs.                                                                                     |
| 11  | DBF-REPORT decisions 1-3 are as paraphrased (partial defence; wider rule unbuilt; calibrations `tests/` exclusion, workflow YAML uncovered, "cannot tell passes") | VERIFIED          | `DBF-REPORT.md:286-305`. Item 2 says Plan 00100's shell coverage stays out; "Plan 00100 lands" matches `Plan/README.md:204` (Dormant).                                                                                                        |
| 12  | "Most instances are in shell, which CodeQL cannot read"; "the only escape so far ran no interpreter"                                                              | UNVERIFIABLE-HERE | `DBF-REPORT.md:300-303` supports "Shell would still be uncovered". The "ran no interpreter" escape and "most instances in shell" need the independent-search report, which I did not read.                                                    |

Also checked: the cited sub-agent report `subagent-reports/261102-phase4-winners.md` exists.

Tally: VERIFIED 8 (C1, C3, C5, C6, C7, C10, C11, plus the report-exists check), REFUTED 2 (C8, C9), UNVERIFIABLE 2 (C2/C4 and C12 grouped as 2 for the main report; rows 2, 4, 12 are listed separately above). The reply counts three UNVERIFIABLE rows.

# Fact-check: Plan 00555 Task 2.3 tick

Diff: /workspace/untracked/plan-fact-check/00555-self-install-venv-python-version-lockout.diff

REFUTED claims: none.

| #   | Claim                                                                                                    | Verdict  | Evidence                                                                                                                                                                                                                                       |
| --- | -------------------------------------------------------------------------------------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | "A drifted venv does not resolve, so `repair` takes the venv-free path."                                 | VERIFIED | bin/hooks-daemon:193-221 `_run_venv_free_verb` has a `repair` arm that runs when no venv resolves. Line 331 and the resolver (`resolve_venv_python`, line 319) vet that the venv's Python version matches, so a drifted venv fails to resolve. |
| 2   | "A venv that resolves but cannot import the package is caught by a bounded import probe in the wrapper." | VERIFIED | bin/hooks-daemon:150-163 `_package_importable` runs `import claude_code_hooks_daemon.daemon.cli` bounded by `timeout $IMPORT_PROBE_TIMEOUT` (default 20 s); line 341 applies it for `repair` only and sets `_VENV_FREE_REBUILD=1`.             |
| 3   | "...rebuilt with `venv_bootstrap.sh repair --rebuild`."                                                  | VERIFIED | bin/hooks-daemon:216 passes `--rebuild`. scripts/venv_bootstrap.sh:48-51 documents it, :672-677 `_vb_repair` sets `_VENV_FORCE_REBUILD=1`, :718-719 accepts the 3-arg form.                                                                    |
| 4   | Report link `subagent-reports/261031-task-2.3-repair-without-venv.md`                                    | VERIFIED | File exists in the plan's subagent-reports/ folder.                                                                                                                                                                                            |

Not run: tests (read-only check). Behaviour was judged from the source only.

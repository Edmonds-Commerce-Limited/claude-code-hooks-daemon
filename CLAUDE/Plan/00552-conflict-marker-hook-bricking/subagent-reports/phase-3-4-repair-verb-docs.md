# Plan 00552 Phases 3 and 4 report

Branch: agent-a1cac6280768f71ad-70a20d11. Commits: 22dbb5b91 (Task 3.1), 162e574b7 (Task 3.2), plus the Task 4.1 docs commit on the branch tip.

## Done

- Task 3.1: new verb `repair-install` (decision: a new verb rather than extending `repair`, which is a uv/venv repair with a build lock and a daemon stop; see the journal decision entry). Logic in `src/claude_code_hooks_daemon/install/repair_install.py`; `cmd_repair_install` and the argparse entry in `daemon/cli.py`. Redeploys stubs and init.sh through `generate_forwarder_content`, runs `bash -n` on every hook and init.sh (OK or BROKEN), parses settings.json, never overwrites a conflict-marked settings.json, runs `reconcile-settings` only with `--reconcile-settings`, `--check` writes nothing, exits 1 while anything is broken (and in `--check` when a file would change). Self-install is checked, not rewritten. Tests: `tests/unit/install/test_repair_install.py` (24 cases, real bash), red on import then green.
- Task 3.2: `INIT_REPAIR_HINT` now reads "run .claude/hooks-daemon/bin/hooks-daemon repair-install from the project root" (built from `REPAIR_INSTALL_VERB`; no quote, dollar, backtick or backslash because it sits in a double-quoted bash string). The 31 tracked stubs were regenerated with the generator CLI against root /workspace; the diff is one line per stub.
- Status line: NOT FOUND in the daemon. Nothing in src, scripts or init.sh emits "settings.json is not valid JSON"; the only status-line settings code reads the user's global settings and stays silent on a bad file. The text is most likely Claude Code's own. Recorded as a journal decision; no new segment invented.
- Task 4.1: TROUBLESHOOTING recovery section (symptoms, terminal steps, rebase ours/theirs inversion, verb, `bash -n`, finishing the operation, `claude --resume`, why exit 2 blocks, what `.gitattributes` prevents) and a CLI table row. Release note 003 updated. No generated CLI docs or verb drift tests list verbs.

## Notes

- `repair-install` runs through bin/hooks-daemon, so it needs the venv; the docs say to run `repair` first if the venv is missing.
- Success Criteria in PLAN.md are all met by the work; the status flip is left to the coordinator.

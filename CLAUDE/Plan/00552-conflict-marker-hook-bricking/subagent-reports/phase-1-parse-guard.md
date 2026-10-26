# Plan 00552 Phase 1 report and Phase 2 handoff

Branch: agent-a05365d4280c46da8-a2c42363. Commits: 07e3e5c10 (Task 1.1 tests), 5d3826d9f (Task 1.2).

## Done

- Tasks 1.1 and 1.2 complete and ticked in PLAN.md; journal action entry written.
- The stub templates live in `install.py` (four shapes) and `forwarder_generator.generate_forwarder_content` rewrites every deployed stub, so the guard is a generator transform, `apply_init_parse_guard` / `build_init_parse_guard_block`. The relay hot path is inserted above the guard header. Tracked `.claude/hooks/*` were regenerated with the roots they record.
- Per-event answers: JSON events `{"systemMessage": ...}` exit 0; status line display line exit 0; worktree-create stderr only, exit 1 (catalogue daemon_down_exit_code).
- Tests: `tests/unit/install/test_forwarder_init_parse_guard.py` (135 cases, real bash). Nine older tests that assumed a disabled-transport generation is byte-identical to its source were updated to expect the guarded form.
- Targeted run: tests/unit/install plus test_dogfooding_hook_scripts pass, except `test_bin_wrapper_project_anchoring.py::test_a_global_anchor_selects_the_tree_the_command_reads`, which reads the CLI tree from a worktree and is unrelated to this change.
- ruff, black and mypy clean on touched files; shellcheck shows only the existing SC2034 and SC1091 notes.
- Latency (200 runs, 3799-line init.sh): `bash -n` 10.4 ms against a 2.8 ms bash spawn floor, about 7.6 ms of parsing plus 1-2 ms substitution fork. Only hooks that miss the relay pay it.

## Left (Phase 2)

- Task 2.1: write or merge a managed `.gitattributes` block (begin/end marker lines that do not resemble conflict markers, `-merge` for `.claude/hooks/**` and `.claude/init.sh`) from the installer and upgrade path; tests for create, idempotent re-install, user lines preserved. Decision to record: settings.json NOT covered (merged file with project-owned entries; `-merge` would drop a side of a real edit; reconcile-settings repairs the daemon entries).
- Task 2.2: integration test with a real temporary git repo, two branches change a stub, merge conflicts, file on disk has no markers and passes `bash -n` (needs the `.gitattributes` block present).
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/003-conflict-marker-hook-bricking.md` is written but UNTRACKED in the worktree; commit it with Task 2.1 and adjust its wording to what is actually built.
- Journal a decision entry for the settings.json choice (`CLAUDE/Plan/mkplan.bash --journal 00552 decision <body-file>`, body file under untracked/scratch/).

## Environment notes

- No python on PATH: use `/workspace/untracked/venv-workspace-py311-2a519198/bin/python`, which imports `/workspace/src`; add `-o pythonpath="src ."` to pytest so the worktree source is used.
- The hooks block `sed`, `| head`/`| tail`, `PYTHONPATH=` prefixes and compound subshell loops; redirect output to untracked/scratch/ and read it, and put loops in a small script.

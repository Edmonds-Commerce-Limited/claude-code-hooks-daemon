# Plan 00521 report: tdd_enforcement Write over an existing file (#114)

## RED (before the change)

New class `TestWriteOverExistingFileIsNotCreation` in `tests/unit/handlers/test_tdd_enforcement.py`: 3 failed, 5 passed.

- `test_overwriting_an_existing_regular_file_is_outside_the_gate`: `assert True is False`
- `test_guidance_says_write_that_creates_a_file`: `'does not exist yet'` not in the guidance
- `test_rule_summary_names_a_write_that_creates`: `'does not exist yet'` not in `'creating a production source file without its test file'`

The creation, symlink, dangling-symlink, directory and unreadable-stat cases passed already (they pin unchanged behaviour).

## GREEN

- `tdd_enforcement.py`: module helper `_is_existing_regular_file()` (symlink check first via `is_symlink()`, then `path_is_file(..., unreadable_means=False)`; an OSError from the symlink probe means "not existing", so the gate still applies). Called in `matches()` right after the strategy lookup, so unknown extensions never pay the stat.
- Rule `blocked=` and `get_claude_md()` now say a `Write` that creates a path that does not exist yet, and that an overwrite is treated like an `Edit`.
- Whole `test_tdd_enforcement.py`: 221 passed.
- No acceptance test assumed overwrite-denial (strategies contain no such assumption), so none changed.
- Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/058-...md`.
- Plan tasks and success criteria ticked; Status stays In Progress.

## Disagreement with the brief / plan text

The brief and Task 1.2 said to resolve a relative `file_path` the way the handler already does, and the plan said "relative to the payload's working directory". The handler never reads the payload cwd: it judges `file_path` as given, with `Path.cwd()` only inside some test-path fallbacks. I followed the brief's "do not invent a new rule" and judge the path as given; the Task 1.2 wording was corrected. Real Write paths are absolute (R-ABSOLUTE-PATH-REQUIRED), so this does not matter in practice.

The deployed `CLAUDE.md` guidance block is auto-generated on daemon restart and was not hand-edited.

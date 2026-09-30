# N269 defensive checklist for the quoted-glob step (sonnet-5-5)

Branch `worktree-n269-quoted-glob`. Every shape was run through `SecretFileGuardHandler` in a
`HandlerChain` at process cwd `/`, with the protected file present under `tmp_path` and the payload
`cwd` set to it. The "before" column is the branch's base `b39b8f8fc` (main after step 1, without
this branch), run in a temporary worktree with the same probe.

Result: the guard DENIES all 36 shapes on the branch and on the base. No regression, nothing
pre-existing to file as a new ledger candidate.

Before this task the branch tests covered only `cat '<p>'`, `grep x "<p>"`, the unquoted-glob
cases, `bash <<'EOF'` with a glob body, and the `find -name` / `rg -g` / `grep --include` values.
Everything else below was added as `TestEveryFileReadingShapeIsStillDenied` in
`tests/unit/utils/test_quoted_text_not_enumerated.py` (one parametrised test per shape).

| #   | Shape                                                                                      | Test                                     | Branch | Base |
| --- | ------------------------------------------------------------------------------------------ | ---------------------------------------- | ------ | ---- |
| 1   | `grep -f P`, `--file=P`, `--file P`                                                        | added                                    | DENY   | DENY |
| 2   | `rg --pre cat x P`; `rg --pre cat --pre-glob '*.txt' x P`                                  | added                                    | DENY   | DENY |
| 3   | `rg --ignore-file P x .`                                                                   | added                                    | DENY   | DENY |
| 4   | `grep -e "pat" P`, `grep -- "pat" P`, `grep "pat" P`                                       | added                                    | DENY   | DENY |
| 5   | `cat 'PREFIX'*`, `cat "PREFIX"*`, `grep x 'PREFIX'*`, `echo 'PREFIX'*`                     | added                                    | DENY   | DENY |
| 6   | `cat $'P'`, `cat $'\x..'` hex-escaped, `grep x $'P'`                                       | added                                    | DENY   | DENY |
| 7   | `cat <<< P`, `grep x <<< "$(cat P)"`                                                       | added                                    | DENY   | DENY |
| 8   | `env grep`, `command cat`, `timeout 5 cat`, `nice cat`, `/usr/bin/grep`, `/bin/cat`        | added                                    | DENY   | DENY |
| 9   | `echo PREFIX* \| xargs cat`; `find . -name 'PREFIX*' -exec cat {} +`                       | added (find-name option already covered) | DENY   | DENY |
| 10  | `awk -f P`; awk `while ((getline line < "P") > 0)`; `awk '{print}' P`                      | added                                    | DENY   | DENY |
| 11  | `gh issue comment 1 --body-file P`, and `-F P`                                             | added                                    | DENY   | DENY |
| 12  | `bash`/`sh`/`python3` `<<'EOF'` body that reads P (and a python3 body globbing the prefix) | added (bash glob body already covered)   | DENY   | DENY |

Notes:

- PREFIX is the protected name minus its last two characters, so it globs to the protected name.
- Item 5 is the closest to the new relaxation (a quoted word that is a prefix, plus an unquoted
  glob tail). The word is not a pure quoted operand, so the relaxation does not apply; it is denied.
- Item 10's getline program is left judged because it contains `getline`, and the literal matcher
  also sees the quoted protected name. A getline that reads a quoted glob (`getline < "PREFIX*"`)
  is not expanded by awk either, so it is not a reading shape.
- These tests are a net for the relaxation: they pass on the base too, so they would not have been
  red before the branch, only red if a later change opens one of these shapes.

## Verification

- `PYTHONPATH=src pytest tests/unit/utils/test_quoted_text_not_enumerated.py`: 75 passed.
- The worktree's venv editable install points at `/workspace/src`, so the tests and probe were run
  with `PYTHONPATH=src` to load this branch's code.
- Release note renamed from `184-...` to `187-...` (184 is taken on main).
- Targeted QA (`llm_qa.py changed --base main --allow-unmapped`), first run: 27/28 passed,
  `changed_tests` 3361 passed / 0 failed / 0 skipped. The one failure was `format` (1 file), on a run
  the tool itself marked "working tree changed during the run" (the post-write formatter touched the
  test file mid-run). `black` on the test file afterwards reports it unchanged. The run is NOT
  recorded for this tree.
- A second, still-tree run queued behind another agent's QA (held by the `p477-provision` worktree)
  for more than 2600 s of the 3600 s wait and was killed by my own `timeout` wrapper before it got the
  lock. So no still-tree QA result exists for this commit; the coordinator's full gate must cover it.
  `shell_segmentation.py` remains unmapped, as in the implementer's report.

# Batch C report: N370, N363, N42

Branch `agent-a212b0493fe461dab-aedeff9c`. Probed with `matches()` on main before any change.

## N370 (sed guard, `git -C <dir> commit -m '... sed ...'`)

Reproduced: `git -C /w commit -m 'use sed -i'` and the `-c k=v` spelling matched (denied). Fix: `_GIT_COMMIT` in
`sed_blocker.py` is now `GIT_INVOCATION + "commit\b"`, the shared pattern in `utils/command_evasion.py`. The
same-command rule is unchanged, so `git -C w commit -m x && sed -i ...` stays denied. Guidance text updated in the
handler and in `docs/guides/HANDLER_REFERENCE.md`; the generated CLAUDE.md block catches up at the next daemon restart.
Tests: `tests/unit/handlers/test_sed_blocker_git_global_options.py`.

## N363 (pipe inside `bash -c '...'` blamed on `bash`)

Reproduced for single quotes (`bash -c`, `bash -lc`, `sh -c`); the double-quoted form already passed. Fix:
`_substitution_content_start` in `pipe_blocker.py` opens a frame for a single-quoted program after a shell `-c` flag
cluster, closed by the next single quote. Frames now carry their opener (`$(`, backtick, `'`) instead of a bool.
A pipe after the closing quote is still judged on the wrapper, so a cheap body cannot launder it. Guidance updated.
Tests: `tests/unit/handlers/pre_tool_use/test_pipe_blocker_shell_dash_c.py`.

## N42 (quoted-heredoc blanking hides executed text)

Fixed by earlier work. Nine shapes, each run in real bash (the line after the fake body runs) and judged through the
real chain by `destructive_git`, `pipe_blocker` and `curl_pipe_shell`: all deny. Real quoted bodies stay allowed.
Tests: `tests/unit/handlers/pre_tool_use/test_heredoc_blanking_n42_shapes.py` (42 cases). Three `COVERED` rows added
to `scripts/qa/dangerous-invocation-corpus.yaml`. No source change.

## Write-back

N370 and N363 statuses and an N42 bullet are in `CLAUDE/Plan/00474-niggles-ledger-seventeen/NIGGLES.md`
(N42 lives in archived ledger 00466, so its outcome is in the write-back section there).

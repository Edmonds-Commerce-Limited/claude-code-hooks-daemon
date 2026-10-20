# Plan 00540 / issue #126 code review (Opus)

Branch `worktree-plan-00540`, range `e1f208711..f5ba6fbc4` (2 commits).

## Verdict: CHANGES REQUIRED

The core fix works. The reporter's reproduction now produces
`${CCY_CLAUDE_WRAPPER:-sh <dir>/claude-supervise --arm --}` with an empty left-alone
list. Every interpreter form the plan lists is rewritten and stays idempotent.
mypy, ruff and black are clean on the touched files. Two matcher defects, both
inside review checks (3) and (5), rewrite or flag lines that are not interpreter-prefixed
supervisor invocations.

## Red-before-green evidence (produced by the reviewer)

Method: clone of the worktree, detached at `e1f208711`. The two test files from
`f5ba6fbc4` were copied over the old source with `git show`, then run with the
worktree venv and `PYTHONPATH=src`. The conftest source-tree guard confirmed that the
package was imported from the clone.

- OLD source + NEW tests: **23 failed, 85 passed**. The failures:
  - `test_an_interpreter_prefix_becomes_sh_on_the_launcher`: all 14 params (7 prefixes x {`.py`, already-broken launcher})
  - `test_the_reporters_absolute_path_wrapper_is_rewritten`
  - `test_the_self_locating_line_keeps_its_interpreter_rewrite`
  - `test_a_pinned_interpreter_is_reported_with_a_ccy_python_suggestion`: all 3 params
  - `test_interpreter_prefix_before_the_launcher_warns`: all 4 params
- These new tests pass on the old source. They are guards, not reds, which is expected:
  - comment untouched
  - other-directory left alone
  - plain-not-pinned (4 params)
  - sh-prefixed untouched
  - sh silent in integrity
  - bare-script-with-python3 does not warn about the launcher
- HEAD source + HEAD tests: **108 passed**.

Logs: `untracked/scratch/rev126-old.txt`, `untracked/scratch/rev126-head.txt`. Probe
script: `untracked/scratch/rev126-probe.py`.

## Checklist

1. Interpreter forms: **pass**. Each of these becomes `sh <dir>/claude-supervise`:

   - `python`, `python3`, `python3.12`
   - `/usr/bin/python3`, `/opt/py/bin/python3.11`, `${HOME}/py/bin/python3`
   - `env python3`, `/usr/bin/env python3`

   Quotes, `${…:-…}`, `--arm --`, a double-space gap, a tab gap, a single-quoted
   whole value and the self-locating `$(cd … && pwd)/` path are all preserved.

2. Bare path behaviour is unchanged and comments are untouched: **pass**. A script
   outside the deployed directory is left alone and reported: **pass**.

3. Repair and idempotence: **pass**. Substring and non-python-word safety: **FAIL**
   (M1, M2).

4. The pinned report reaches upgrade stdout through `result.messages`, which
   `upgrade_version.sh` prints as `-> …`, together with an `export CCY_PYTHON=<pin>`
   suggestion: **pass**.

5. Integrity: silent for `sh` and for no prefix: **pass**. Noisy on substring paths:
   **FAIL** (M1).

6. Release note 005 is accurate. It names 3.69.0 and 3.70.0, the repair of both shapes,
   the CCY_PYTHON pin and the new warning, and it matches the sibling note format: **pass**.

7. No suppressions and no changelog comments. Constants are `_SHELL_INTERPRETER` and
   `_CCY_PYTHON_ENV`, and type hints are present: **pass** (one nit below).

## Must fix

**M1. The supervisor file name has no right-hand boundary.** Neither
`_INTERPRETER_BEFORE_SUPERVISOR_RE` (install) nor `_names_deployed_file(…, LAUNCHER)`
checks what follows the name, and `_LAUNCHER_INTERPRETER_RE` only excludes `.py`. As a
result, a working Python helper whose name starts with `claude-supervise` is rewritten
to run under `sh`, and the integrity check warns about it. Observed:

- `python3 .claude/ccy/claude-supervise_helper.py --` becomes `sh .claude/ccy/claude-supervise_helper.py --`
- `python3 .claude/ccy/claude-supervise-wrapper --arm --` becomes `sh …/claude-supervise-wrapper …`
- `python3 .claude/ccy/claude-supervise.sh --` becomes `sh …` (harmless, but not the launcher)
- integrity `wrapper_interpreter_before_launcher` returns `python3` for `…/claude-supervise-wrapper` and `…/claude-supervise_x`

Fix: end the file-name pattern with a token boundary, for example
`(?=[\s"'}]|$)` after `claude-supervise` or `claude-supervise\.py`. Apply it in the
regex and in the line-level gate. Add tests for `-wrapper`, `_helper.py` and `.sh`.

**M2. The interpreter lookbehind lets `-` through, so a non-python word that ends in
`python3` loses its tail.** The lookbehind is `(?<![\w./+$~{}])`, which allows `-`
because `${X:-python3` needs it. Observed:

- `foo-python3 .claude/ccy/claude-supervise --` becomes `foo-sh …`
- `/usr/bin/foo-python3 X.py` becomes `/usr/bin/foo-sh …/claude-supervise`, a binary that does not exist
- integrity reports `python3` for `foo-python3`

Fix: anchor the start to start-of-value, whitespace, a quote, `=` or the `:-` of a
parameter expansion, for example `(?:(?<=^)|(?<=[\s"'=])|(?<=:-))`. Add tests for
`foo-python3` and `/usr/bin/foo-python3`.

## Should fix (the issue class, outside the plan's literal "immediately before")

**S1. A flag or a quote between the interpreter and the path still breaks silently.**

- `python3 -u .claude/ccy/claude-supervise.py --` becomes `python3 -u .claude/ccy/claude-supervise --`, which is SyntaxError at launch
- `python3 '.claude/ccy/claude-supervise.py' --` becomes `python3 '.claude/ccy/claude-supervise' --`

In both cases the line is not reported and integrity returns None. Issue #126 asks for
"left alone and reported" when the line cannot be rewritten to a working form. Either
rewrite through the flags and quotes, or keep `.py`, add the line to `left_alone`, and
widen the integrity check. Recommend fixing this with M1/M2, since the same regex is
being changed.

## Advisory

- **A1.** `PLAIN_INTERPRETER_WORDS` includes `python`, and its comment says "the
  launcher's own default search finds them". It does not: the launcher tries
  `$CCY_PYTHON`, `python3.14`…`python3.11`, then `python3`, never `python`. A
  `python X.py` wrapper therefore drops its interpreter without a CCY_PYTHON hint.
  Either treat `python` as pinned or correct the comment.
- **A2.** The pin note suggests only `pinned[0]` when several lines pin different
  interpreters. It is also emitted only once: the next upgrade sees `sh` and the pin
  hint is gone. That is acceptable, but worth a mention in the release note ("read the
  upgrade output").
- **A3.** The integrity message says "a daemon upgrade repairs the line"
  unconditionally, including for `/usr/bin/python3 /opt/other/claude-supervise`. The
  migration does not touch that line: the launcher is outside the deployed directory
  and the line is not reported either.
- **A4.** `$PY .claude/ccy/claude-supervise.py` becomes `$PY …/claude-supervise`, which
  breaks if `$PY` is Python. This cannot be decided statically. Consider reporting any
  word before the path that is not `sh`, `bash` or `exec`.
- **A5.** The integrity handler hard-codes `sh` in its message text. It could reuse a
  shared constant with install's `_SHELL_INTERPRETER`.

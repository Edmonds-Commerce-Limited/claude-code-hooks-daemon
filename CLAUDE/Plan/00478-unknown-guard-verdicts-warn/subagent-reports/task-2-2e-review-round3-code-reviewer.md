STOPPING BECAUSE: the review is complete. The findings are below.

# Third review: Plan 00478 Task 2.2e (base 6bba54cc7, HEAD 6e065284c)

**Critical 0 · Important 0 · Minor 3.** Verdict: **APPROVE.** All three Minors are non-blocking and should be filed as plan tasks.

## 1. Round-2 findings: all closed (re-run on a fresh 6bba54cc7 checkout and on HEAD)
- **C-1:** `sleep 1 & pytest | tail -5`, `true & pytest | tail`, `mytool & cargo test | head` and `docker ps | tail & pytest | tail` all deny.
- **I-1:** all 20 shapes deny: `bash -euo pipefail -c`, `python -u/-B/-X dev/-W ignore/-I -m`, `-mpytest`, `exec`, `exec -a`, `chronic`, `flock`, `doas`, `taskset`, `unbuffer`, `script -q -c`, `eval`, `bash <<<`, `timeout 5s --`.
- **I-2:** with the repo yaml, all 8 QA-script spellings deny, including `python3 scripts/qa/llm_qa.py all`. `run_all.sh.bak` allows.
- **I-3:** literal-destination awk under a literal glob is back to nomatch (`/tmp/out`, `| "sort"`, `other/keys`, `END{print n > ...}`).
- **I-4:** `$PWD`, `"$PWD"`, `${PWD}`, `$HOME/..` and `~+` operands deny under `protected/**`.
- **M-1:** `cd protected && awk '{print > $1}' ...` and a cwd inside `protected` deny.
- **M-2:** the docs now describe the shipped rule (one gap, Minor-2 below).

## 2. Base→HEAD flips (deny at base, allow at HEAD)
Re-running the round-2 harness gives 19 pipe flips (with config) and 57 wpp flips, all benign:
- The pipe flips are unknown producers with no blacklisted word, such as `docker ps` and `mytool`.
- The wpp flips name no path under the glob in force, or are unreadable text under `**`, which is within the mandate.

The new probes found these flips that hide a blacklisted producer:

**Minor-1 (conf 65): a script written by heredoc and run in the same command escapes the "named anywhere" net.**
- Allows at HEAD: `cat > t.sh <<'EOF'⏎pytest -q tests/⏎EOF⏎bash t.sh 2>&1 | tail -20`, and the same with `tee t.sh <<'EOF' … sh t.sh | tail`.
- `strip_inert_spans` blanks the body because `cat`/`tee` is a data sink, but the same command then executes that file.
- The `echo 'pytest -q' > t.sh && bash t.sh | tail` form still denies, so the two spellings are inconsistent.
- This contradicts "named anywhere in the command" in release note 031, HANDLER_REFERENCE and the yaml comment.
- **Fix** (`pipe_blocker.py` `handle()`, the `_blacklisted_word_anywhere(scan_target)` call around line 1535): also scan quoted-heredoc bodies whose redirect target is later run by a shell, python or `source`. The cheaper option is to scan the unstripped heredoc bodies only on this unknown-tier path. The false-positive cost is small: it needs a heredoc mentioning pytest plus an unknown `| tail` in the same command.

**Minor-2 (conf 70): the legacy `py.test` entry point is on no blacklist.**
- `py.test | tail`, `python -m py.test | tail` and `uv run py.test | tail` were deny at base and allow at HEAD.
- **Fix:** widen the pytest strategy pattern to `^py\.?test\b`, and add a handle()-level deny test.

**Out of scope (hostile respellings, not findings):** `x=py; ${x}test | tail` and `eval py""test | tail` allow. Plain `py""test`, `py\test`, `p'y'test` and `$'py\x74est'` all still deny.

## 3. Shared scanner (`shell_segmentation._quoted_span_end`, `${NAME}`)
- **All-guard differential:** 71 `${x}` commands through every pre_tool_use handler, on base and HEAD. Shapes included `${x}"; rm/reset …"`, `${x}$(git reset --hard)`, `"${x}"git …`, `git reset --hard${x}`, `bash -c "echo ${x}; …"` and `cat ${x} <secret>`. The only diff is one `worktree_file_copy` row, and it is a test-setup artefact: the scratch project is not a recognised checkout. With cwd=/workspace, base and HEAD are identical on 11 copy shapes, and `${x}` now behaves exactly like `$x`.
- **Targeted tests:** 6793 passed over the pipe_blocker, write_protected_paths, destructive_git, secret_file, curl_pipe_shell, worktree_file_copy, sensitive_content, issue_filing, gh_*, root_recursion and utils scanner-consumer tests, run with `PYTHONPATH=src` because the shared venv trips the source-tree guard. The segmentation tests separately: 319 passed.
- **Minor-3 (conf 70):** operator forms still end the word stream, so `awk '{print > FILENAME}' ${PWD:-.}/protected/x` under `protected/**` was deny at base and allows at HEAD. The release note's "an operand built from an expansion counts by its literal part" is untrue for this form. **Fix:** in `_unresolved_operand_naming`, fall back to a text match on the raw operand when the word stream ends at `${`. If that is not wanted, narrow the doc sentence to `$NAME`/`${NAME}`.

## 4. Over-tightening (allowed at base, denied at HEAD)
Exactly 10 rows, all genuine:
- `echo hi & pytest | tail` (pipes pytest), in both configs.
- 8 awk `print > FILENAME` rewrites of the literal-glob file (direct, `./`, `.claude/./`, `other/../`, `*`, two `cd` forms, and cwd inside the directory).

One thing that is not a flip: unknown pipes whose text mentions a blacklisted name as data still deny, as they did at base. Examples are `vim pytest.ini | tail`, `docker logs pytest-runner | tail`, `stat pytest.ini | tail`, `docker ps | tail # pytest` and `docker ps | tail; pytest x.py`. The cause is that `\bpytest\b` matches across `.` and `-`. This is optional cleanup, not a regression.

## 5. Docs
Release note 031, HANDLER_REFERENCE (both paragraphs), the guidance and the yaml comment match the code, except for "anywhere" (Minor-1) and the expansion-operand sentence (Minor-3). The `(\s|$)` explanation is correct.

**Repro:** everything is in `/workspace/untracked/worktrees/worktree-478-2e-contested-rows/untracked/scratch/rr3/`:
- `allguards.py` + `mkcases.py` → `base.json`/`head.json` (all guards)
- `pcases.py` with `pcases.txt`/`pcases2.txt` → `pb*.json`/`ph*.json` (pipe probes)
- `wfc.py`, `cwdp.py` (worktree_file_copy and wpp probes)
- `r3-cmp.txt` (round-2 harness rerun)
- `pytest.out` (test run)

Run each with `PYTHONPATH=<tree>/src /workspace/untracked/venv-workspace-py313-0d6d49c6/bin/python`. The base checkout `untracked/scratch/rr3-base` has been removed with `git worktree remove`.
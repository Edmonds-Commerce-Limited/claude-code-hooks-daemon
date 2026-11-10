STOPPING BECAUSE: the review is complete. The findings are below.

# Re-review: Plan 00478 Task 2.2e (base 6bba54cc7, HEAD 609f24ea0)

**Critical 1 · Important 4 · Minor 2.** The original probes now pass: C1 and C2 deny, and C3 is 27/27. But a new variant of each still gets through. Verdict: **REQUEST CHANGES.**

**Core rule (task 2) holds.** Every base→HEAD flip I found was in the unknown tier at base: pipe_blocker's "unrecognized" reason, or write_protected_paths failing closed on a computed destination or unreadable text. pipe_blocker can't over-tighten, because `matches()` is unchanged. HEAD's deny set sits inside base's, and `_offending_matches` still yields the base first pipe first.

## Critical
**C-1. A background `&` still launders a blacklisted pipe (C1 is not closed).**
- `pipe_blocker.py` `_extract_producer` doesn't split on a single `&`, so the second pipe's producer is read as `sleep 1 & pytest`, which is unknown.
- `sleep 1 & pytest | tail -5`, `true & pytest | tail`, `mytool & cargo test | head` and `docker ps | tail & pytest | tail` all ALLOW at HEAD. The advisory even names `sleep`.
- At base these denied, but only as "unrecognized".
- This contradicts release note 031, HANDLER_REFERENCE and the handler guidance ("every pipe is judged; an unknown pipe never excuses a blocked one").
- `echo hi & pytest | tail` is nomatch on both trees, so this bug existed before the branch. The branch is what turned it into an allow.
- **Fix:** treat a single unquoted `&` as a statement separator in producer extraction, and add the four commands as handle()-level DENY tests.

## Important
**I-1. C2 still has gaps (`_run_targets`, `_shell_c_body`, `_past_runner`).** All of these ALLOW at HEAD:
- **Shell `-c` with clustered options:** `bash -euo pipefail -c 'pytest' | tail`. A common agent spelling; `-o` inside a cluster isn't treated as taking a value, so `-c` is never reached.
- **Python flags before `-m`:** `python -u -m pytest`, `python3 -B -m`, `python3 -X dev -m`, `python -W ignore -m`, `python3 -I -m`, `python -mpytest`.
- **Wrappers not seen through:** `exec`, `exec -a x`, `chronic`, `flock /tmp/l`, `doas`, `taskset -c 0`, `unbuffer`, `script -q -c pytest`, `eval pytest`, `bash <<< 'pytest | tail'`, `timeout 5s -- pytest`.
- `chronic` and `flock` are read through by write_protected_paths but missing from the shared `COMMAND_WRAPPERS` that pipe_blocker uses.
- These now deny: `command`, `command -p`, `stdbuf`, `ionice`, `time`, `nohup env`, `nice -10`, `xargs -0/-r`, `bash -o pipefail -c`, `bash -ec`, `bash -lc`, nested `bash -c "env pytest | tail"`, `$( )`, backticks, `<( )`, `|&`, and heredoc into `bash` / `cat <<'EOF' | bash`.
- **Fix:** parse shell option clusters (any cluster containing `o`/`O` consumes the next word). Skip interpreter flags up to `-m` and accept `-mX`. Add `exec`/`chronic`/`flock`/`doas`/`taskset`/`unbuffer`/`eval` to the shared table, and read a here-string body.

**I-2. `extra_blacklist` doesn't cover the QA scripts "at any path" as `.claude/hooks-daemon.yaml` claims.**
- ALLOW: `bash scripts/qa/run_all.sh | tail`, `bash ./scripts/qa/run_tests.sh | tail -5`, `sh scripts/qa/run_all.sh | tail`, `bash -x …`.
- Cause: `_run_targets` returns early for a shell word with no `-c` and never adds the script as a target.
- `python3 scripts/qa/llm_qa.py all | tail` (the project's main QA wrapper) is on no list.
- **Fix:** add a target for `<shell|python> [flags] <script>` using the script's basename, and decide whether `llm_qa.py` belongs in the config.

**I-3. Over-tightening in write_protected_paths (`write_protected_paths.py:1259-1275`).**
- With a literal glob (`.claude/ccy/ccy.env.local`), these were nomatch at base and DENY at HEAD, though each only reads the protected file:
  - `awk '{print > "/tmp/out"}' P`
  - `awk '{print | "sort"}' P`
  - `awk -F= '{print $1 > "other/keys"}' P`
  - `awk '{n++} END{print n > "/tmp/c"}' P`
- Cause: the C3 operand check runs for any writing program (`_awk_program_writes`), not only a computed destination.
- **Fix:** apply the operand deny only when a redirect target isn't a string literal (FILENAME, `$N`, a variable).

**I-4. C3 still has gaps for expansion-rooted operands.**
- With `protected/**`, these were DENY at base and ALLOW at HEAD: `awk '{print > FILENAME}' $PWD/protected/x`, `"$PWD"/protected/x`, `$HOME/../protected/x`, `~+/protected/x`.
- `$PWD` also allows under `**`.
- Cause: `_operand_naming` gives up on an untrusted operand, and the program-only `_text_naming` never sees the operand text.
- **Fix:** run `_text_naming` (the directory pattern) over untrusted operands as well.

## Minor
**M-1. Computed destination with cwd inside a protected directory.**
- `cd protected && awk '{print > $1}' ../other/list`, and cwd=`protected` with `awk '{print > $1}' list`, were DENY at base and ALLOW at HEAD.
- This is within the unknown-tier mandate, but every relative destination lands inside the listed directory.
- **Fix:** deny when the effective cwd is under a listed directory glob.

**M-2. Docs are partly untrue.**
- Release note 031, `docs/guides/HANDLER_REFERENCE.md:744`, both `get_claude_md` texts and the yaml comment state "every pipe judged" and "any path", which C-1 and I-2 falsify.
- HANDLER_REFERENCE's wpp paragraph says the operand deny is for a computed-destination program, but the code does it for any writing program (I-3).
- Also, `^run_all\.sh\b` matches `run_all.sh.bak` (trivial).

## Positive
- Every-pipe judging, and the unknown verdict leaving the disclosure tracker untouched, are sound.
- Basename reduction and runner peeling work for the listed spellings.
- Absolute-path and `cd`-resolved awk operands deny correctly.

**Repro:** the harness is `untracked/scratch/rr2e/run.py`. It reads `cases.txt` (round 1), `wcases.txt` and the `hd*.txt` heredoc files; `cases-round3.txt` holds the QA-script probes. Results are in `base.out`/`head.out` and `base2.out`/`head2.out` (round 2: the `&` and flag cases). `reason.py` with `rcases.txt` prints the base and HEAD reasons, and `absp.py` covers the absolute and `$PWD` operands.

Run it as `PYTHONPATH=<tree>/src /workspace/untracked/venv-workspace-py313-0d6d49c6/bin/python run.py <tmpdir> [hd*.txt]`; `/workspace/.venv` has no pydantic. The base worktree `untracked/scratch/rr2e-base` has been removed, so re-running against base needs a new detached checkout of 6bba54cc7.
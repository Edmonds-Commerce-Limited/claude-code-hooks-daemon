# Batch I: N409 (subagent_full_qa_blocker script-file false positive)

## Finding

The shell-level mention and real-run shapes in the brief already behaved correctly: this handler has its own
parser, and every mention shape allowed and every real shape denied before any change. The real N409 defect was in the
Python-code judgement. Two rules treated any literal in a process-starting script as a command:
`_pytest_in_code` (a `"pytest"` literal anywhere plus an import of `subprocess`) and `_python_strings` (every one-word
string became a program, every list an argv). So `TOOLS = [..., "pytest"]` and `KNOWN = ["run_all.sh"]` denied, as did
`print("./scripts/qa/llm_qa.py all")` beside any process call.

## Change

`src/claude_code_hooks_daemon/handlers/pre_tool_use/subagent_full_qa_blocker.py`:
`_process_arguments` computes which expressions can reach a call as an argument (or a method receiver), following
names, loop variables, walrus targets, parameter defaults, attributes, dict and subscript values and function returns.
Calls to text sinks (`_TEXT_SINKS`) are not followed unless the script defines a function by that name.
`_python_strings` judges only reached strings and argv lists; `_pytest_in_code` requires the `"pytest"` literal to be
reached (`_passed_literals`). Unparseable Python keeps judging every literal.

## Red/green

Tests first: 10 failed, 75 passed (the 10 were the 5 mention rows on stdin and the same 5 as script files). After the
fix the whole handler test module and corpus module: 1451 passed.

Tests: `TestPythonHoldingAProgramNameIsNotRunningIt` (9 mention rows, 20 full-run rows on stdin and as script files,
the sink-name-defined case, the unparseable case) and `TestMentionsAndRealRunsAtTheShellLevel` (10 mentions, 15 real
runs: `if/then`, `bash -c`, `eval`, `env`, `nohup`, `timeout`, `python3 ./llm_qa.py all`, `uv run`, `cat <<'EOF' | bash`,
`bash <<'EOF'`, subshell, `$(...)`, backticks, `&`). Six `n409-` allow rows added to
`tests/fixtures/ordinary_command_corpus.yaml`.

## Judgement calls

- A python heredoc that calls subprocess on the full-QA command DENIES (it is a real run); a python heredoc that only
  prints or stores the string allows. Quoted-heredoc blanking is not used for interpreters: the handler's own
  heredoc reader decides, so `bash <<'EOF'` and `python3 - <<'PY'` bodies are read as code.
- Not used: `strip_inert_spans` / `command_position_segments` (N405 shape). The handler resolves wrappers itself and
  re-parsing with the shared helpers would duplicate that and risk the deliberate fail-closed paths.
- Acceptance tests: none added. The two existing acceptance probes are in-process payloads that never execute. A
  `bash -n -c` wrapper would make this handler read the command as parse-only and allow it, so it cannot express a
  deny here.
- Review round 1 (`261011-review-batch-i-opus.md`) fixes: `write`/`writelines` removed from the text sinks (they feed a
  shell or a script that is then run); any name the code defines, rebinds or imports under (including `as` aliases) is
  no longer a sink; the redundant `"pytest" in literals` clause is dropped and the parse and reach walk are done once
  per script (`_parsed_reach`, cached). Seven new deny shapes were added to `_PYTHON_FULL_RUNS` (12 red before the fix).
- Residual, pre-existing on main and left unfixed: a list built with `.append(...)` or `+=` and then passed to
  `Popen(...)`, `asyncio.create_subprocess_exec(...)`, and `exec(open('runner.py').read())`. The reviewer's 34-script
  probe misses exactly these 4 on both main and this branch.
- N96 (the open decision on this handler) is unaffected: no structural change.

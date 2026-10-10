# N385 curl_pipe_shell part (Sonnet)

Branch: agent-a220a4cbce194b561-7e5be5a9.

## Change

- `src/claude_code_hooks_daemon/handlers/pre_tool_use/curl_pipe_shell.py`:
  - The pipe-into-interpreter regexes are replaced by a word-level reader. Each pipe stage is resolved, its leading `VAR=value` words and wrappers are peeled with the shared `peel_command_wrappers`, and the head must fully match an interpreter name. This catches `| env python3`, `| sudo -u bob python3` and `| env FOO=1 bash`, and fixes a latent false positive (`| sudo tee .../python.list`).
  - `node` is an interpreter (`| node` and `| node -` deny; `node parse.js` and `node -e` stay allowed).
  - New `_substitution_runs_download`: a `$(...)`, backtick or `<(...)` whose body runs curl or wget is denied when it is the program: the whole argument of a shell's `-c` (or python `-c`, perl/ruby `-e`), of `eval`, or the sole operand of an interpreter or `source` / `.` (process substitution).
- `tests/unit/handlers/pre_tool_use/test_curl_pipe_shell_careless.py`: written first. Red run: all 28 must-deny cases failed on main, the allow cases passed. Now green (with the two existing curl test files, 211+ passed).
- `scripts/qa/dangerous-invocation-corpus.yaml`: five COVERED `remote-code-*` rows and one UNCOVERED-open row. The checker holds all 43 rows.
- NIGGLES.md N385 updated.

## Left open

`curl url -o x.sh && bash x.sh`. `curl -o x.sh U && sha256sum -c sums && bash x.sh` is the careful form this guard's own advice points at, and `bash -n x.sh` does not run the file. `curl -O`, `cd` and variable names lose the file name, so a deny would refuse the careful spelling and still miss the careless one.

Also unseen: a download held in a variable and run later, and a substitution inside a larger `-c` body.

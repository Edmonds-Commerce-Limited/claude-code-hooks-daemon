## 01:00 · correction · 00:44 — N678 ruling: where a program reads its own text, and the evidence to cite

Two corrections to the N678 ruling entry of today. The ruling itself is unchanged.

- `sys.argv` does not hold a `-c` program; it holds only `-c`. The program's text is readable from `/proc/self/cmdline` (the `-c` form) and from `/proc/$PPID/cmdline` (the whole Bash command, heredoc included).
- The evidence to cite is the tracked test class `TestAGivenUpScanOfAPythonProgram` in `tests/unit/handlers/pre_tool_use/test_secret_file_guard_cwd_fail_closed.py`, not the untracked probe file.

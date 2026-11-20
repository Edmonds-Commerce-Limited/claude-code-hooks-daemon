## 00:44 · decision · — — N678 ruling: a given-up scan still denies glob characters in a Python program

Ledger N678 asked whether a scan that gives up should still deny a Python heredoc. Ruling: the deny stays. No exemption is added.

What was measured (deadline forced to -1, `untracked/scratch/n678_probe.py`):

- Braces are not the trigger. `_MAY_GLOB` is `*`, `?` and `[`. A program of dict and set displays alone stays an advisory after a give-up. The test that failed in the full gate holds `# -*- coding: utf-8 -*-`; its `*` is what denied. The ledger's evidence line was wrong on this and is corrected.
- So the real question is `*`, `?` and `[` in program text: `x[0]`, `a * b`, `*args`, a comment. That is most real programs, but only when their scan passes the 5 s deadline.

Why no exemption:

- The completed scan judges a glob spelled in Python code. `print(own/id_rs[a])` is valid Python and a shell glob word; it is denied today, in the heredoc and the `-c` form. An exemption after a give-up would allow what the finished scan denies.
- A program can read its own text back (`sys.argv`, `/proc/$PPID/cmdline` holds the whole Bash command, heredoc included) and hand it to a shell. Plan 00466 N101 round 5 ruled this way for brace words in code; the same holds for glob words.
- No test on the word itself separates code from a glob: `x[0]` is both, and a bare `*` matches every file in the directory. Only matching against the protected-file index answers it, and that is the scan that gave up.
- With an exemption, padding a program until the scan times out would carry a code-spelled glob past the guard. That is the hole review 614c P2 closed.

Cost accepted: a long inline program on a loaded host can be denied though it reads nothing protected. The deny message now says so and names the way out: write the program to a file and run the file.

Change made: one sentence added to `_GAVE_UP_CAUSE`; `TestAGivenUpScanOfAPythonProgram` in `test_secret_file_guard_cwd_fail_closed.py` pins the completed-scan deny, the give-up deny for code, comment and string globs, and the braces-only advisory. No verdict changed, so there is no DENY to ALLOW flip to review.

Left open in N678: the scan's speed. `_search_reach` takes 0.44 s against 0.15 s on main for the 600-line program. Making an ordinary program finish inside the deadline is the right way to cut the false denies.

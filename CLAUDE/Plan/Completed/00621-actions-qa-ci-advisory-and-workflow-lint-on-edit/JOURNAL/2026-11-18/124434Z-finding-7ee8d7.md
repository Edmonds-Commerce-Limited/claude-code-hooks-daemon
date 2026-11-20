## 12:44 · finding · — — Linter output and single-file mode (peer note)

The rollout side reports (a peer note, not verified here) that the linter already offers `check --format json -- <path>` with findings carrying id, path, line, col, severity, message, excepted and exceptionKey, and exit codes 0 clean, 1 findings, 2 fault. It must run from the repository root today; a next release adds `check --file <path>`, which finds the enclosing repository and reads its exceptions and workflow labels. Task 1.1 stays open until that version is published and checked against the real tool.

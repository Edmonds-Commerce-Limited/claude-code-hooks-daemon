## 07:26 · action · —

Task 2.2 item 3 (`branch-reject request`) landed in 1f415b692 (core) and 5e3471e24 (CLI), tests first.

- The request mints ONE request per reviewer required, each with its own nonce and prompt: a dispatch record binds one nonce to one agent, so two reviewers need two nonces.
- The prompt is composed from git facts and the stored keep history only. Decision: any control, format, surrogate, private-use, unassigned or line/paragraph-separator character in the branch, a path, a commit subject or a quoted keep reason refuses the request, and so does a path `ls-tree` had to C-quote (it then carries the quoted form, not the raw byte). Without this a file name holding a newline would put caller-chosen lines into a prompt the daemon claims to have composed alone.
- The prompt has no trailing newline; its sha256 is stored as `prompt_sha256`. The text form prints it between `----- BEGIN PROMPT i of n -----` / `----- END PROMPT i of n -----` lines; `--format json` gives the exact string.
- The CLI classifies through `delete_branches(dry_run=True, reject_route=None)`, so it cannot disagree with `delete-branch` about what is `unproven`. The protected-names tuple is now one helper both commands use.
- The handoff records the hook-order design for the gate and recorder: PreToolUse writes the dispatch record with an empty `agent_id`, only PostToolUse fills it, SubagentStop never does.

Targeted ruff, black, mypy clean; the reject, request and delete-branch CLI tests pass. Remaining in Task 2.2: the reviewer agent, the dispatch gate, the SubagentStop recorder.

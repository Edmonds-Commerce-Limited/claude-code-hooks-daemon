## 09:00 · action · —

Task 2.2 item 5, the core of the SubagentStop verdict recorder (red 2f3b9dde3, green 6adb8fe9e).

A verdict counts only when it comes from a clean, final stop. Most SubagentStop blockers are non-terminal, so the recorder runs even when a stop is blocked. To handle that, the first stop of an identified reviewer takes an exclusive `stops/<nonce>` marker before anything else is checked. A later stop of the same nonce, or a stop with `stop_hook_active` set, withdraws that nonce's verdict and writes nothing. The verdict id is the nonce, and the verdict is created exclusively. A keep record is never withdrawn, because it only restricts.

The recorder identifies a stop as the reviewer's only when all of these hold:

- the payload and meta types are both the reviewer type;
- the sha256 of the first human turn equals the request's `prompt_sha256`;
- the dispatch record's session and `tool_use_id` equal the payload session and meta `toolUseId`;
- the agent id is not bound to another agent.

It never writes the agent id itself.

Checked against live agent transcripts:

- Every record carries `isSidechain: true`, so the main-session human-prompt test does not apply here.
- 40 agents gave exactly 40 non-meta string user records.
- `api-request-blob` records carry an assistant-role message but are not assistant records.
- For 35 of 35 agents, the last assistant text equals the persisted `last_assistant_message`.

The handler will register at priority 13. It cannot go above the terminal size blocker at 15 (`test_stop_chain_terminal_shadowing.py` forbids that), and the marker makes the order irrelevant anyway.

Residue for Task 2.4:

- A transcript not yet flushed at hook time writes nothing. That is the closed direction.
- A reply over the size threshold is always blocked, so its verdict is always withdrawn.
- A reviewer killed after a blocked first stop keeps its first verdict.
- A second stop whose transcript cannot be read cannot withdraw.

The handler, its registration, the docs and the Task 2.2 tick are left for the next agent (see the handoff).

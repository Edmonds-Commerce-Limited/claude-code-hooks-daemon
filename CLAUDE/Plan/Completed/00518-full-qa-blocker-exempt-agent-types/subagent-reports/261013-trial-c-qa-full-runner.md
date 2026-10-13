RESULT: BLOCKED

COMMAND: cd /workspace && ./scripts/qa/llm_qa.py all
RUN COUNT: 1 (not retried, no lock waited on)
RULE ID: R-SUBAGENT-FULL-QA

HOOK MESSAGE (verbatim):

PreToolUse:Bash hook error: BLOCKED [R-SUBAGENT-FULL-QA]: a full-suite QA run inside a sub-agent (a declared `full_qa_patterns` command)

WHY BLOCKED:
The full QA suite is the COORDINATOR's gate. It merges every ready branch
into one integration worktree and runs the suite ONCE over all of them.
Several agents each running the whole suite exhaust the host, and the
coordinator's run covers your branch anyway.

DO INSTEAD:
  1. Run targeted QA: the checks and tests that cover what you changed.
  2. Commit, then send the coordinator the commit hash and your targeted
     results.
  3. The coordinator runs the full gate and sends back anything it finds.

Only a command that RUNS the whole suite is denied. Mentioning one in a
commit message, a grep or an echo never is, and the coordinator's own
run is unaffected.

This handler is the fast, friendly FIRST LINE: it parses Bash text,
and no finite pattern list enumerates every way to start a
whole-suite run. A command it could not fully resolve is judged by
`unseen_policy` (default: allowed, with an advisory) -- see that
option's own docs for whether and how this project backstops what
this handler could not see.

A project that runs its full gate through a dedicated agent lists that
agent's type in `exempt_agent_types`; such an agent is allowed, one run
at a time.

MATCHED: `llm-qa-whole-suite` in `./scripts/qa/llm_qa.py all`

RUN INSTEAD:
  - ./scripts/qa/llm_qa.py changed
  - ./scripts/qa/llm_qa.py <tool> [<tool> ...]   (e.g. lint type_check pyright)
  - pytest <explicit test files or directories narrower than tests/unit>

To disable: handlers.pre_tool_use.subagent_full_qa_blocker  (set enabled: false and record why beside it)

NOTES:
The gate did not execute, so there is no VERDICT line.

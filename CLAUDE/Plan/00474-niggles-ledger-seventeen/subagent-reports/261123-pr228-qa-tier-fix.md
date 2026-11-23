# PR 228 QA (docs or code tier) failure

Cause: not the N709 work. Two detectors failed on content merged in from main (Plan 00634):

- magic_values: 4 magic timeouts in tests/unit/utils/test_human_approval.py and test_teamchat_seat.py. Replaced with `Timeout.TEAMCHAT_WHOAMI`.
- plan_qa status-enum-and-date: 00634 PLAN.md status was `🔄 In Progress`, not a recognised token. Now `In Progress`.

The other plan_qa findings are advisory only. Verified locally: ruff and black clean, both test files pass (228 passed). The full llm_qa could not run here: this worktree has no venv.

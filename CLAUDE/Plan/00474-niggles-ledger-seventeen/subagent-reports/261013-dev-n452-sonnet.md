# N452 report: first-write binding from outside the repository (GitHub #105)

## Tests written (RED first)

New class `TestFirstWriteBindsWhenTheCwdGivesNoSameRepositoryCheckout` in `tests/unit/handlers/pre_tool_use/test_subagent_worktree_write_guard.py`:

- `test_the_binding_survives_a_later_cwd_in_a_sibling_worktree[other_repo]` and `[nowhere]`: first write into wt-a from the other cwd allows and binds (binding_count 1); then cwd wt-b with a wt-a target allows; cwd wt-b with a wt-b target denies, naming wt-a and "first write".
- `test_a_first_write_into_the_main_tree_from_elsewhere_binds_nothing`, `test_no_agent_id_binds_nothing_from_elsewhere`, `test_a_target_outside_any_checkout_binds_nothing`: guards on the no-binding cases (these passed before and after).

RED: the two parametrised cases failed (`assert 0 == 1`, binding_count). The other 54 passed.

## Fix

`_crossing` in `src/claude_code_hooks_daemon/handlers/pre_tool_use/subagent_worktree_write_guard.py`: the cwd-outside-checkout and different-repository exits no longer return before the bind. Only a same-repository, linked-cwd crossing returns early (and binds nothing). Otherwise, with an agent_id and a linked target, the agent is bound. CheckoutUndecidableError still propagates and fails open. Module docstring and `_crossing` docstring updated; the resident guidance text was already accurate.

Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/051-subagent-worktree-write-guard-binds-on-a-first-write-from-outside-the-repository.md`.

## QA

Handler tests: 56 passed. `./scripts/qa/llm_qa.py changed`: 40/40 passed (changed_tests 1874 passed, 0 failed). The "NOT RECORDED" notice was only because the tree was uncommitted when it ran.

## Commit

See the final reply for the hash.

## 09:55 · finding · —   — Task 2.7 merge turned main red; fixing forward

Task 2.7 was merged and pushed to main before any targeted QA had run on it. The agent's `llm_qa.py` run had timed out on the host QA lock, and I merged anyway and ran `changed` afterwards. That run is red:

- **75 failing tests.** The worst is `test_provision_sh.py`, with 52. Foreground `repair` now pipes through `tee`, and the test sandboxes deliberately exclude it, so provisioning fails with `tee: command not found`. The agent added `tee` to only one sandbox's tool list. A build path that newly needs a binary is a real robustness defect, not just a test-harness issue.
- **15 pyright errors** in `venv_lock.py:226-235`.
- **1 magic timeout** in a test.
- **1 `shellcheck disable` with no reason**, at `venv.sh:556`.

A qa-fixer agent is fixing forward on a branch, with an instruction not to "fix" the problem by adding `tee` to more sandboxes. The Task 2.1 agent has been told main is red and not to absorb the fix.

Lesson: when an agent reports that its targeted QA did not run, run `changed` on its branch before merging, not after. Every merge this session that waited for its QA result (3.1, 2.4, 2.3) caught or confirmed things before they spread.

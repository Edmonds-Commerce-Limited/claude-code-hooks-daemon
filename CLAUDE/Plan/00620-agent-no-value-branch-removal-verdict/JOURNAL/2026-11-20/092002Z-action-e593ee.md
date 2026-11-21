## 09:20 · action · — — Task 2.2 closed: the verdict recorder handler is registered

Task 2.2 closed: the SubagentStop recorder handler `branch_reject_verdict_recorder` (priority 13, non-terminal, WORKFLOW+NON_TERMINAL, never blocks) wraps core `record_review_stop`. It is registered in both config files, `init_config`, the v3.76.0 manifest and the guidance-coverage exemptions. DESIGN.md section 3 now has the `stops/<nonce>.json` row and the one-verdict-per-nonce rule. HANDLER_REFERENCE.md documents the gate, the binder and the recorder.

Decisions:

- Only a literal `stop_hook_active: false` counts as a first stop. Any other value, or a missing field, is treated as a re-entry and withdraws the verdict. The contract marks the field unconditional, so a missing value is malformed, and the handler fails closed on it.
- The reply comes only from the payload's `last_assistant_message`. Reading it from the transcript would make the core's payload-against-transcript equality check compare the transcript with itself.
- `matches` reads neither the store nor the filesystem, and it also matches a re-entry stop, because the re-entry is what withdraws a verdict.

Residue for the Task 2.4 adversarial pass:

- The reply-equality check runs after the fact, so a transcript not yet flushed at hook time records nothing. That outcome is closed.
- A verdict reply over the size blocker's threshold is always blocked, and so always withdrawn. Do not exempt it.
- A reviewer killed after a blocked first stop keeps its first verdict.
- A re-entry stop whose transcript cannot be resolved or read, or whose handler crashes (OSError/RuntimeError/ValueError are logged), cannot be identified, so it cannot withdraw the earlier verdict.

Test note: run pytest with an absolute `PYTHONPATH=$PWD/src`. A relative `src` makes `test_config_fingerprint.py::test_identical_across_separate_processes` fail, because its subprocesses run with cwd `/` and `/tmp` and import `/workspace/src`.

The expected red is unchanged: `TestGuidanceActuallyReachesClaudeMd` (the gate's section) goes green after the merge plus a daemon restart.

## 08:05 · action · —

Sixth agent, Task 2.2 item 4: `dispatch_declaration.matches` now returns False for a branch-reject reviewer dispatch (the reviewer type, or a prompt that starts with the review marker), in both advisory and strict mode. Strict mode would otherwise deny the daemon-composed prompt, and no handler may rewrite it, because the gate compares it byte for byte. A marker quoted mid-prompt is still matched. Tests: `TestBranchRejectReviewerDispatch`.

Orientation for the gate handler is in the handoff. The gate priority is 59, not 49: no Agent denier sits above 48, and the advisories at 60 never deny. No PreToolUse handler rewrites an Agent `tool_input`. A crash in a SAFETY+BLOCKING handler denies in `chain.py`. Context budget reached, so the gate handler, binder and recorder are left to the next agent.

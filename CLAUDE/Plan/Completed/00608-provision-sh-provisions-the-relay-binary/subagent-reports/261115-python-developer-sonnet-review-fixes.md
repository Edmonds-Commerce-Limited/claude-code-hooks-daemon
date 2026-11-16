# Plan 00608 review fixes (four Minor findings)

1. Forwarder change detection: state is now porcelain plus `git diff HEAD -- .claude/hooks`, so a rewrite of an already-modified forwarder is seen. Test: test_a_forwarder_already_modified_and_rewritten_is_reported (red before, green after).
2. `--check` exits: only exit 2 (argparse, old CLI) provisions; stderr is merged into the answer and never shown for it. Any other non-zero exit reports "The relay check failed ..." with the cause, sets the failed flag, builds nothing. Tests: crashing check, old-CLI usage error hidden (sandbox gained SANDBOX_RELAY_CHECK_STDERR).
3. A helper that fails to source prints "The relay step could not source its helper: <path>". Test added.
4. Background tests now assert the specific report text; the background sync test reads the sync log, since the sync is detached.

Shellcheck: only the pre-existing SC1091 info. Release note 078 still accurate.

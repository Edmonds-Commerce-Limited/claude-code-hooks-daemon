# Callout: the QA audits no longer pass by scanning nothing

**Plan**: 00364
**Audience**: everyone

`audit_error_hiding.py` and `audit_capture_corruption.py` matched their
exclusion patterns (`untracked/`, `venv/`, `node_modules`, …) against each
file's ABSOLUTE path, so a checkout that merely LIVED under a matching
directory excluded itself entirely. A git worktree at
`untracked/worktrees/<branch>/` is exactly that case: the error-hiding audit
collected no files, reported no violations, and marked every live exclusion
stale, while the capture-corruption audit collected no shell files. Both now
judge the path relative to the tree being scanned, and the error-hiding audit
fails with a named workspace when it collected no candidate files at all, so
"no violations" can no longer mean "nothing was looked at".

`scripts/qa/llm_qa.py` no longer hardcodes the retired pre-v3.7.0 venv path,
which the fingerprint-keyed layout stopped creating. It asks
`scripts/lib/resolve_venv.sh`, the same resolver `init.sh` and the installer
use, and falls back to the legacy path only when the resolver is missing
entirely. A fresh worktree no longer needs a hand-made symlink before the QA
suite will start.

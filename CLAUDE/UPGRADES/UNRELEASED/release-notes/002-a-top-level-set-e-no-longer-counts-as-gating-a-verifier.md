# Callout: a top-level `set -e` no longer counts as consuming a verifier's result

**Plan**: 00474
**Audience**: everyone

Under the current Claude Code Bash tool a command runs inside an `&&` list, where bash ignores errexit, so a top-level `set -e` / `set -euo pipefail` does not stop a command after a failing step: `set -euo pipefail; pytest tests/; git commit -m x` committed even when pytest failed. `verification_result_gate` therefore no longer stands down for a top-level `set -e` prelude (including inside `{ }` groups and subshells), and a verifier followed by a mutator under such a prelude is now reported, or denied in `mode: block`. Gate the pair with `&&`, `|| exit 1`, an explicit exit-code check, or run the statements in a fresh `bash -c 'set -euo pipefail; …'` (or a `bash <<'EOF'` script that sets it inside the body), all of which still pass.

`bash_safe_mode` still accepts a declared prelude and denies nothing new (`pipefail` and `-u` still work), but its deny message, fix line and resident guidance now lead with `&&`, `|| exit 1` and the `bash -c` wrapper, and state that a top-level `set -e` does not stop the command under the current Claude Code Bash tool.

# Callout: bash strict mode is now on by default and blocks unguarded sequenced commands

**Plan**: 00270
**Audience**: client projects

The `bash_safe_mode` handler now ships enabled and blocking. A Bash command of two or more `;`- or newline-sequenced statements that declares no `set` safety prelude (errexit and pipefail) is denied, because an early failure would otherwise be silently ignored. There are two remedies: put `set -euo pipefail` at the top of the command, or chain the statements with `&&` only (a pure `&&` chain and a single statement are never flagged). A command that must run every statement whatever fails (a diagnostic sweep, an exit-code observer) declares `MUST_SKIP_SAFE_MODE_BECAUSE="reason"; <command>`. To opt out, set `handlers.pre_tool_use.bash_safe_mode.enabled: false`, or keep it advisory with `options.mode: warn`. Mind one gotcha under `pipefail`: `producer | head` exits 141 (SIGPIPE), which `set -e` treats as a failure, so avoid it rather than appending `|| true`; read the file with `head -n N <file>` directly or capture with `bin/echd-capture N`.

# Callout: opening the compact summary no longer defers the post-compact resume

**Plan**: 00474
**Audience**: everyone

The ccy supervisor tracks the human's input box from the keystrokes it forwards, and every injection (including the resume after a compact) waits until the box is empty. `HumanInputLine` counted every control byte it did not recognise as typed content, so one Ctrl+O (Claude Code prints "ctrl+o to see full summary" right after a compact) left the box looking non-empty until the human pressed Enter, Ctrl-U or Ctrl-C, and the resume was deferred meanwhile. Ctrl+O and Ctrl+T (the transcript/summary and todo-list view toggles) are now consumed as no-ops: they neither mark the box non-empty nor change its content, and they do not start the abandoned-box clock. Ctrl+V and Ctrl+R stay counted as content because they can fill the box, and any other unrecognised control byte keeps the conservative rule.

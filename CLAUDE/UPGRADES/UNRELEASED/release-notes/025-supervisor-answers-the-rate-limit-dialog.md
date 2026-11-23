# Callout: ccy supervisor answers Claude Code's rate-limit dialog and resumes after the reset

**Plan**: 00523
**Audience**: client projects

When a session hits a usage limit, the ccy supervisor now picks `Stop and wait for limit to reset` on Claude Code's menu. After the reset it clears the pre-filled `continue` and sends one `continue` of its own, at most once per reset window. Nothing else is typed into the box while that `continue` is pending. Any key the human presses while the dialog is up, even before the supervisor first sees it, leaves that window to the human, and the host re-checks for pending input before it sends a key. An unrecognised look-alike screen is logged only as a hash and row count, and a reset time in the past or more than 8 days ahead is treated as unknown (no `continue` is sent). It is on by default, `CCY_RATE_LIMIT_DIALOG=off` in `ccy.env` disables it, and it needs the `hooks-screen` binary (`nice -n 19 bash screen/build.sh`) and the next ccy relaunch to take effect.

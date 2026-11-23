# Callout: ccy supervisor answers Claude Code's rate-limit dialog and resumes after the reset

**Plan**: 00523
**Audience**: client projects using ccy

When a session hits a usage limit, Claude Code shows a `What do you want to do?` menu. The ccy supervisor now picks `Stop and wait for limit to reset`. Once the reset time has passed and the session is idle, it clears Claude Code's pre-filled `continue` from the input box and sends one `continue` of its own. While that `continue` is pending, it types nothing else into the box, so a model restore or a usage-pause `/compact` cannot be appended to the pre-fill.

The supervisor does this once per reset window. If the human types into the dialog, the window is left to them. Anything the supervisor does not recognise exactly gets no keystroke.

The feature is on by default. Set `CCY_RATE_LIMIT_DIALOG=off` in `ccy.env` to disable it.

It reads the rendered screen, so it needs the `hooks-screen` binary. Build it with `nice -n 19 bash screen/build.sh`. Because the screen read runs in the supervisor host, the feature takes effect on the next ccy relaunch; a worker reload is not enough.

The dialog fixtures in the tests are reconstructed from Claude Code's own strings and have not yet been checked against a live dialog. A screen that looks like the dialog but is not recognised is saved to `supervise-rate-limit-unrecognised.txt` in the status directory. No configuration changes.

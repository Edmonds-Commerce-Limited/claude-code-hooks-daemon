# Callout: the ccy supervisor can now read the screen to decide its focus hold

**Plan**: 00538
**Audience**: operators

With `CCY_FOCUS_HOLD=1`, the supervisor's focus hold used to rely on your keystrokes alone, so one history recall could hold every send for hours. A keystroke latch now only asks a new small Rust helper, `hooks-screen`, to render the terminal output and say which view is showing. Only a `transcript` or `panel-selected` verdict holds. A missing helper, a timeout or an `unknown` screen lets sends through.

Until real screen captures exist the helper recognises nothing, so the hold stays effectively off. To help build the recognisers, set `CCY_SCREEN_CAPTURE=1` alongside `CCY_FOCUS_HOLD=1`, open a sub-agent transcript once, and keep `untracked/supervise/screen-capture/`. Build the helper with `bash screen/build.sh`. Its renderer is the vendored `vt100` crate (checked into `screen/vendor/`, built offline and locked), because terminal emulation is a correctness problem; the relay stays std-only. This is host code, so relaunch ccy to pick it up.

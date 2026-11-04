# Callout: the ccy supervisor's main-thread focus hold is now off by default

**Plan**: 00474
**Audience**: operators

The ccy supervisor has a focus hold. It stops typing anything while the main prompt may not have focus, for example after an Up arrow that could have moved into the sub-agent panel. The hold judges this from your keys alone, so it cannot tell a history recall (Up, then Enter at the main prompt) from panel navigation, and only Esc ends it. In live use one history recall left the supervisor holding every send for more than fifteen hours while the main thread plainly had focus.

The hold is now off unless you set `CCY_FOCUS_HOLD=1` in the ccy environment. It is host code, so relaunch ccy to pick up the change. A host started before the upgrade keeps holding until it is relaunched; press Esc to release a hold in the meantime.

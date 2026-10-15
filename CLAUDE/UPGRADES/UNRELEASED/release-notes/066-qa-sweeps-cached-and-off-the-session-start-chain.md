# Callout: the docs and plan QA session-start sweeps are cached and no longer hold up the chain

**Plan**: 00495
**Audience**: client projects

`docs-qa-sweep` and `plan-qa-sweep` re-ran their whole check catalogue on every new session. On a repository with a large documentation tree that is several CPU-seconds, enough to overrun the SessionStart dispatch budget so that handlers behind them were dropped.

Each sweep now keeps its last result in `<daemon untracked dir>/sweep-cache/<sweep>.json`, keyed by a fingerprint of everything that can change a finding: the stat of every project file outside `.git`, dependency and cache directories and the daemon's own runtime directory, the policy, the daemon version, the date and, for the plan sweep, the HEAD commit and plan counter. A session with an unchanged fingerprint reports the cached result. Any change is a miss: the sweep runs on a background thread and the handler waits at most one second for it. A sweep that finishes in that time is reported as before. One that does not is reported as "still running in the background" with the previous result labelled as possibly out of date, and its result is cached for the next session. Nothing is dropped and no check is skipped; `hooks-daemon docs-qa --sweep` and `plan-qa --sweep` still run in the foreground against the live tree.

No configuration change is needed. Deleting the `sweep-cache/` directory forces a full sweep at the next session start.

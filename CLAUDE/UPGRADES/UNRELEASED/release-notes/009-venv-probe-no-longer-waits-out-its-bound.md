# Callout: a venv cache miss no longer costs the probe's full timeout

**Plan**: 00500
**Audience**: operators

When the hook's venv resolver had to probe a candidate interpreter (a cache miss), every probe used to cost the whole watchdog bound, about 5 seconds, even when the candidate answered at once. The watchdog held the caller's output pipe until its `sleep` ended. It now detaches its input and output and kills its own `sleep` when the candidate answers, so a good candidate costs milliseconds. A hanging candidate is still killed at the bound. Nothing to do on upgrade.

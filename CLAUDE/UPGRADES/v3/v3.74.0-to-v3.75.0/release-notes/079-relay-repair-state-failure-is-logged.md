# Callout: a relay repair that cannot create its state file is logged

**Plan**: 00608
**Audience**: operators

When the session-start relay repair could not create its state directory or file, it returned the reason into that one session's start-up context only and wrote nothing to the daemon log, so the failure left no trace afterwards. It now also logs an error naming the binary and the reason. The repair is still not started in that case, and nothing else changes.

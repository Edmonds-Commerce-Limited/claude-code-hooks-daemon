# Callout: the protected-file index now builds in the live daemon, and says so when it cannot

**Plan**: 00474
**Audience**: operators

The cached index of protected files that `secret_file_guard` and `quarantine_artefact_read_guard` consult for recursive searches and globs (Plan 00483 A2) could stay unavailable for the whole life of a daemon on a large working copy: every recursive search kept drawing the "index of protected files is not available yet" advisory. The background build ran its `git ls-files` listings under the 5 second hot-path bound, the `--ignored` listing alone takes 3 to 7 seconds there, and a timed-out build was remembered as failed for ten minutes with nothing logged.

The build now has its own 120 second bound per listing, logs a warning naming the reason when git gives no answer or the build raises, retries after 30 seconds rather than ten minutes, and starts at daemon startup so the first recursive search after a restart is judged sooner. No configuration changes.

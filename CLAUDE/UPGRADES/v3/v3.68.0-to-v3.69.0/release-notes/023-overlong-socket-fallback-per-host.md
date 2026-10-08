# Callout: an over-length socket path is reported not live

**Plan**: 00483
**Audience**: everyone

When a project path is so long that the daemon's socket path is past the AF_UNIX limit, the start-up liveness check now reports it as not live instead of "indeterminate". Previously `start` refused with a false "socket exists but its liveness is indeterminate" message even though nothing existed at that path.

This fix by itself changes no path; the per-host fallback names are a separate change below.

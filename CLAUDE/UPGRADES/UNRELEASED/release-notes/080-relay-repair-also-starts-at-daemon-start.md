# Callout: the relay repair also starts when the daemon starts

**Plan**: 00608
**Audience**: operators

An unusable relay binary was repaired in the background only by the session-start check. A clone provisioned after its session began, or a session whose start-up hook never reached the daemon, therefore stayed on the slower fallback transport until the next session start. The daemon now judges the configured relay binary at its own start-up, as a deferred step after its socket is bound, and starts the same detached repair. It is once per cause, shared with the session-start check through one claim file, so the two triggers never build twice, and a failed attempt stays failed until `transport on` is run by hand. The step never delays or stops daemon start-up: a failure to judge or start the repair is logged at ERROR in the daemon log. A relay disabled in config, or a usable binary, starts nothing.

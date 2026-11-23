# Callout: the daemon can read a session's teamchat role per team; `hooks-daemon team-seat` shows it

**Plan**: 00631
**Audience**: operators

A session started inside a teamchat team now carries `TEAMCHAT_RUNTIME` and `TEAMCHAT_KIT` on its hook payload, and the daemon can ask the kit's own `teamchat whoami --json` which role and duty the session holds in each team, cached for `team_seat.resolve_ttl_seconds` (default 60). Nothing changes behaviour yet: this is the resolver later team-aware handlers build on. A session in no team costs one string check, and an answer the daemon cannot read is treated as "role unknown", which never switches a guard off. Run `hooks-daemon team-seat` (or `--json`) in a session to see what it resolves to; it is read-only, prints no secrets or paths, and exits 3 when a team is signalled but the role could not be read. Set `team_seat.detection: off` to never run the probe.

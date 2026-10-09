# Callout: the host status-line segment shows the session's role as `role@host`

**Plan**: 00474
**Audience**: operators

When a session sets a hostname override (`HOOKS_DAEMON_HOSTNAME`, the role that `persistent_crons` `hosts:` entries match against), the opt-in `host_hostname` segment now shows it before the `@`. For example, it renders `sdlc-runner@build-box` instead of `@build-box`. A role longer than 15 characters is cut to its first 10 characters followed by `...`, so a long alias cannot crowd out the host name. When no override is set, or the override equals the host's own name (as it does when only `CCY_HOST_HOSTNAME` is set), the segment is unchanged. The role is read on every render from the session's payload, while the host name is still resolved once per daemon start. No configuration change is needed. The segment remains disabled by default.

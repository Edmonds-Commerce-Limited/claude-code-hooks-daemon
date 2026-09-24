# Callout: the operator-signal channel now runs without a venv

**Plan**: 00457
**Audience**: operators

`bin/hooks-daemon signal ... --all-sessions` — the host-side reboot/shutdown
warning for container-deployed sessions — used to refuse with exit 5 on a
host whose only venv for the project was built inside the container, exactly
the deployment this channel exists for. It now runs under a system
`python3` (>= 3.8) before venv resolution, the same way `repair` already
does for its own missing-venv case, so no workaround is needed. Nothing
changes when a venv does resolve.

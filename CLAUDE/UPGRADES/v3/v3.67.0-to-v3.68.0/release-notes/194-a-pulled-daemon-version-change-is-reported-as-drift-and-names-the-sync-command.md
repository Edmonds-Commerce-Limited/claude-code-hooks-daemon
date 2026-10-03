# Callout: a pulled daemon version change is reported as drift, and a downgrade is named as one

**Plan**: 00477
**Audience**: operators

The installed daemon clone under `.claude/hooks-daemon/` is gitignored and per-checkout. When a pull changes `daemon.expected_version` in `.claude/hooks-daemon.yaml`, the clone stays at the old version, and nothing said so. Two places now do:

- **A running daemon**, at SessionStart (new and resumed sessions): the `version_check` handler compares the running version with the key and tells both the human and the agent the two versions, where the expected one came from, whether syncing is an UPGRADE or a DOWNGRADE, and the command a human runs: `/hooks-daemon upgrade X.Y.Z`. A downgrade asks for confirmation that it is intended, since it can come from a commit made on an older checkout. The check reads only local files and never asks the network.
- **A daemon that cannot start**, in `init.sh`: the existing version-mismatch message (clone against the tracked assets) now compares the clone with the resolved expected version, the config key first and the `.claude/HOOKS-DAEMON.md` header for a project that predates the key. It is reached only after a failed start, so a healthy hook path pays nothing.

Nothing moves the daemon to another version: the notice only names the command. The daemon's own repository never reports drift, a branch install (which writes no key) is left to its own advisory, and an invalid `daemon.expected_version` keeps the state it already had.

Also fixed: `_resolve_python_cmd` in `init.sh` returned success after a failed resolve, with the interpreter left empty. It now returns the resolver's status.

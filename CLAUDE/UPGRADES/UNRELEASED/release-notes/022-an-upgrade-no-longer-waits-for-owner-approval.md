# Callout: an upgrade no longer waits for the project owner's approval, and a large jump gets advice to go in phases

**Plan**: 00503
**Audience**: everyone

The pre-deploy upgrade gate had two stops: the reading confirmation (exit 3) and, for a breaking upgrade, the project owner's approval (exit 4), given in their own terminal with `hooks-daemon approve-upgrade`. The owner ruled the second one friction with no safety value: the threat model is a careless agent, not a hostile one, and an installed daemon older than the gate has no `approve-upgrade`, so a project could be stuck behind a long pipeline command just to say yes.

The approval tier is removed. There is no exit 4, no `upgrade-approvals/` marker, no `approve-upgrade` command (and no `approve` form of the standalone gate), and no `upgrade_approval_guard` handler with its rules `R-UPGRADE-APPROVAL-AGENT` and `R-UPGRADE-APPROVAL-ENV-BYPASS`. A config that still names `upgrade_approval_guard:` keeps validating; the key is retired, so it is accepted silently. Delete it when convenient.

What used to need approval - a MAJOR bump, a crossed config-changes manifest declaring `breaking: true`, a `critical` pre-upgrade task found in the project, or an installed version the gate cannot read - is now listed first, under "READ THIS FIRST: this upgrade is likely to break the project", in the same listing the reading confirmation already stops on. Read it, carry out the pre-upgrade tasks it names, and re-run the upgrade with `--skip-reading-confirmation=<digest>`; that is the whole gate. The reading confirmation itself is unchanged.

A large jump - one that crosses a MAJOR boundary, or spans more than ten minor releases - now also prints `ADVICE:` to upgrade in phases, naming an intermediate release (the last release of the current major, or one near ten minors ahead). It is advice only: it never stops the upgrade, changes the digest or sets an exit code.

An upgrade runs the gate from the TARGET release's code, not from the installed daemon's, so a project upgrading from 3.68 or 3.69 to this release meets no approval stop. Only an upgrade whose target is still 3.68.0 or 3.69.0 prints the old approval stop; move the target to this release or later instead of running `approve-upgrade`.

The gated-install receipt now lives in `untracked/upgrade-gate/gated-install.json` (it was under `upgrade-approvals/`). A project that had one is asked for the reading once on a same-version re-run that claims the target is already installed; its first upgrade through this gate records the new receipt.

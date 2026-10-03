# Callout: a fresh install no longer trips the upgrade gate on its first re-run

**Plan**: 00474
**Audience**: operators

v3.68.0 shipped with a defect: a project freshly installed at v3.68.0 left no gated-install record, so re-running the upgrade to the same v3.68.0 stopped for the project owner with every guide since v2.0 listed. A fresh install now records itself the way a gated upgrade does, so the idempotent re-run proceeds. A v3.68.0 install that already lacks the record is still stopped on a same-version re-run, deliberately: its history cannot be told from a manual checkout plus `hooks-daemon repair`. Upgrading to any later release is not affected, and the owner can approve the re-run with `hooks-daemon approve-upgrade`.

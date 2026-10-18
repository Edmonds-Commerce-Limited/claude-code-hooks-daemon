# Task: Commit `daemon.expected_version` and `.claude/provision.sh` so other checkouts follow this upgrade

**Type**: workflow-change
**Severity**: recommended
**Applies to**: all
**Idempotent**: yes

## Why

Plan 00477. An upgraded project gains two things that only work once they are COMMITTED. One is the `daemon.expected_version` key in `.claude/hooks-daemon.yaml`, which the upgrade writes. The other is the tracked `.claude/provision.sh`, which the upgrade deploys. A fresh clone uses them to build exactly this daemon version (`bash .claude/provision.sh`). Another checkout that pulls the commit uses them to sync its gitignored daemon clone to it. From this release, an UPGRADE pulled into another checkout is synced in the background at that checkout's next session start, with no manual step. The sync is started by the tracked `.claude/hooks/session-start` forwarder, which the upgrade regenerates. It works only once these files are in the commit the other checkout pulls, and the upgrade commit normally carries the forwarder already.

## How to detect if this applies to you

Check that the key is present and that both files are tracked with no uncommitted change. Sample:

```bash
grep -nE '^[[:space:]]+expected_version:' .claude/hooks-daemon.yaml
git ls-files --error-unmatch .claude/provision.sh .claude/hooks-daemon.yaml
git status --porcelain -- .claude/provision.sh .claude/hooks-daemon.yaml
```

The task applies when the `grep` finds nothing, when `git ls-files` reports either file as untracked, or when `git status` lists either one. In the daemon's own repository (self-install) it does not apply: that repository has no daemon clone to provision or sync.

## How to handle

- **The key is missing**: the upgrade writes it unless the install is a branch install, which has no release to name. On a release install, re-run the upgrade's expected-version step. Sample, from the project root:

  ```bash
  .claude/hooks-daemon/untracked/venv-*/bin/python -m claude_code_hooks_daemon.install.expected_version --project-root .
  ```

  If more than one venv matches the glob, use the one the running daemon uses.

- **Either file is untracked or modified**: commit it with the rest of the upgrade. `.claude/provision.sh` is daemon-owned: commit it as deployed, and do not edit it. `.claude/hooks-daemon.yaml` belongs to the project, so review its diff before committing.

- **`.claude/provision.sh` is ignored by a project `.gitignore` rule**: ask the user before changing the ignore rules. A fresh clone cannot provision itself without the file.

## How to confirm

`git ls-files .claude/provision.sh .claude/hooks-daemon.yaml` lists both files. `git status --porcelain` lists neither. `grep` finds `expected_version:` with this release's version.

## Rollback / if this goes wrong

Both are ordinary tracked changes: `git revert` the commit. Without them, a fresh clone or a pulled upgrade falls back to the manual route the session-start notices name.

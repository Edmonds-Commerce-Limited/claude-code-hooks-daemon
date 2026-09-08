# Task: Drop the `HOOKS_DAEMON_PYTHON` workaround for an old default `python3`

**Type**: config-migration
**Severity**: optional
**Applies to**: all
**Idempotent**: yes

## Why

Interpreter discovery used to compare against a HARDCODED candidate list
(`python3.11`, `python3.12`, `python3.13`). On a host whose default `python3`
predates the 3.11 floor that had two failure modes: it could not find a newer
interpreter the list did not name, and when it failed it suggested installing a
version that might not exist.

The field report behind this came from a host with `python3` at 3.9 alongside
`python3.13` and `python3.14`. The installer aborted, and the only way through
was to set `HOOKS_DAEMON_PYTHON=python3.13` by hand.

Discovery now enumerates every `python3.NN` on `PATH`, keeps those at or above
the floor, and selects the HIGHEST — so that host resolves `python3.14`
unaided. When nothing qualifies, the diagnostic lists the interpreters it
actually observed and their versions rather than naming a version that may not
be installed.

`HOOKS_DAEMON_PYTHON` is **still honoured and still supported.** This task
concerns only the case where it was set to escape the old discovery, where it
is now redundant — and where leaving it set pins you to an interpreter you did
not really choose.

## How to detect if this applies to you

You are affected only if `HOOKS_DAEMON_PYTHON` is set somewhere persistent AND
its value was chosen to work around the old discovery rather than for a reason
of your own.

Sample — look in the usual places:

```bash
# Current environment
echo "${HOOKS_DAEMON_PYTHON:-<unset>}"

# Shell profiles, service units, container definitions, CI config
grep -rn 'HOOKS_DAEMON_PYTHON' \
  ~/.bashrc ~/.zshrc ~/.profile \
  /etc/systemd/system .github/ Dockerfile* docker-compose*.y*ml 2>/dev/null
```

If it is unset everywhere, this task does not apply — stop here.

If it IS set, check what discovery would now reach on its own:

```bash
# sample — adapt the path to where the daemon is installed
bash -c 'source .claude/hooks-daemon/scripts/lib/python_discovery.sh \
         && find_latest_python 3.11'
```

## How to handle

Compare that result with your `HOOKS_DAEMON_PYTHON` value.

- **Discovery finds the same or a newer interpreter** — the override is
  redundant. Remove it and let discovery track your newest qualifying
  interpreter automatically, which is the point of the change.
- **Discovery finds nothing** — keep the override. Your host has no
  `python3.NN` on `PATH` at or above 3.11, so the override is doing real work.
  Note that a bare `python3` carrying no `.NN` suffix is deliberately not
  matched, so this can happen on a host that does have a modern interpreter
  under that one name.
- **Discovery finds a DIFFERENT interpreter and you wanted the pinned one** —
  keep the override. Pinning a specific interpreter deliberately is a supported
  use, not a workaround. **Ask the user rather than deciding this one**: an
  override that looks redundant may be holding the venv on a particular
  interpreter on purpose, and you cannot tell which from the value alone.

Removing the override changes which interpreter builds the venv, so re-provision
rather than leaving one built by the old interpreter in place:

```bash
# sample — after removing the override
./scripts/qa/run_tests.sh   # provisions against the newly-discovered interpreter
```

## How to confirm

```bash
echo "${HOOKS_DAEMON_PYTHON:-<unset>}"       # expect <unset> if you removed it
.claude/hooks-daemon/bin/hooks-daemon status  # expect Status: RUNNING
```

## Rollback / if this goes wrong

Re-export the variable with its previous value; nothing else changed.

```bash
export HOOKS_DAEMON_PYTHON=/path/to/python3.NN
```

If the venv was rebuilt against an interpreter that turns out to be wrong for
your project, the old one was not overwritten — venv paths are fingerprinted per
interpreter, so restoring the override and re-running re-selects the original.

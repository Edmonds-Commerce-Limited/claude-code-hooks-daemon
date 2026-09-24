# Callout: a venv that cannot run no longer reports itself "resolved"

**Plan**: 00466
**Audience**: operators

The venv resolver used to accept a candidate `untracked/venv-*/bin/python`
on its executable bit alone. A venv built inside a container can be
present and `+x` and still fail at exec time on the host — wrong
architecture/libc, or a symlink into a container-only path. That candidate
was reported "resolved", so `bin/hooks-daemon` never reached its venv-free
path for `repair`/`signal` and instead crashed on a raw exec error. Every
resolution site — the bash `scripts/lib/resolve_venv.sh::_rv_pick_python`
fallback and the Python `resolve_existing_venv_python_with_diagnostics`
SSOT (its metadata, fingerprint-keyed, scan-fallback and legacy steps) —
now launches a candidate before accepting it, falls through to the next
candidate (and ultimately the venv-free path) on failure, and names the
rejected venv and the `repair` command in its diagnostic. Only reached on
a resolver-cache miss, so this adds no cost to the steady-state per-hook
path.

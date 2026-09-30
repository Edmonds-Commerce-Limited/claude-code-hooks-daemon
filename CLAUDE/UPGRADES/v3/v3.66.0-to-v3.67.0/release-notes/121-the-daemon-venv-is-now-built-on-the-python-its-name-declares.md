# Callout: the daemon's venv is now built on the Python its name declares

**Plan**: 00466
**Audience**: client projects

A daemon venv is named after the Python it was fingerprinted from
(`venv-…-py311-…`). The bootstrap passed the bare name `python3` to
`uv sync --python`, and uv reads that as "any Python 3". So on a machine where
uv prefers a managed interpreter, a `py311` venv could quietly be built on 3.12
or 3.13, and the daemon ran on a Python its venv's name denied.

The bootstrap now hands uv the resolved interpreter path. It also checks the
built venv's version and refuses a mismatch with an error naming both versions,
instead of using the wrong venv. An existing mislabelled venv is left as it is.
To check yours, compare the output of the venv's `bin/python --version` with the
`pyMM` in its name. If they differ, delete the venv; the next daemon start
rebuilds it on the right interpreter.

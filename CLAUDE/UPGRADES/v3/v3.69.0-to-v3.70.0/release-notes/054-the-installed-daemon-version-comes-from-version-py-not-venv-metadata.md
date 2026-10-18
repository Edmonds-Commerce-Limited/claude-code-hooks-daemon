# Callout: the installed daemon version comes from version.py, not from venv metadata

**Plan**: 00517
**Audience**: client projects

The running daemon's upgrade notice (`daemon_upgrade_detector`) took the installed version from the selected venv's `.daemon-metadata.json`, a copy written when the venv was built, so a venv whose metadata disagreed with the source it served reported a version that was not installed. It now reads the `__version__` literal in the installed source tree's `version.py`, as text and fresh on every prompt, so a source upgraded underneath a running daemon is reported and a venv with different metadata is not. The metadata keeps only what tells venvs apart (`lock_hash`, `python_path`) and the version that built the venv.

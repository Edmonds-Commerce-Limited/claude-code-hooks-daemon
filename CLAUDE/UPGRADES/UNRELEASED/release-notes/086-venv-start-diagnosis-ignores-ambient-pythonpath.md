# Callout: the venv start diagnosis no longer trusts an ambient PYTHONPATH

**Audience**: client projects

When the daemon fails to start, it runs the venv's own interpreter to report why (version, `site-packages` on `sys.path`, whether the daemon package imports). That probe inherited the caller's `PYTHONPATH`, so a shell that exports `PYTHONPATH=<checkout>/src` made a venv with no daemon package report `importable: yes` and `healthy`, hiding a broken venv. The probe now runs without `PYTHONPATH`, so it judges the venv itself.

Nothing to do on upgrade. The start-failure message may now name a venv problem that was previously masked.

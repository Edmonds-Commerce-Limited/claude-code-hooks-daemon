"""Config-optimisation last-run tracking (Plan 00308).

Records which daemon version a project last ran the ``/optimise`` (aka
"config-optimisation") review against, so the
``config_optimisation_reminder`` SessionStart handler can surface a stale
review after an upgrade instead of it being silently skipped.
"""

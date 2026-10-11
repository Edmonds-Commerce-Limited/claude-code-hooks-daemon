"""Arm the doc-write jail in a Python spawned by a test run (Plan 00474 N280).

Imported automatically at interpreter start because the run puts this directory
on the child's ``PYTHONPATH``. It does nothing unless the jail's environment is
present.
"""

import doc_write_jail

doc_write_jail.install_from_environment()

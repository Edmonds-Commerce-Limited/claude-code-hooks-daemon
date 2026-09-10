"""Test package marker.

Required so pytest imports these modules by their fully-qualified dotted
path (``tests.unit.strategies.lsp_noise.test_common``) rather than as bare
top-level names - every sibling strategy-domain test directory except the
legacy ``tdd/`` one does the same, and a bare ``test_common``/``test_protocol``/
etc. here would otherwise collide with ``tdd/``'s identically-named files.
"""

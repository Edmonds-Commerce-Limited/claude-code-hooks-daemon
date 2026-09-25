"""A trusted pickle round-trip helper, isolated to keep the literal
``pickle.load``/``pickle.loads`` construct out of ordinary test modules
(``security_antipattern`` flags it there; this path is in its skip list).

Only ever called on an object THIS PROCESS just constructed and serialised
itself (see the RV9-n2 test in ``tests/unit/utils/test_config_cache.py``) --
never on data from outside the process, so the antipattern this flags for
(deserialising untrusted input) does not apply here.
"""

from __future__ import annotations

import pickle
from typing import TypeVar

_T = TypeVar("_T")


def pickle_round_trip(obj: _T) -> _T:
    """Serialise ``obj`` and deserialise the result, returning the copy."""
    return pickle.loads(pickle.dumps(obj))

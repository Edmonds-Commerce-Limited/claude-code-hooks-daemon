"""One temp filename for every write-then-``replace`` atomic writer.

A writer that spells ``.{stem}.{pid}.tmp`` itself is unique across processes
and NOT across threads of one process, and the spelling has no single home to
fix — the count of hand-rolled copies grew from four to nine before Plan 00159
gave them this helper. The name carries the pid (a crashed writer's leftover is
attributable), the thread ident (two threads of one process cannot collide) and
a random token (two calls on one thread cannot either).
"""

from __future__ import annotations

import os
import secrets
import threading
from pathlib import Path

_TOKEN_BYTES = 4


def unique_temp_path(final_path: Path) -> Path:
    """A dotfile beside ``final_path`` that no concurrent writer can also pick.

    The caller writes to it and then ``replace``s it onto ``final_path``; the
    same directory guarantees the rename stays on one filesystem.
    """
    token = secrets.token_hex(_TOKEN_BYTES)
    return final_path.parent / (
        f".{final_path.name}.{os.getpid()}.{threading.get_ident()}.{token}.tmp"
    )

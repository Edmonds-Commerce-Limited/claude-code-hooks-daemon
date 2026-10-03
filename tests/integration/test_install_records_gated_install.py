"""N327: a fresh install must record itself the way a gated upgrade does.

The pre-deploy gate treats a venv stamp naming the target, with no gated-install
receipt, as an install of unknown history and sends it to the owner. A fresh
install runs no gate, so ``scripts/install_version.sh`` has to leave the receipt
itself -- and only when the venv carried no stamp before it, because a stamp
that was already there may have been written by a manual checkout plus repair.
The end-to-end behaviour is pinned by tests/acceptance; this pins the placement.
"""

from __future__ import annotations

from pathlib import Path

INSTALL_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "install_version.sh"


def _text() -> str:
    return INSTALL_SCRIPT.read_text(encoding="utf-8")


def test_install_records_the_gated_install_after_the_venv_is_stamped() -> None:
    text = _text()
    assert "upgrade_gate_standalone.py" in text
    assert "record-install" in text
    assert text.index('ensure_venv "$DAEMON_DIR"') < text.index("record-install")


def test_the_prior_stamp_is_read_before_ensure_venv_stamps_the_venv() -> None:
    text = _text()
    assert text.index("PRIOR_VENV_STAMP") < text.index('ensure_venv "$DAEMON_DIR"')


def test_the_record_is_written_only_for_a_fresh_install() -> None:
    text = _text()
    after = text[text.index("record-install") - 600 : text.index("record-install")]
    assert '-z "$PRIOR_VENV_STAMP"' in after

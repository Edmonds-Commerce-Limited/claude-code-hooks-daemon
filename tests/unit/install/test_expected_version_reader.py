"""Plan 00477 Task 5.1 - reading back the version a project expects.

``read_expected_version`` is the Python twin of ``_resolve_expected_version``'s config
step in ``init.sh``. It answers one question for the running daemon: which version does
the tracked ``daemon.expected_version`` name right now. Anything that is not a usable
X.Y.Z answers None, so a caller can never act on a guess; a file that is not valid YAML
raises, since that is an error rather than an absent answer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.expected_version import read_expected_version


def _config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "hooks-daemon.yaml"
    path.write_text(text)
    return path


class TestReadExpectedVersion:
    def test_reads_the_recorded_version(self, tmp_path: Path) -> None:
        path = _config(tmp_path, 'daemon:\n  expected_version: "3.68.0"  # note\n')
        assert read_expected_version(path) == "3.68.0"

    def test_a_missing_key_is_none(self, tmp_path: Path) -> None:
        assert read_expected_version(_config(tmp_path, "daemon:\n  log_level: INFO\n")) is None

    def test_a_missing_daemon_block_is_none(self, tmp_path: Path) -> None:
        assert read_expected_version(_config(tmp_path, "handlers: {}\n")) is None

    def test_a_missing_file_is_none(self, tmp_path: Path) -> None:
        assert read_expected_version(tmp_path / "absent.yaml") is None

    @pytest.mark.parametrize("bad", ["main", "3.68", "v3.68.0", "3.68.0-rc1", '""', "3", "[1]"])
    def test_an_invalid_value_is_none(self, tmp_path: Path, bad: str) -> None:
        path = _config(tmp_path, f"daemon:\n  expected_version: {bad}\n")
        assert read_expected_version(path) is None

    def test_unparseable_yaml_raises_rather_than_guessing(self, tmp_path: Path) -> None:
        path = _config(tmp_path, "daemon: [unclosed\n")
        with pytest.raises(ValueError, match="Invalid YAML"):
            read_expected_version(path)

    def test_a_non_mapping_document_is_none(self, tmp_path: Path) -> None:
        assert read_expected_version(_config(tmp_path, "- a\n- b\n")) is None

    def test_a_daemon_value_that_is_not_a_mapping_is_none(self, tmp_path: Path) -> None:
        assert read_expected_version(_config(tmp_path, "daemon: nope\n")) is None

    def test_a_bare_number_is_not_a_version(self, tmp_path: Path) -> None:
        """YAML reads an unquoted 3.68 as a float; it is not X.Y.Z."""
        assert (
            read_expected_version(_config(tmp_path, "daemon:\n  expected_version: 3.68\n")) is None
        )

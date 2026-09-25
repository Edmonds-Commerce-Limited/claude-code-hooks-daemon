"""Every transcript-directory derivation names the same directory (00466 N27).

``skill-scan`` and ``tool-report`` each derived Claude Code's per-project
directory with their own code and disagreed for a path containing ``.`` or
``_``: one of them read a directory that does not exist and reported "no data".
Each derivation site is pinned here to the shared helper.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.skill_scan.extraction import derive_transcript_dir
from claude_code_hooks_daemon.tool_report.analyser import transcripts_root_for
from claude_code_hooks_daemon.utils.claude_config import claude_project_dir


def _awkward_project(tmp_path: Path) -> Path:
    root = tmp_path / "my_app.v2" / "sub-dir"
    root.mkdir(parents=True)
    return root


def test_skill_scan_names_claude_codes_directory(tmp_path: Path) -> None:
    root = _awkward_project(tmp_path)
    config = tmp_path / "cfg"
    assert derive_transcript_dir(root, config_dir=config) == claude_project_dir(
        root, config_dir=config
    )


def test_tool_report_names_claude_codes_directory(tmp_path: Path) -> None:
    root = _awkward_project(tmp_path)
    config = tmp_path / "cfg"
    assert transcripts_root_for(root, config) == claude_project_dir(root, config_dir=config)


def test_both_commands_agree_for_a_dotted_underscored_path(tmp_path: Path) -> None:
    root = _awkward_project(tmp_path)
    config = tmp_path / "cfg"
    assert derive_transcript_dir(root, config_dir=config) == transcripts_root_for(root, config)

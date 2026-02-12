"""Guide path resolution utilities.

Provides filesystem paths to guide documents shipped with the daemon package.
Handlers reference guides by path so LLMs can read them on demand.
"""

from pathlib import Path

# Guide filename constant
_LLM_COMMAND_GUIDE_FILENAME = "llm-command-wrappers.md"

# Guides package directory (relative to this file)
_GUIDES_DIR = Path(__file__).resolve().parent.parent / "guides"


def get_llm_command_guide_path() -> str:
    """Return absolute filesystem path to the LLM command wrapper guide.

    Uses __file__-relative path resolution, which works in both
    development (editable install) and production (installed package).

    Returns:
        Absolute path to the guide markdown file.
    """
    return str(_GUIDES_DIR / _LLM_COMMAND_GUIDE_FILENAME)

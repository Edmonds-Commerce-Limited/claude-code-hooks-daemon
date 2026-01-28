"""Plan numbering utilities for planning mode integration."""

import re
from pathlib import Path


def get_next_plan_number(plan_folder: Path) -> str:
    """Calculate next plan number by scanning plan folder.

    Scans the plan folder (and non-numbered subdirectories) for the highest
    plan number and returns the next number as a 5-digit zero-padded string.

    Plan folders follow the pattern: {number}-{name}/
    - number: 1-5 digits (e.g., 001, 00001, 123)
    - name: any text

    Subdirectories that start with digits are treated as plan folders and are
    NOT scanned recursively (they are plans, not archives).

    Subdirectories that don't start with digits (e.g., "archive/", "2025/")
    ARE scanned recursively to find archived plans.

    Args:
        plan_folder: Path to CLAUDE/Plan directory

    Returns:
        Next plan number as 5-digit zero-padded string (e.g., "00001", "00042")

    Raises:
        FileNotFoundError: If plan_folder does not exist

    Examples:
        >>> get_next_plan_number(Path("CLAUDE/Plan"))  # Empty dir
        "00001"
        >>> # Dir with: 00001-first/, 00003-third/
        >>> get_next_plan_number(Path("CLAUDE/Plan"))
        "00004"
        >>> # Dir with: 00001-current/, archive/00002-old/
        >>> get_next_plan_number(Path("CLAUDE/Plan"))
        "00003"
    """
    if not plan_folder.exists():
        raise FileNotFoundError(f"Plan directory does not exist: {plan_folder}")

    highest_number = 0
    pattern = re.compile(r"^(\d+)-")

    def scan_directory(directory: Path, scan_subdirs: bool = True) -> None:
        """Scan directory for plan numbers.

        Args:
            directory: Directory to scan
            scan_subdirs: Whether to recursively scan non-numbered subdirectories
        """
        nonlocal highest_number

        if not directory.is_dir():
            return

        for entry in directory.iterdir():
            # Only process directories
            if not entry.is_dir():
                continue

            # Check if directory name starts with digits
            match = pattern.match(entry.name)
            if match:
                # Found a plan directory
                number = int(match.group(1))
                highest_number = max(highest_number, number)
                # Don't scan numbered directories recursively (they are plans)
                continue

            # Non-numbered directory - scan recursively if enabled
            if scan_subdirs:
                scan_directory(entry, scan_subdirs=True)

    # Scan the main plan folder
    scan_directory(plan_folder, scan_subdirs=True)

    # Return next number as 5-digit zero-padded string
    next_number = highest_number + 1
    return f"{next_number:05d}"

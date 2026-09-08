"""The one version parser for install-time range loaders.

The truth-changes, config-migrations and release-notes loaders, and the
breaking-changes detector, all compare version ranges. They must agree on what
a version string looks like, and in particular they must all accept the TAG
form (``v3.62.0``), because that is the only form this project's own
documentation ever hands to the upgrade path: ``git describe --tags`` always
emits the prefix, and every ``RELEASES/vX.Y.Z.md`` prints the literal ``v``
argument. A loader that rejects it does not fail loudly — it skips the check
that would have warned about the change, on every tagged upgrade.

Only the prefix is forgiven. Everything after it must still be dot-separated
integers, so this cannot widen into "accept anything".
"""

from __future__ import annotations

_VERSION_SEPARATOR = "."
_TAG_PREFIXES = ("v", "V")


def strip_tag_prefix(version: str) -> str:
    """Return ``version`` without a single leading ``v``/``V``."""
    for prefix in _TAG_PREFIXES:
        if version.startswith(prefix):
            return version[len(prefix) :]
    return version


def parse_version_tuple(version: str) -> tuple[int, ...]:
    """Parse ``'3.62.0'`` or ``'v3.62.0'`` into a sortable tuple of ints.

    Args:
        version: Version string, with or without a leading ``v``/``V``.

    Returns:
        Tuple of ints such as ``(3, 62, 0)`` for numeric comparison.

    Raises:
        ValueError: If any component after the optional prefix is not an int.
    """
    try:
        return tuple(int(part) for part in strip_tag_prefix(version).split(_VERSION_SEPARATOR))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid version string: {version!r}") from exc

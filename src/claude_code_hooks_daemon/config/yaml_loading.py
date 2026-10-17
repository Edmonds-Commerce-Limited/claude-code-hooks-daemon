"""Safe YAML loading for the daemon's config, on the C parser when PyYAML has one.

``yaml.safe_load`` always uses the pure-Python ``SafeLoader``. PyYAML built
against libyaml also ships ``CSafeLoader``, which accepts the same documents and
refuses the same tags but parses about 13 times faster (Plan 00495 Phase 1: 0.130 s
against 0.010 s on this repository's own config). Only the safe loaders are
ever selected; the unsafe ``Loader``, ``FullLoader`` and ``UnsafeLoader`` are not
reachable from here.

libyaml composes nested collections by C recursion with no depth limit, so a
flow document nested some tens of thousands deep overflows the C stack and
kills the process, where the pure-Python loader raises ``RecursionError``
(which ``Config.load`` reports as ``ValueError``, Ledger 00466 RV9-n1). Flow
depth cannot exceed the number of opening brackets, so a document with more
than ``C_LOADER_MAX_OPEN_BRACKETS`` of them is parsed by the pure-Python
loader. Block nesting that deep would need hundreds of megabytes of
indentation, so it is not counted.
"""

from typing import IO, Any, Final, cast

import yaml

#: PyYAML's C-accelerated safe loader, or None when PyYAML was built without libyaml.
_C_SAFE_LOADER: type[yaml.SafeLoader] | None = getattr(yaml, "CSafeLoader", None)

#: Most ``[`` plus ``{`` a document may hold and still be parsed by libyaml. Far
#: below the depth that overflows its C stack, far above a real config's count.
C_LOADER_MAX_OPEN_BRACKETS: Final[int] = 1000


def select_safe_loader() -> type[yaml.SafeLoader]:
    """The fastest safe loader this PyYAML build offers.

    Returns:
        ``CSafeLoader`` where libyaml is available, otherwise ``SafeLoader``.
    """
    return _C_SAFE_LOADER if _C_SAFE_LOADER is not None else yaml.SafeLoader


def safe_load_yaml(stream: str | IO[str]) -> Any:
    """Parse one YAML document with a safe loader, like ``yaml.safe_load``.

    Args:
        stream: The document text, or an open text file.

    Returns:
        The parsed document (None for an empty one).

    Raises:
        yaml.YAMLError: If the document is not valid YAML or names an unsafe tag.
        RecursionError: If the document is nested too deeply to parse.
    """
    text = stream if isinstance(stream, str) else stream.read()
    if text.count("[") + text.count("{") > C_LOADER_MAX_OPEN_BRACKETS:
        loader_class: type[yaml.SafeLoader] = yaml.SafeLoader
    else:
        loader_class = select_safe_loader()
    loader = loader_class(text)
    try:
        return loader.get_single_data()
    finally:
        # types-PyYAML leaves ``dispose`` unannotated; yaml.load calls it the same way.
        cast("Any", loader).dispose()

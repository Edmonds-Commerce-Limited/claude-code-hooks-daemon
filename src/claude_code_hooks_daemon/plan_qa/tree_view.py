"""Two views of a plan tree: the disk, and the index a commit will record.

The plan tree scan walks directories, tests files and reads documents. Those
four questions are all it asks of the filesystem, so they are the whole of
:class:`TreeView`, and the scan runs unchanged over either answer.

The disk is right for the EDIT surface and the session sweep. It is wrong for
the commit gate (ledger 00474 N244): ``git rm -r --cached`` leaves a folder on
disk that the commit does not carry, so a gate that walks the disk judges a
tree no commit will ever hold. :class:`IndexTreeView` answers the same four
questions from the listing ``git ls-files -s`` gives, with document text loaded
up front in one batch — the view itself never spawns anything.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Protocol


class TreeView(Protocol):
    """The filesystem questions a plan tree scan asks."""

    def children(self, directory: Path) -> list[Path]:
        """Direct children of ``directory``, sorted; empty when it is not a directory."""
        ...

    def is_dir(self, path: Path) -> bool:
        """Whether ``path`` is a directory."""
        ...

    def is_file(self, path: Path) -> bool:
        """Whether ``path`` is a file."""
        ...

    def read_text(self, path: Path) -> str:
        """Text of the file at ``path``."""
        ...


class DiskTreeView:
    """The working tree as it is on disk."""

    def children(self, directory: Path) -> list[Path]:
        """Direct children of ``directory``, sorted."""
        return sorted(directory.iterdir())

    def is_dir(self, path: Path) -> bool:
        """Whether ``path`` is a directory on disk."""
        return path.is_dir()

    def is_file(self, path: Path) -> bool:
        """Whether ``path`` is a file on disk."""
        return path.is_file()

    def read_text(self, path: Path) -> str:
        """Text of the file at ``path`` on disk."""
        return path.read_text()


class IndexTreeView:
    """The tree a commit will record, from a listing of the index.

    Directories are not listed by git, so a directory is any ancestor of a
    listed file. Git cannot record an EMPTY directory, so one that matters
    anyway (an archive directory a project keeps empty until its first plan
    is archived) is declared through ``empty_dirs`` by whoever knows it
    matters, rather than being silently reported missing.
    """

    def __init__(
        self,
        files: Iterable[Path],
        texts: Mapping[Path, str],
        empty_dirs: Iterable[Path] = (),
    ) -> None:
        """Initialise.

        Args:
            files: Every file the commit records, as absolute paths.
            texts: The content of the files a scan will read. Reading one that
                is not here is a programming error and raises ``KeyError``
                rather than falling back to the disk, which is the very thing
                this view exists not to consult.
            empty_dirs: Directories to treat as existing although no listed
                file lives under them.
        """
        self._files = frozenset(files)
        self._texts = dict(texts)
        children: defaultdict[Path, set[Path]] = defaultdict(set)
        for file in self._files:
            child = file
            for parent in file.parents:
                children[parent].add(child)
                child = parent
        for directory in empty_dirs:
            children.setdefault(directory, set())
        self._children = {directory: sorted(names) for directory, names in children.items()}

    def children(self, directory: Path) -> list[Path]:
        """Direct children of ``directory``, sorted; empty when it holds nothing listed."""
        return list(self._children.get(directory, ()))

    def is_dir(self, path: Path) -> bool:
        """Whether some listed file lives under ``path``."""
        return path in self._children

    def is_file(self, path: Path) -> bool:
        """Whether ``path`` is a listed file."""
        return path in self._files

    def read_text(self, path: Path) -> str:
        """The loaded text of ``path``."""
        return self._texts[path]

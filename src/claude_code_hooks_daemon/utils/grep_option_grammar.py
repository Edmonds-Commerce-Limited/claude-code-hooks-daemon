"""Option grammar of the grep family: what each option takes and what supplies the pattern.

Two readers of a ``grep``/``rg``/``git grep`` command line need the same facts:
:mod:`recursive_search` (which words are searched roots) and
:mod:`secret_file_matching` (is a bare name the pattern or a file). Both must
decide whether the first operand is the pattern, and a wrong answer hides a
searched path. The tables below were derived from the tools' own ``--help``
output (GNU grep 3.11, ugrep, ripgrep, git grep 2.47); this module is their
single source.

Positive proof only. An option the tables do not place makes the parse
*uncertain*: callers then keep every operand and judge each as a path, rather
than skipping a word on a guess.

The session's ``grep`` can be GNU grep or ugrep, so ``grep`` is judged against
both: an option only one of them knows is read as that one reads it, and an
option they read differently is unknown. GNU grep accepts any unambiguous
abbreviation of a long option; ugrep and ripgrep do not, and reading
abbreviations for every tool errs towards the stricter reading.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Final, NamedTuple


class Arity(Enum):
    """What an option does with the words around it."""

    FLAG = "flag"
    VALUE = "value"
    # A value only when attached (``--color=auto``); the next word is never consumed.
    OPTIONAL = "optional"
    UNKNOWN = "unknown"


class LongOption(NamedTuple):
    """A long option as the grammar reads it: its arity and its full name."""

    arity: Arity
    name: str | None


_UNKNOWN_LONG: Final = LongOption(Arity.UNKNOWN, None)
_END_OF_OPTIONS: Final = "--"
_RECURSIVE_SHORT: Final = "rR"
_RECURSIVE_LONG: Final = frozenset({"--recursive", "--dereference-recursive"})
_DIGITS: Final = "0123456789"


def _names(text: str) -> frozenset[str]:
    return frozenset(text.split())


@dataclass(frozen=True)
class _Table:
    """The options of one binary."""

    value_short: str
    optional_short: str
    flag_short: str
    value_long: frozenset[str]
    optional_long: frozenset[str]
    flag_long: frozenset[str]
    pattern_short: str
    pattern_long: frozenset[str]
    abbreviates: bool

    def short(self, letter: str) -> Arity:
        """Arity of the short option ``-letter``."""
        if letter in self.value_short:
            return Arity.VALUE
        if letter in self.optional_short:
            return Arity.OPTIONAL
        if letter in self.flag_short:
            return Arity.FLAG
        return Arity.UNKNOWN

    def long(self, name: str) -> LongOption:
        """Arity and full name of the long option ``name`` (``--regex`` for GNU ``--regexp``)."""
        exact = self._exact(name)
        if exact is not None:
            return exact
        if not self.abbreviates:
            return _UNKNOWN_LONG
        matches = {
            option
            for option in self.value_long | self.optional_long | self.flag_long
            if option.startswith(name)
        }
        if len(matches) != 1:
            return _UNKNOWN_LONG
        return self._exact(matches.pop()) or _UNKNOWN_LONG

    def _exact(self, name: str) -> LongOption | None:
        if name in self.value_long:
            return LongOption(Arity.VALUE, name)
        if name in self.optional_long:
            return LongOption(Arity.OPTIONAL, name)
        if name in self.flag_long:
            return LongOption(Arity.FLAG, name)
        return None


_GNU: Final = _Table(
    value_short="ABCDdefm",
    optional_short="",
    flag_short="EFGHILPRTUVZabchilnoqrsvwxz" + _DIGITS,
    value_long=_names(
        "--after-context --before-context --binary-files --context --devices --directories "
        "--exclude --exclude-dir --exclude-from --file --group-separator --include --label "
        "--max-count --regexp"
    ),
    optional_long=_names("--color --colour"),
    flag_long=_names(
        "--basic-regexp --binary --byte-offset --count --dereference-recursive "
        "--extended-regexp --files-with-matches --files-without-match --fixed-strings --help "
        "--ignore-case --initial-tab --invert-match --line-buffered --line-number "
        "--line-regexp --no-filename --no-group-separator --no-ignore-case --no-messages "
        "--null --null-data --only-matching --perl-regexp --quiet --recursive --silent "
        "--text --version --with-filename --word-regexp"
    ),
    pattern_short="ef",
    pattern_long=_names("--regexp --file"),
    abbreviates=True,
)

# -Q (query UI) and --config/--save-config (a config file can carry patterns) are
# deliberately absent: they are unknown, so the parse is uncertain.
_UGREP: Final = _Table(
    value_short="ABCDJKMNOdefgmt",
    optional_short="Z",
    flag_short="%+.@EFGHILPRSTUVWXYabchijklnopqrsuvwxyz" + _DIGITS,
    value_long=_names(
        "--after-context --and --andnot --before-context --binary-files --colors --colours "
        "--context --context-separator --delay --depth --devices --directories --encoding "
        "--exclude --exclude-dir --exclude-from --exclude-fs --file --file-extension "
        "--file-magic --file-type --filter --filter-magic-label --format --from --glob "
        "--iglob --include --include-dir --include-from --include-fs --jobs --label "
        "--max-count --max-files --max-line --max-size --min-count --min-line --min-size "
        "--neg-regexp --not --range --regexp --replace --zmax"
    ),
    optional_long=_names(
        "--color --colour --fuzzy --group-separator --hexdump --hyperlink --ignore-files "
        "--mmap --pager --pretty --separator --sort --tabs --tag --view --width"
    ),
    flag_long=_names(
        "--all --any-line --ascii --basic-regexp --binary --bool --break --byte-offset "
        "--column-number --count --cpp --csv --decompress --dereference-files "
        "--dereference-recursive --dotall --empty --extended-regexp --files "
        "--files-with-matches --files-without-match --fixed-strings --free-space "
        "--glob-ignore-case --heading --help --hex --hidden --ignore-binary --ignore-case "
        "--index --initial-tab --invert-match --json --line-buffered --line-number "
        "--line-regexp --lines --match --no-config --no-confirm --no-dereference "
        "--no-filename --no-group-separator --no-ignore-files --no-messages --null "
        "--null-data --only-line-number --only-matching --passthru --perl-regexp --quiet "
        "--recursive --silent --smart-case --split --stats --text --tree --ungroup "
        "--version --with-filename --with-hex --word-regexp --xml"
    ),
    pattern_short="efN",
    pattern_long=_names("--regexp --file --and --andnot --not --neg-regexp"),
    abbreviates=False,
)

_RG: Final = _Table(
    value_short="ABCEMTdefgjmrt",
    optional_short="",
    flag_short=".0FHILNPSUVabchilnopqsuvwxz",
    value_long=_names(
        "--after-context --before-context --color --colors --context --context-separator "
        "--dfa-size-limit --encoding --engine --field-context-separator "
        "--field-match-separator --file --generate --glob --hostname-bin "
        "--hyperlink-format --iglob --ignore-file --max-columns --max-count --max-depth "
        "--max-filesize --path-separator --pre --pre-glob --regex-size-limit --regexp "
        "--replace --sort --sortr --threads --type --type-add --type-clear --type-not"
    ),
    optional_long=frozenset(),
    flag_long=_names(
        "--auto-hybrid-regex --binary --block-buffered --byte-offset --case-sensitive "
        "--column --count --count-matches --crlf --debug --files --files-with-matches "
        "--files-without-match --fixed-strings --follow --glob-case-insensitive "
        "--heading --help --hidden --ignore-case --ignore-file-case-insensitive "
        "--include-zero --invert-match --json --line-buffered --line-number --line-regexp "
        "--max-columns-preview --mmap --multiline --multiline-dotall --no-config "
        "--no-filename --no-ignore --no-ignore-dot --no-ignore-exclude --no-ignore-files "
        "--no-ignore-global --no-ignore-messages --no-ignore-parent --no-ignore-vcs "
        "--no-line-number --no-messages --no-pcre2-unicode --no-require-git --no-unicode "
        "--null --null-data --one-file-system --only-matching --passthru --pcre2 "
        "--pcre2-version --pretty --quiet --search-zip --smart-case --sort-files --stats "
        "--stop-on-nonmatch --text --trace --trim --type-list --unrestricted --version "
        "--vimgrep --with-filename --word-regexp"
    ),
    pattern_short="ef",
    # --files lists files and takes no pattern, so no operand is one.
    pattern_long=_names("--regexp --file --files"),
    abbreviates=False,
)

_GIT: Final = _Table(
    value_short="ABCefm",
    optional_short="O",
    flag_short="EFGHILPWachilnopqrvwz" + _DIGITS,
    value_long=_names(
        "--after-context --before-context --context --max-count --max-depth "
        "--no-after-context --no-before-context --no-context --no-max-count --no-threads "
        "--threads"
    ),
    optional_long=_names("--color --no-color --no-open-files-in-pager --open-files-in-pager"),
    flag_long=_names(
        "--all-match --and --basic-regexp --break --cached --column --count "
        "--exclude-standard --ext-grep --extended-regexp --files-with-matches "
        "--files-without-match --fixed-strings --full-name --function-context --heading "
        "--ignore-case --index --invert-match --line-number --name-only --no-all-match "
        "--no-basic-regexp --no-break --no-cached --no-column --no-count "
        "--no-exclude-standard --no-ext-grep --no-extended-regexp --no-files-with-matches "
        "--no-files-without-match --no-fixed-strings --no-full-name --no-function-context "
        "--no-heading --no-ignore-case --no-index --no-invert-match --no-line-number "
        "--no-name-only --no-null --no-only-matching --no-perl-regexp --no-quiet "
        "--no-recurse-submodules --no-recursive --no-show-function --no-text "
        "--no-textconv --no-untracked --no-word-regexp --not --null --only-matching --or "
        "--perl-regexp --quiet --recurse-submodules --recursive --show-function --text "
        "--textconv --untracked --word-regexp"
    ),
    pattern_short="ef",
    pattern_long=frozenset(),
    abbreviates=True,
)


def _agree(arities: Sequence[Arity]) -> Arity:
    """The one arity every reading agrees on; a flag read as optional by one is optional."""
    kinds = set(arities)
    if len(kinds) == 1:
        return kinds.pop()
    if kinds == {Arity.FLAG, Arity.OPTIONAL}:
        return Arity.OPTIONAL
    return Arity.UNKNOWN


@dataclass(frozen=True)
class ToolGrammar:
    """The grammar of one command word, over one or more binaries' tables.

    ``intersect`` demands that EVERY table knows an option and reads it alike
    (``ag``/``ack``, whose own tables are not carried); otherwise the tables
    that know it must agree. ``overrides`` pin options the tables misjudge.
    ``always_uncertain`` marks a tool that reads a config file of its own.
    """

    tables: tuple[_Table, ...]
    intersect: bool = False
    always_uncertain: bool = False
    short_overrides: dict[str, Arity] = field(default_factory=dict)
    long_overrides: dict[str, Arity] = field(default_factory=dict)

    def short(self, letter: str) -> Arity:
        """Arity of ``-letter``."""
        if letter in self.short_overrides:
            return self.short_overrides[letter]
        return self._combine([table.short(letter) for table in self.tables])

    def long(self, name: str) -> LongOption:
        """Arity and full name of the long option ``name`` (abbreviations resolved)."""
        found = [table.long(name) for table in self.tables]
        known = [option for option in found if option.arity is not Arity.UNKNOWN]
        if len({option.name for option in known}) > 1:
            return _UNKNOWN_LONG
        arity = self._combine([option.arity for option in found])
        if arity is Arity.UNKNOWN:
            return _UNKNOWN_LONG
        full = known[0].name
        override = self.long_overrides.get(full or "")
        return _UNKNOWN_LONG if override is Arity.UNKNOWN else LongOption(arity, full)

    def supplies_pattern(self, option: str) -> bool:
        """Whether the option (``-e``, ``--regexp``; full name) gives the pattern."""
        if option.startswith("--"):
            return any(option in table.pattern_long for table in self.tables)
        return any(option[1:] in table.pattern_short for table in self.tables)

    def _combine(self, arities: list[Arity]) -> Arity:
        known = [arity for arity in arities if arity is not Arity.UNKNOWN]
        if not known or (self.intersect and len(known) != len(arities)):
            return Arity.UNKNOWN
        return _agree(known)


_GREP_TABLES: Final = (_GNU, _UGREP)
_GRAMMARS: Final[dict[str, ToolGrammar]] = {
    "grep": ToolGrammar(_GREP_TABLES),
    "egrep": ToolGrammar((_GNU,)),
    "fgrep": ToolGrammar((_GNU,)),
    "zgrep": ToolGrammar((_GNU,)),
    "ugrep": ToolGrammar((_UGREP,)),
    # ug reads a .ugrep configuration, so no option list can be trusted.
    "ug": ToolGrammar((_UGREP,), always_uncertain=True),
    "rg": ToolGrammar((_RG,)),
    # Their own tables are not carried: only what grep, ugrep and rg agree on is trusted.
    # -r/-R recurse in both; -A/-B/-C and --context take an optional count in ag;
    # -u/-U/-S/-s/-Q/-a/-t/-z are flags there (not in every one of the tables).
    "ag": ToolGrammar(
        (_GNU, _UGREP, _RG),
        intersect=True,
        short_overrides={
            **dict.fromkeys("rRuUSsQatz", Arity.FLAG),
            "A": Arity.UNKNOWN,
            "B": Arity.UNKNOWN,
            "C": Arity.UNKNOWN,
        },
        long_overrides={
            "--after-context": Arity.UNKNOWN,
            "--before-context": Arity.UNKNOWN,
            "--context": Arity.UNKNOWN,
        },
    ),
    "git": ToolGrammar((_GIT,)),
}
_GRAMMARS["ack"] = _GRAMMARS["ag"]
_GIT_GREP_KEY: Final = "git"


#: ripgrep reads extra arguments, patterns included, from the file this variable names.
RG_CONFIG_ENV: Final = "RIPGREP_CONFIG_PATH"
_RG_NAME: Final = "rg"


def grammar_for(command: str, *, git_grep: bool = False, rg_config: bool = False) -> ToolGrammar:
    """The grammar of the search command word ``command`` (``rg``, ``/usr/bin/grep``).

    An empty or unrecognised word is read as ``grep``, which is judged against
    both binaries it can be. ``rg_config`` says the command line names
    :data:`RG_CONFIG_ENV`, so what ``rg`` is given cannot be told from its words.
    """
    if git_grep:
        return _GRAMMARS[_GIT_GREP_KEY]
    name = command.rsplit("/", 1)[-1]
    grammar = _GRAMMARS.get(name, _GRAMMARS["grep"])
    return replace(grammar, always_uncertain=True) if rg_config and name == _RG_NAME else grammar


@dataclass
class ParsedArguments:
    """What a search command's arguments say, by argument position.

    ``operands`` are indexes into the parsed list (the pattern, when given as an
    operand, is the first of them). ``maybe_consumed`` counts words an unplaced
    option might have taken as its value, so up to that many operands may not be.
    """

    operands: list[int] = field(default_factory=list)
    values: list[tuple[str, str]] = field(default_factory=list)
    pattern_supplied: bool = False
    uncertain: bool = False
    maybe_consumed: int = 0
    recursive: bool = False


def parse_arguments(grammar: ToolGrammar, arguments: list[str]) -> ParsedArguments:
    """Read ``arguments`` with ``grammar``; whatever it cannot place makes the parse uncertain."""
    parsed = ParsedArguments(uncertain=grammar.always_uncertain, recursive=grammar.always_uncertain)
    pending: str | None = None
    options_ended = False
    for position, word in enumerate(arguments):
        if pending is not None:
            parsed.values.append((pending, word))
            pending = None
        elif options_ended or not word.startswith("-") or word == "-":
            parsed.operands.append(position)
        elif word == _END_OF_OPTIONS:
            options_ended = True
        elif word.startswith("--"):
            pending = _read_long(grammar, word, parsed)
        else:
            pending = _read_cluster(grammar, word[1:], parsed)
    return parsed


def _read_long(grammar: ToolGrammar, word: str, parsed: ParsedArguments) -> str | None:
    """Record a ``--name[=value]`` word; the option still awaiting its value, if any."""
    name, has_value, value = word.partition("=")
    option = grammar.long(name)
    if option.arity is Arity.UNKNOWN or option.name is None:
        # Possibly an abbreviation of --recursive, and possibly a value-taking option.
        parsed.uncertain = True
        parsed.recursive = True
        parsed.maybe_consumed += 0 if has_value else 1
        return None
    parsed.recursive = parsed.recursive or option.name in _RECURSIVE_LONG
    if grammar.supplies_pattern(option.name):
        parsed.pattern_supplied = True
    if option.arity is not Arity.VALUE:
        return None
    if has_value:
        parsed.values.append((option.name, value))
        return None
    return option.name


def _read_cluster(grammar: ToolGrammar, cluster: str, parsed: ParsedArguments) -> str | None:
    """Record a ``-abc`` word; the option still awaiting its value, if any."""
    for offset, letter in enumerate(cluster):
        arity = grammar.short(letter)
        last = offset == len(cluster) - 1
        if letter in _RECURSIVE_SHORT and arity is not Arity.VALUE:
            parsed.recursive = True
        if arity is Arity.VALUE:
            if grammar.supplies_pattern(f"-{letter}"):
                parsed.pattern_supplied = True
            attached = cluster[offset + 1 :]
            if attached:
                parsed.values.append((f"-{letter}", attached))
                return None
            return f"-{letter}"
        if arity is Arity.UNKNOWN:
            parsed.uncertain = True
            parsed.maybe_consumed += 1 if last else 0
        elif arity is Arity.OPTIONAL and not last:
            # ugrep reads the rest of the cluster as the value, GNU grep as more flags.
            parsed.uncertain = True
    return None

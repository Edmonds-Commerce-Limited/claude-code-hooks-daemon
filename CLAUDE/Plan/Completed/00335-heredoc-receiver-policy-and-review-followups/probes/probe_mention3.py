"""Does the positional fix still serve the case c8ce2d7a existed for?

Uses a SUBSTRING-style glob (the shape of the shipped default) so a dotted
module path containing the stem matches the way the real one did.
"""

from claude_code_hooks_daemon.utils import secret_file_matching as sfm

PATTERNS = ("*.privkey*",)

CASES = {
    "import of a module whose path contains the stem": (
        "python3 -c 'import pkg.handlers.pre_tool_use.privkey_guard'",
        None,
    ),
    "from-import of that module": (
        "from pkg.handlers.pre_tool_use.privkey_guard import Handler",
        None,
    ),
    "multi-line parenthesised from-import": (
        "from pkg.handlers.pre_tool_use import (\n    privkey_guard,\n)",
        None,
    ),
    "prose mention of the dotted path (no import)": (
        "grep -rn pkg.handlers.privkey_guard src",
        "*.privkey*",
    ),
    "import PLUS a prose mention of the same path": (
        "from pkg.handlers.privkey_guard import X\n# see pkg.handlers.privkey_guard",
        "*.privkey*",
    ),
    "real file read still caught": ("cat mykeys.privkey", "*.privkey*"),
}

for label, (cmd, expected) in CASES.items():
    found = sfm.find_protected_mention(cmd, PATTERNS)
    verdict = "as expected" if found == expected else f"UNEXPECTED (got {found!r})"
    print(f"  {found!r:14} | {verdict:30} | {label}")

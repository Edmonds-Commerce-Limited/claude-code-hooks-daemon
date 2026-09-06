from claude_code_hooks_daemon.utils import secret_file_matching as sfm

PATTERNS = ("*.privkey", "**/*.privkey")

cases = {
    "plain read": "cat mykeys.privkey",
    "laundered via fake import line": "import mykeys.privkey\ncat mykeys.privkey",
    "laundered from-line": "from mykeys.privkey import x\ncat mykeys.privkey",
    "laundered same line": "import mykeys.privkey; cat mykeys.privkey",
    "leading whitespace import": "  import mykeys.privkey\ncat mykeys.privkey",
}

for label, cmd in cases.items():
    found = sfm.find_protected_mention(cmd, PATTERNS)
    print(f"{'MENTION' if found else 'MISSED '} | {label} | {found!r}")

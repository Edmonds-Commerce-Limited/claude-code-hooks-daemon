"""Adversarial re-test of the positional import exemption (B1 fix)."""

from claude_code_hooks_daemon.utils import secret_file_matching as sfm

PATTERNS = ("*.privkey", "**/*.privkey")

MUST_DETECT = {
    "plain read": "cat mykeys.privkey",
    "orig laundering 1 (newline)": "import mykeys.privkey\ncat mykeys.privkey",
    "orig laundering 2 (from)": "from mykeys.privkey import x\ncat mykeys.privkey",
    "orig laundering 3 (semicolon)": "import mykeys.privkey; cat mykeys.privkey",
    "orig laundering 4 (indent)": "  import mykeys.privkey\ncat mykeys.privkey",
    "tab after import": "import\tmykeys.privkey\ncat mykeys.privkey",
    "double space": "import  mykeys.privkey\ncat mykeys.privkey",
    "disclosure BEFORE import": "cat mykeys.privkey\nimport mykeys.privkey",
    "import is a PREFIX of token": "import mykeys\ncat mykeys.privkey",
    "many imports": "import a\nimport mykeys.privkey\nimport b\ncat mykeys.privkey",
    "import then && on same line": "import mykeys.privkey && cat mykeys.privkey",
    "import then pipe": "import mykeys.privkey | cat mykeys.privkey",
    "CRLF-ish line start": "import mykeys.privkey\r\ncat mykeys.privkey",
    "import inside quotes, real read after": "echo 'import mykeys.privkey'\ncat mykeys.privkey",
    "trailing-dot module then read": "import mykeys.privkey.\ncat mykeys.privkey",
    "subdir path read": "import mykeys.privkey\ncat sub/dir/mykeys.privkey",
    "glob-shaped read": "import mykeys.privkey\ncat *.privkey",
    "redirect read": "import mykeys.privkey\nwhile read l; do :; done < mykeys.privkey",
}

MUST_ALLOW = {
    "bare module import (the motivating case)": "python3 -c 'import pkg.sub.thing'",
    "from-import of a module": "from pkg.sub.thing import Widget",
    "import ... as": "import pkg.sub.thing as t",
    "no protected token at all": "cat README.md",
}

print("== must DETECT (a miss is a bypass) ==")
bad = 0
for label, cmd in MUST_DETECT.items():
    found = sfm.find_protected_mention(cmd, PATTERNS)
    ok = found is not None
    bad += 0 if ok else 1
    print(f"  {'MENTION' if ok else 'MISSED ':7} | {label}")

print("== must ALLOW (a hit is a false positive) ==")
for label, cmd in MUST_ALLOW.items():
    found = sfm.find_protected_mention(cmd, PATTERNS)
    ok = found is None
    bad += 0 if ok else 1
    print(f"  {'clean  ' if ok else 'FALSEPOS':7} | {label} -> {found!r}")

print(f"\nfailures: {bad}")

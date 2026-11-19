"""Compare one corpus tag across modes: python cmp2.py <tag>."""

import json
import sys
from pathlib import Path

R = Path(__file__).resolve().parent
tag = sys.argv[1]
modes = [
    "branch-cap-built",
    "branch-lifted-built",
    "branch-lifted-cold",
    "branch-cap-cold",
    "parent-cap-built",
    "parent-lifted-built",
    "main-lifted-cold",
]
d = {
    m: {
        r["command"]: r["decision"][:5] for r in json.loads((R / f"out-{tag}-{m}.json").read_text())
    }
    for m in modes
}
cmds = list(d[modes[0]])
print("modes:", " ".join(m.replace("-built", "B").replace("-cold", "C") for m in modes))
for c in cmds:
    row = [d[m][c] for m in modes]
    if any(v != "deny" for v in row[:4]) or (row[4] == "deny" and row[0] != "deny"):
        print(" ".join(f"{v:5}" for v in row), "|", c.replace("\n", "<NL>"))
reg_main = [
    c
    for c in cmds
    if d["main-lifted-cold"][c] == "deny" and any(d[m][c] != "deny" for m in modes[:4])
]
reg_parent = [
    c for c in cmds if d["parent-cap-built"][c] == "deny" and d["branch-cap-built"][c] != "deny"
]
print("DENY main -> ALLOW branch:", reg_main)
print("DENY parent(cap) -> ALLOW branch(cap):", reg_parent)

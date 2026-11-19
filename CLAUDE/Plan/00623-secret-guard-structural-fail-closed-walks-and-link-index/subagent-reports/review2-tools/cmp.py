import json


def ld(n):
    return {r["command"]: r["decision"] for r in json.load(open(n))}


cap = ld("out-branch-cap-built.json")
lifted = ld("out-branch-lifted-built.json")
cold = ld("out-branch-cap-cold.json")
main = ld("out-main-lifted-cold.json")
for k in cap:
    if cap[k] != "deny" or lifted[k] != cap[k] or cold[k] != cap[k]:
        print(f"cap={cap[k]:6} lifted={lifted[k]:6} cold={cold[k]:6} main={main[k]:6} | {k}")
print("main deny:", [k for k in main if main[k] == "deny"])
print(
    "main-deny->branch-allow",
    [
        k
        for k in main
        if main[k] == "deny" and (cap[k] != "deny" or cold[k] != "deny" or lifted[k] != "deny")
    ],
)

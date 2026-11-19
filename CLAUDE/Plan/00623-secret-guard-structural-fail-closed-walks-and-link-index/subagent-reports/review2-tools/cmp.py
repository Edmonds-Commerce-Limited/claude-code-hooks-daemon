import json, sys
def ld(n): return {r['command']:r['decision'] for r in json.load(open(n))}
a=ld('out-branch-cap-built.json'); l=ld('out-branch-lifted-built.json'); c=ld('out-branch-cap-cold.json'); m=ld('out-main-lifted-cold.json')
for k in a:
  if a[k]!='deny' or l[k]!=a[k] or c[k]!=a[k]: print(f'cap={a[k]:6} lifted={l[k]:6} cold={c[k]:6} main={m[k]:6} | {k}')
print('main deny:',[k for k in m if m[k]=='deny'])
print('main-deny->branch-allow', [k for k in m if m[k]=='deny' and (a[k]!='deny' or c[k]!='deny' or l[k]!='deny')])

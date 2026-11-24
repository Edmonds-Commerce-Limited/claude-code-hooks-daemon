import sys; sys.path.insert(0,sys.argv[1]+"/src")
from datetime import datetime, UTC
from claude_code_hooks_daemon.utils.ci_state import read_ci_output as r, ci_commands as c
now=datetime(2026,11,24,12,0,tzinfo=UTC)
def t(name,s,**k):
    try: print(name, r(s,now=now,stuck_after_seconds=1800,**k))
    except BaseException as e: print(name,"RAISED",type(e).__name__, str(e)[:80])
t("deep","["*100000)
t("deepvalid","["*5000+"]"*5000)
t("minyear",'[{"status":"queued","startedAt":"0001-01-01T00:00:00+01:00"}]')
t("zero",'[{"status":"queued","startedAt":"0001-01-01T00:00:00Z","createdAt":"2026-11-24T11:55:00Z"}]')
t("maxyear",'[{"status":"queued","startedAt":"9999-12-31T23:59:59-01:00"}]')
t("bigint",'[{"status":"queued","databaseId":'+"9"*5000+'}]')
t("nested_name",'[{"status":"queued","workflowName":'+"["*900+"]"*900+',"createdAt":"2026-11-24T11:55:00Z"}]')
t("bucketlist",'[{"bucket":"pending","name":{"a":1}}]')
t("row_zone_less","queued\t\tt\tCI\tmain\tpush\t1\t1m\t2026-11-24T11:00:00")
t("row_tab_bucket","foo\tpending\n")
t("UPPER",'[{"status":"QUEUED","createdAt":"2026-11-24T10:00:00Z"}]')
t("future",'[{"status":"queued","startedAt":"2027-01-01T00:00:00Z","createdAt":"2026-11-24T10:00:00Z"}]')
for cmd in ["gh run list --jq .","gh run list -q.","gh pr checks 1 --json bucket,name --jq=.","gh -R o/r run list","GH_TOKEN=x gh run list","gh run view 1 --json=status","sudo gh run list","env gh run list","gh run list --template='{{.}}'"]:
    try: print(repr(cmd), c(cmd))
    except BaseException as e: print(repr(cmd),"RAISED",type(e).__name__)

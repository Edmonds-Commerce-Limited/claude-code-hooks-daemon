"""Probe: old host <-> new worker codec and state round-trip."""
import importlib.util, sys
from pathlib import Path
def load(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s)
    sys.modules[name] = m; s.loader.exec_module(m); return m
new = load("new", "/workspace/untracked/worktrees/worktree-p487-supervisor-plugins/.claude/ccy/claude-supervise.py")
old = load("old", "/workspace/untracked/scratch/p487-probe/old_sup.py")
nm = new.CompactStateMachine(new.CompactPolicy())
nm.arm_plugin_notice("x", "exception", "on_idle")
om = old.CompactStateMachine(old.CompactPolicy())
om.import_state(nm.export_state()); print("old host imports new worker state: ok")
nm2 = new.CompactStateMachine(new.CompactPolicy()); nm2.import_state(om.export_state()); print("new worker imports old host state: ok; pending", nm2.plugin_notices_pending)
o = new.TickOutcome(decision_value="noop", reason="r", payload=None, submit=True, consume_signal_path=None, deferred_log=None, machine_state=nm.export_state(), exit_for_restart=("x","y"))
print("old host decodes new outcome:", old._outcome_from_json(new._outcome_to_json(o)).decision_value)
print("new worker plugin flags from old-host argv:", new._parse_worker_plugin_flags(["--worker","--arm"]))
oo = old.TickOutcome(decision_value="noop", reason="r", payload=None, submit=True, consume_signal_path=None, deferred_log=None, machine_state=None)
print("new host decodes old outcome:", new._outcome_from_json(old._outcome_to_json(oo)).plugin_failures)

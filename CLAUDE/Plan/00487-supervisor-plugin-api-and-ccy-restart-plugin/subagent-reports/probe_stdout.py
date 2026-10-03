"""Probe: a plugin print() reaches the worker's protocol stdout, and a
JSON-scalar line there makes the HOST's decode raise an uncaught AttributeError."""
import contextlib, importlib.util, io, os, sys, tempfile
from pathlib import Path

SUP = Path("/workspace/untracked/worktrees/worktree-p487-supervisor-plugins/.claude/ccy/claude-supervise.py")
spec = importlib.util.spec_from_file_location("sup", SUP)
sup = importlib.util.module_from_spec(spec); sys.modules["sup"] = sup; spec.loader.exec_module(sup)

work = Path(tempfile.mkdtemp(dir="/workspace/untracked/scratch/p487-probe"))
os.chmod(work, 0o755)
plugin = work / "noisy.py"
plugin.write_text(
    "PLUGIN_API = 1\n"
    "class H:\n"
    "    name='noisy'; version='1'\n"
    "    def on_start(self): pass\n"
    "    def on_idle(self, tick):\n"
    "        print(42)\n"
    "        return None\n"
    "def create_worker_half(api): return H()\n")
os.chmod(plugin, 0o644)
rt = sup.PluginRuntime(state_root=work/"state", status_dir=work/"u", marker_path=work/"m.json")
rt.load([("noisy", plugin)], frozenset())
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rt.run_idle(0.0)
print("plugin wrote to worker stdout:", repr(buf.getvalue()), "failures:", rt.failures)
try:
    sup._outcome_from_json(buf.getvalue())
except (ValueError, KeyError) as e:
    print("caught by PolicyWorker.decide:", type(e).__name__)
except Exception as e:
    print("ESCAPES PolicyWorker.decide (only ValueError/KeyError caught):", type(e).__name__, e)

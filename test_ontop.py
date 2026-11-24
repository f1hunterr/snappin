"""Live test: 'always on top' is applied, and removed when switched off."""
import subprocess, sys, time, os
sys.argv = [sys.argv[0], "--no-admin"]
import snappin as s

ms = s.get_monitors(); dev, _ = ms[0]
f = os.path.join(os.environ["TEMP"], "snappin-top.txt"); open(f, "a").close()
p = subprocess.Popen(["notepad.exe", f]); time.sleep(3)
h, exe, _t = [w for w in s.list_windows() if "snappin-top" in w[2]][0]
rule = {"exe": exe, "title": "snappin-top", "top": True}
cfg = {"enabled": True, "monitors": {dev: {"layout": "Halves", "zones": {"1": rule}}}}
is_top = lambda: bool(s.user32.GetWindowLongW(h, s.GWL_EXSTYLE) & s.WS_EX_TOPMOST)
assert not is_top()
for _ in range(3): s.enforce(cfg, ms); time.sleep(.2)
print("on top after enforce:", is_top()); assert is_top()
rule["top"] = False
for _ in range(3): s.enforce(cfg, ms); time.sleep(.2)
print("on top after switching off:", is_top()); assert not is_top()
rule["top"] = True; s.enforce(cfg, ms); assert is_top()
cfg["monitors"][dev]["zones"] = {}          # unpinned entirely
s.enforce(cfg, ms)
print("on top after unpin:", is_top()); assert not is_top()
p.kill(); print("ALL OK")

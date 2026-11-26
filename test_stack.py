"""Live test: two apps share one zone; both sit in it, cycling switches the
front app, an old single-rule config is migrated, strip room is reserved."""
import json, os, subprocess, sys, tempfile, time
sys.argv = [sys.argv[0], "--no-admin"]
import snappin as s

ms = s.get_monitors(); dev, work = ms[0]
tmp = os.environ["TEMP"]
helper = os.path.join(tmp, "stackwin.py")
open(helper, "w").write("import sys, tkinter as tk\nr = tk.Tk(); r.title(sys.argv[1]); r.geometry('500x400+200+200'); r.mainloop()\n")
pa = subprocess.Popen([sys.executable, helper, "snappin-stack-a"]); time.sleep(1.5)
pb = subprocess.Popen([sys.executable, helper, "snappin-stack-b"]); time.sleep(2)
ws = s.list_windows()
wa = [w for w in ws if "snappin-stack-a" in w[2]][0]
wb = [w for w in ws if "snappin-stack-b" in w[2]][0]
import atexit
atexit.register(lambda: [p.kill() for p in (pa, pb)])   # never leave helpers
ra = {"exe": wa[1], "title": "snappin-stack-a"}
rb = {"exe": wb[1], "title": "snappin-stack-b"}

# 1. old config format (single rule per zone) is migrated to a list
old = {"enabled": True, "monitors": {dev: {"layout": "Halves", "zones": {"1": ra}}}}
p = os.path.join(tmp, "snappin-old.json"); json.dump(old, open(p, "w"))
mig = s.load_config(p)
assert mig["monitors"][dev]["zones"]["1"] == [ra], mig
print("old config migrated: ok")

# 2. both apps in the same zone end up in the same rectangle
cfg = {"enabled": True, "tabstrip": False, "monitors": {dev: {
    "layout": "Halves", "zones": {"1": [ra, rb]}}}}
tx, ty, tw, th = s.zone_rect(work, s.LAYOUTS["Halves"][1])
def settle(n=8):
    for _ in range(n): s.enforce(cfg, ms); time.sleep(.3)
def geom(h):
    l, t, r, b = s.frame_rect(h); return (l, t, r - l, b - t)
settle()
for w in (wa, wb):
    g = geom(w[0]); print("stack member:", g)
    assert all(abs(a - b) <= 2 for a, b in zip(g, (tx, ty, tw, th)))

# 3. arrange puts the FIRST app in front; cycling switches to the other
s.arrange_stacks(cfg, ms); time.sleep(.3)
st = s.zone_stack(cfg, ms, 0, 1)
assert [o for _, o in st] == [0, 1], st
assert s.front_of(st)[1] == 0, "first app should start in front"
print("first app in front: ok")
h = s.cycle_zone(cfg, ms, 1, zone=(0, 1)); time.sleep(.4)
assert h == wb[0] and s.front_of(st)[1] == 1; print("cycle -> second app: ok")
h = s.cycle_zone(cfg, ms, 1, zone=(0, 1)); time.sleep(.4)
assert h == wa[0] and s.front_of(st)[1] == 0; print("cycle wraps -> first app: ok")

# 4. tab strip on: windows move down by the strip height, same size for both
cfg["tabstrip"] = True; settle()
for w in (wa, wb):
    g = geom(w[0]); print("with strip:", g)
    assert abs(g[1] - (ty + s.STRIP_H)) <= 2 and abs(g[3] - (th - s.STRIP_H)) <= 2
assert s._zone_full[(0, 1)] == (tx, ty, tw, th)
pa.kill(); pb.kill(); print("ALL OK")

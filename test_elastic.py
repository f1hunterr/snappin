"""Live test: an app with a minimum width (700) pinned into a 640-wide zone
must not overlap the neighbouring zone's app; the boundary should shift."""
import subprocess, sys, time, os, textwrap
sys.argv = [sys.argv[0], "--no-admin"]
import snappin as s

helper = os.path.join(os.environ["TEMP"], "minwin.py")
open(helper, "w").write(textwrap.dedent("""
    import tkinter as tk
    r = tk.Tk(); r.title("snappin-minwin"); r.minsize(700, 300)
    r.geometry("700x300+100+100"); r.mainloop()
"""))
dev, work = s.get_monitors()[0]
ms = s.get_monitors()
f = os.path.join(os.environ["TEMP"], "snappin-neighbour.txt"); open(f, "a").close()
p1 = subprocess.Popen([sys.executable, helper])
p2 = subprocess.Popen(["notepad.exe", f])
time.sleep(3)
ws = s.list_windows()
w1 = [w for w in ws if "snappin-minwin" in w[2]][0]
w2 = [w for w in ws if "snappin-neighbour" in w[2]][0]
cfg = {"enabled": True, "monitors": {dev: {"layout": "Thirds", "zones": {
    "0": {"exe": w1[1], "title": "snappin-minwin"},
    "1": {"exe": w2[1], "title": "snappin-neighbour"}}}}}
for _ in range(14):
    s.enforce(cfg, ms); time.sleep(.3)
a, b = s.frame_rect(w1[0]), s.frame_rect(w2[0])
print("minwin   :", a, "width", a[2] - a[0])
print("neighbour:", b, "width", b[2] - b[0])
print("need learned:", s._need.get(w1[0]))
overlap = a[2] > b[0] + 2
print("OVERLAP" if overlap else "no overlap")
p1.kill(); p2.kill()
assert not overlap and a[2] - a[0] >= 698
print("ALL OK")

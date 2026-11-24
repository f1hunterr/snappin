"""Live test: pin Notepad to the right half, drag it away, minimize, close/reopen."""
import subprocess, sys, time, os
sys.argv = [sys.argv[0], "--no-admin"]
import snappin as s

mons = s.get_monitors()
dev, work = mons[0]
print("monitor", dev, work)
zones = s.LAYOUTS["Halves"]
tx, ty, tw, th = s.zone_rect(work, zones[1])
print("target", tx, ty, tw, th)
assert s.zone_rect(work, zones[0])[0] + s.zone_rect(work, zones[0])[2] == tx  # no gap

notepad = r"C:\Windows\System32\notepad.exe"
cfg = {"enabled": True, "monitors": {dev: {"layout": "Halves",
       "zones": {"1": {"exe": "", "title": "snappin-test"}}}}}


def find():
    return [w for w in s.list_windows() if "snappin-test" in w[2]]


def open_np():
    f = os.path.join(os.environ["TEMP"], "snappin-test.txt")
    open(f, "a").close()
    p = subprocess.Popen(["notepad.exe", f])
    for _ in range(40):
        time.sleep(.25)
        w = find()
        if w:
            return p, w[0]
    raise SystemExit("notepad window not found")


def settle(h):
    for _ in range(10):
        s.enforce(cfg, mons)
        time.sleep(.3)
    fl, ft, fr, fb = s.frame_rect(h)
    return (fl, ft, fr - fl, fb - ft)

p, (h, exe, title) = open_np()
cfg["monitors"][dev]["zones"]["1"]["exe"] = exe
print("exe", exe)
got = settle(h); print("pinned:", got); assert all(abs(a - b) <= 2 for a, b in zip(got, (tx, ty, tw, th)))

s.user32.SetWindowPos(h, None, 50, 50, 400, 300, 0x14)
got = settle(h); print("after drag:", got); assert all(abs(a - b) <= 2 for a, b in zip(got, (tx, ty, tw, th)))

s.user32.ShowWindow(h, 6)  # minimize
s.enforce(cfg, mons); assert s.user32.IsIconic(h), "must stay minimized"
s.user32.ShowWindow(h, 9)  # restore
s.user32.SetWindowPos(h, None, 10, 10, 300, 300, 0x14)
got = settle(h); print("after restore:", got); assert all(abs(a - b) <= 2 for a, b in zip(got, (tx, ty, tw, th)))

p.kill(); time.sleep(1)
p, (h2, _, _) = open_np()
got = settle(h2); print("after reopen:", got); assert all(abs(a - b) <= 2 for a, b in zip(got, (tx, ty, tw, th)))
p.kill()
print("ALL OK")

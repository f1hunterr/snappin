"""SnapPin - assign apps to snap-layout zones and keep them there.

Pure stdlib (ctypes + tkinter). Run with run.bat (auto-elevates so it can
move admin apps too).
"""
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

# ---------------------------------------------------------------- win32 ----
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
dwmapi = ctypes.windll.dwmapi
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor, physical px
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x80
GW_OWNER = 4
SW_RESTORE = 9
SWP_NOZORDER, SWP_NOACTIVATE = 0x4, 0x10
DWMWA_CLOAKED, DWMWA_EXTENDED_FRAME_BOUNDS = 14, 9
PROCESS_QUERY_LIMITED = 0x1000
VK_LBUTTON, VK_CONTROL, VK_MENU, VK_P = 0x01, 0x11, 0x12, 0x50

user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                wintypes.UINT]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                            ctypes.POINTER(wintypes.DWORD)]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                         ctypes.c_void_p, wintypes.DWORD]


class MONITORINFOEX(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32)]


def get_monitors():
    """[(device_name, (x, y, w, h) of work area)] - primary first."""
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    def cb(hmon, hdc, rc, lp):
        mi = MONITORINFOEX()
        mi.cbSize = ctypes.sizeof(mi)
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        w = mi.rcWork
        out.append((mi.dwFlags & 1, mi.szDevice,
                    (w.left, w.top, w.right - w.left, w.bottom - w.top)))
        return True

    user32.EnumDisplayMonitors(None, None, cb, 0)
    out.sort(key=lambda m: -m[0])
    return [(n, r) for _, n, r in out]


def monitor_details():
    """Measured facts per monitor, same order as get_monitors():
    [{'name','full':(x,y,w,h),'work':(x,y,w,h),'scale':percent}]"""
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    def cb(hmon, hdc, rc, lp):
        mi = MONITORINFOEX()
        mi.cbSize = ctypes.sizeof(mi)
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        f, w = mi.rcMonitor, mi.rcWork
        dx, dy = ctypes.c_uint(96), ctypes.c_uint(96)
        try:
            ctypes.windll.shcore.GetDpiForMonitor(
                hmon, 0, ctypes.byref(dx), ctypes.byref(dy))
        except Exception:
            pass
        out.append((mi.dwFlags & 1, {
            "name": mi.szDevice,
            "full": (f.left, f.top, f.right - f.left, f.bottom - f.top),
            "work": (w.left, w.top, w.right - w.left, w.bottom - w.top),
            "scale": round(dx.value * 100 / 96)}))
        return True

    user32.EnumDisplayMonitors(None, None, cb, 0)
    out.sort(key=lambda m: -m[0])
    return [d for _, d in out]


def describe_monitor(d):
    fx, fy, fw, fh = d["full"]
    wx, wy, ww, wh = d["work"]
    return (f"Screen {fw} x {fh} px at ({fx}, {fy}), scale {d['scale']}%.  "
            f"Usable area {ww} x {wh} px"
            + (f" (taskbar takes {fh - wh} px)" if fh != wh else "")
            + (f" (taskbar takes {fw - ww} px wide)" if fw != ww else ""))


def exe_of(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(h)


def title_of(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def real_uwp_exe(frame_hwnd):
    """Store apps live inside ApplicationFrameHost; the real app is a child
    CoreWindow owned by another process. Return that process's exe."""
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(child, lp):
        pid_f, pid_c = wintypes.DWORD(), wintypes.DWORD()
        user32.GetWindowThreadProcessId(frame_hwnd, ctypes.byref(pid_f))
        user32.GetWindowThreadProcessId(child, ctypes.byref(pid_c))
        if pid_c.value != pid_f.value:
            e = exe_of(child)
            if e:
                found.append(e)
                return False
        return True

    user32.EnumChildWindows(frame_hwnd, cb, 0)
    return found[0] if found else ""


def monitor_of(hwnd, monitors):
    """Index of the monitor containing the window's centre."""
    l, t, r, b = frame_rect(hwnd)
    cx, cy = (l + r) // 2, (t + b) // 2
    for i, (_, (x, y, w, h)) in enumerate(monitors):
        if x <= cx < x + w and y <= cy < y + h:
            return i
    return 0


def zone_at(work, layout, cx, cy):
    """Zone index whose rect contains (cx,cy), else nearest zone centre."""
    best, bd = 0, None
    for i, fr in enumerate(LAYOUTS[layout]):
        x, y, w, h = zone_rect(work, fr)
        if x <= cx < x + w and y <= cy < y + h:
            return i
        d = (cx - (x + w / 2)) ** 2 + (cy - (y + h / 2)) ** 2
        if bd is None or d < bd:
            best, bd = i, d
    return best


def pin_all_open(cfg, monitors, skip_hwnd=0):
    """Assign every open window to the zone it currently sits in.
    One app per zone: the first window found for a zone wins, and zones
    that already have an app are left alone. Returns number assigned."""
    n = 0
    for hwnd, exe, title in list_windows(skip_hwnd):
        if user32.IsIconic(hwnd):
            continue
        mi = monitor_of(hwnd, monitors)
        dev, work = monitors[mi]
        m = cfg["monitors"].setdefault(dev, {"layout": "Halves", "zones": {}})
        l, t, r, b = frame_rect(hwnd)
        z = zone_at(work, m["layout"], (l + r) // 2, (t + b) // 2)
        if str(z) in m["zones"]:
            continue
        if any(os.path.normcase(v["exe"]) == os.path.normcase(exe)
               for mm in cfg["monitors"].values() for v in mm["zones"].values()):
            continue                      # app already pinned somewhere
        m["zones"][str(z)] = {"exe": exe, "title": ""}
        n += 1
    return n


def list_windows(skip_hwnd=0):
    """Real top-level app windows: [(hwnd, exe_path, title)]."""
    res = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, lp):
        if hwnd == skip_hwnd or not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        if user32.GetWindow(hwnd, GW_OWNER):
            return True
        cloaked = ctypes.c_int(0)
        dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED,
                                     ctypes.byref(cloaked), 4)
        if cloaked.value:
            return True
        t = title_of(hwnd)
        if not t:
            return True
        exe = exe_of(hwnd)
        if exe.lower().endswith("applicationframehost.exe"):
            exe = real_uwp_exe(hwnd) or exe
        if exe:
            res.append((hwnd, exe, t))
        return True

    user32.EnumWindows(cb, 0)
    return res


def frame_rect(hwnd):
    """Visible frame (without Win10/11 invisible resize borders)."""
    r = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
                                    ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def place(hwnd, x, y, w, h):
    """Put the *visible* frame of hwnd at x,y,w,h. True if already there."""
    fl, ft, fr, fb = frame_rect(hwnd)
    if (abs(fl - x) <= 2 and abs(ft - y) <= 2 and
            abs((fr - fl) - w) <= 2 and abs((fb - ft) - h) <= 2):
        return True
    if user32.IsZoomed(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    wr = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(wr))
    dl, dt = fl - wr.left, ft - wr.top           # invisible border sizes
    dr, db = wr.right - fr, wr.bottom - fb
    user32.SetWindowPos(hwnd, None, x - dl, y - dt, w + dl + dr, h + dt + db,
                        SWP_NOZORDER | SWP_NOACTIVATE)
    return False


# --------------------------------------------------------------- layouts ----
# zone = (x, y, w, h) as fractions of the monitor work area
LAYOUTS = {
    "Halves": [(0, 0, .5, 1), (.5, 0, .5, 1)],
    "Left big + right small (2/3 - 1/3)": [(0, 0, 2 / 3, 1), (2 / 3, 0, 1 / 3, 1)],
    "Left small + right big (1/3 - 2/3)": [(0, 0, 1 / 3, 1), (1 / 3, 0, 2 / 3, 1)],
    "Left half + right stacked": [(0, 0, .5, 1), (.5, 0, .5, .5), (.5, .5, .5, .5)],
    "Left stacked + right half": [(0, 0, .5, .5), (0, .5, .5, .5), (.5, 0, .5, 1)],
    "Top / bottom": [(0, 0, 1, .5), (0, .5, 1, .5)],
    "Quarters (2x2)": [(0, 0, .5, .5), (.5, 0, .5, .5), (0, .5, .5, .5), (.5, .5, .5, .5)],
    "Thirds": [(0, 0, 1 / 3, 1), (1 / 3, 0, 1 / 3, 1), (2 / 3, 0, 1 / 3, 1)],
    "Wide center (25 - 50 - 25)": [(0, 0, .25, 1), (.25, 0, .5, 1), (.75, 0, .25, 1)],
    "Full screen": [(0, 0, 1, 1)],
    # --- extra variants added by SnapPin (not in the Windows 11 picker) ---
    "2/3 left + right stacked": [(0, 0, 2 / 3, 1), (2 / 3, 0, 1 / 3, .5), (2 / 3, .5, 1 / 3, .5)],
    "Left stacked + 2/3 right": [(0, 0, 1 / 3, .5), (0, .5, 1 / 3, .5), (1 / 3, 0, 2 / 3, 1)],
    "Left half + right 3 stacked": [(0, 0, .5, 1), (.5, 0, .5, 1 / 3), (.5, 1 / 3, .5, 1 / 3), (.5, 2 / 3, .5, 1 / 3)],
    "Left + two top right + wide bottom right": [(0, 0, .5, 1), (.5, 0, .25, .5), (.75, 0, .25, .5), (.5, .5, .5, .5)],
    "Top wide + two bottom": [(0, 0, 1, .5), (0, .5, .5, .5), (.5, .5, .5, .5)],
    "Two top + bottom wide": [(0, 0, .5, .5), (.5, 0, .5, .5), (0, .5, 1, .5)],
    "Center + stacked sides (25-50-25)": [(0, 0, .25, .5), (0, .5, .25, .5), (.25, 0, .5, 1), (.75, 0, .25, .5), (.75, .5, .25, .5)],
    "Four columns": [(i / 4, 0, .25, 1) for i in range(4)],
    "Three rows": [(0, i / 3, 1, 1 / 3) for i in range(3)],
    "Grid 3x2": [(c / 3, r / 2, 1 / 3, .5) for r in range(2) for c in range(3)],
}


def zone_rect(work, frac):
    x, y, w, h = work
    fx, fy, fw, fh = frac
    # integer edges computed from shared boundaries so zones never gap/overlap
    x0, x1 = round(x + fx * w), round(x + (fx + fw) * w)
    y0, y1 = round(y + fy * h), round(y + (fy + fh) * h)
    return x0, y0, x1 - x0, y1 - y0


# ---------------------------------------------------------------- config ----
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", "."), "SnapPin")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")


def load_config(path=CONFIG_PATH):
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    cfg.setdefault("enabled", True)
    cfg.setdefault("monitors", {})
    cfg.setdefault("launch_on_start", True)
    return cfg


def save_config(cfg, path=CONFIG_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, path)


def matches(rule, exe, title):
    if os.path.normcase(rule.get("exe", "")) != os.path.normcase(exe):
        return False
    tf = rule.get("title", "").strip().lower()
    return not tf or tf in title.lower()


_stuck = {}


def enforce(cfg, monitors, skip_hwnd=0):
    """One pass: move every pinned, non-minimized window into its zone."""
    if not cfg.get("enabled"):
        return 0
    if user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000:
        return 0                      # user is dragging - don't fight them
    wins = list_windows(skip_hwnd)
    moved = 0
    # every (monitor index, base zone rect, rule) that is configured
    targets = []
    for mi, (dev, work) in enumerate(monitors):
        m = cfg["monitors"].get(dev)
        zones = LAYOUTS.get(m.get("layout")) if m else None
        if not zones:
            continue
        for idx, rule in m.get("zones", {}).items():
            if int(idx) < len(zones):
                targets.append((mi, zone_rect(work, zones[int(idx)]), rule))
    if not targets:
        return 0
    for hw in [h for h in _need if not user32.IsWindow(h)]:
        _need.pop(hw, None)

    # which zone does each live window belong to?
    # The same app pinned on several monitors: exactly ONE zone - the one on
    # the monitor the window is currently on (else windows jump around).
    assign = []                       # (hwnd, target index)
    for hwnd, exe, title in wins:
        if user32.IsIconic(hwnd):
            continue
        cands = [i for i, t in enumerate(targets)
                 if matches(t[2], exe, title)]
        if not cands:
            continue
        here = monitor_of(hwnd, monitors)
        assign.append((hwnd, next((i for i in cands if targets[i][0] == here),
                                  cands[0])))

    rects = elastic_rects(targets, assign, monitors)

    for hwnd, ti in assign:
        x, y, w, h = rects[ti]
        # Window can't reach the zone: don't fight it every tick - retry
        # only once it changes.
        key = (hwnd, x, y, w, h)
        if _stuck.get(key) == frame_rect(hwnd):
            continue
        if not place(hwnd, x, y, w, h):
            moved += 1
            after = frame_rect(hwnd)
            aw, ah = after[2] - after[0], after[3] - after[1]
            ok = (abs(after[0] - x) <= 2 and abs(after[1] - y) <= 2 and
                  abs(aw - w) <= 2 and abs(ah - h) <= 2)
            if not ok:
                _stuck[key] = after
                if aw > w + 2 or ah > h + 2:
                    # learned: this app has a minimum size. Next pass the
                    # zone boundary shifts so it fits without overlapping.
                    _need[hwnd] = (max(aw, _need.get(hwnd, (0, 0))[0]),
                                   max(ah, _need.get(hwnd, (0, 0))[1]))
            else:
                _stuck.pop(key, None)
    return moved


_need = {}      # hwnd -> (min width, min height) learned by trying


def elastic_rects(targets, assign, monitors):
    """Zone rects, with shared boundaries nudged so apps that refuse to get
    smaller than some size still fit without covering their neighbours.
    Every zone touching a moved boundary moves with it, so zones never
    overlap and never leave gaps."""
    MIN = 150
    rects = [t[1] for t in targets]
    by_mon = {}
    for hwnd, ti in assign:
        if hwnd in _need:
            by_mon.setdefault(targets[ti][0], []).append((ti, _need[hwnd]))
    for mi, items in by_mon.items():
        _, (wx, wy, ww, wh) = monitors[mi]
        xmap, ymap = {}, {}

        def cur(ti):
            x, y, w, h = targets[ti][1]
            x0, x1 = xmap.get(x, x), xmap.get(x + w, x + w)
            y0, y1 = ymap.get(y, y), ymap.get(y + h, y + h)
            return x0, y0, x1 - x0, y1 - y0

        for _ in range(3):
            for ti, (nw, nh) in items:
                bx, by, bw, bh = targets[ti][1]
                ax, ay, aw, ah = cur(ti)
                snap = (dict(xmap), dict(ymap))
                if nw > aw:
                    if bx + bw < wx + ww:
                        xmap[bx + bw] = ax + nw
                    elif bx > wx:
                        xmap[bx] = ax + aw - nw
                if nh > ah:
                    if by + bh < wy + wh:
                        ymap[by + bh] = ay + nh
                    elif by > wy:
                        ymap[by] = ay + ah - nh
                same_mon = [i for i, t in enumerate(targets) if t[0] == mi]
                if any(cur(i)[2] < MIN or cur(i)[3] < MIN for i in same_mon):
                    xmap, ymap = snap      # would squash a neighbour: skip
        for i, t in enumerate(targets):
            if t[0] == mi:
                rects[i] = cur(i)
    return rects


def stuck_report():
    """Names of pinned windows that can't shrink to their zone (they would
    spill over a neighbouring zone). Entries vanish when the window moves."""
    names = []
    for (hwnd, x, y, w, h), frame in list(_stuck.items()):
        if not user32.IsWindowVisible(hwnd) or frame_rect(hwnd) != frame:
            _stuck.pop((hwnd, x, y, w, h), None)
            continue
        fw, fh = frame[2] - frame[0], frame[3] - frame[1]
        names.append(f"{os.path.basename(exe_of(hwnd))} needs at least "
                     f"{fw} x {fh} (zone is {w} x {h})")
    return names


def launch_missing(cfg):
    running = running_exe_names()   # by process, so tray-only apps aren't re-launched
    started = []
    for m in cfg["monitors"].values():
        for rule in m.get("zones", {}).values():
            exe = rule.get("exe", "")
            if exe.lower().endswith("applicationframehost.exe"):
                continue  # UWP: can't launch from exe path
            if os.path.basename(exe).lower() in running:
                continue
            if exe and os.path.exists(exe) and exe not in started:
                try:
                    subprocess.Popen([exe], cwd=os.path.dirname(exe))
                    started.append(exe)
                except OSError:
                    pass
    return started


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def pythonw_path():
    d, f = os.path.split(sys.executable)
    if f.lower() == "python.exe":
        w = os.path.join(d, "pythonw.exe")
        return w if os.path.exists(w) else sys.executable
    return sys.executable


def running_exe_names():
    """Lower-case exe file names of all running processes (incl. tray-only)."""
    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260)]
    k = kernel32
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.Process32FirstW.argtypes = k.Process32NextW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(PE)]
    snap = k.CreateToolhelp32Snapshot(2, 0)   # TH32CS_SNAPPROCESS
    names = set()
    pe = PE()
    pe.dwSize = ctypes.sizeof(pe)
    ok = k.Process32FirstW(snap, ctypes.byref(pe))
    while ok:
        names.add(pe.szExeFile.lower())
        ok = k.Process32NextW(snap, ctypes.byref(pe))
    k.CloseHandle(snap)
    return names


def relaunch_as_admin():
    exe = pythonw_path()
    params = " ".join('"%s"' % a for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)


# -------------------------------------------------------------------- UI ----
def run_ui():
    import tkinter as tk
    from tkinter import ttk, messagebox

    cfg = load_config()
    monitors = get_monitors()
    root = tk.Tk()
    root.title("SnapPin - apps stay where you put them")
    root.geometry("940x780")

    state = {"zone": 0, "wins": [], "paused_hotkey_down": False}
    mon_names = [f"Monitor {i + 1} ({n.lstrip(chr(92) + '.')})"
                 for i, (n, _) in enumerate(monitors)]
    mon_var = tk.StringVar(value=mon_names[0])
    layout_var = tk.StringVar()
    enabled_var = tk.BooleanVar(value=cfg["enabled"])
    status_var = tk.StringVar()
    win_var = tk.StringVar()
    title_var = tk.StringVar()

    top = ttk.Frame(root, padding=8)
    top.pack(fill="x")
    ttk.Label(top, text="Monitor:").pack(side="left")
    mon_cb = ttk.Combobox(top, textvariable=mon_var, values=mon_names,
                          state="readonly", width=28)
    mon_cb.pack(side="left", padx=6)
    ttk.Button(top, text="Find displays",
               command=lambda: find_displays()).pack(side="left")
    ttk.Label(top, text="Layout:").pack(side="left", padx=(10, 0))
    lay_cb = ttk.Combobox(top, textvariable=layout_var,
                          values=list(LAYOUTS), state="readonly", width=34)
    lay_cb.pack(side="left", padx=6)

    info_var = tk.StringVar()
    ttk.Label(root, textvariable=info_var, foreground="#2a5a9a").pack(
        fill="x", padx=10)

    canvas = tk.Canvas(root, width=720, height=300, bg="#202020",
                       highlightthickness=0)
    canvas.pack(padx=8, pady=4)

    mid = ttk.Frame(root, padding=8)
    mid.pack(fill="x")
    ttk.Label(mid, text="Selected zone gets:").grid(row=0, column=0, sticky="w")
    win_cb = ttk.Combobox(mid, textvariable=win_var, state="readonly",
                          width=62)
    win_cb.grid(row=0, column=1, padx=6, columnspan=3)
    ttk.Button(mid, text="Refresh list",
               command=lambda: refresh_wins()).grid(row=0, column=4)
    ttk.Label(mid, text="Only windows with title containing (optional):")\
        .grid(row=1, column=0, sticky="w", pady=4)
    ttk.Entry(mid, textvariable=title_var, width=30).grid(row=1, column=1,
                                                          sticky="w", padx=6)
    ttk.Button(mid, text="Assign to zone",
               command=lambda: assign()).grid(row=1, column=2)
    ttk.Button(mid, text="Clear zone",
               command=lambda: clear()).grid(row=1, column=3)
    ttk.Button(mid, text="Clear all",
               command=lambda: clear_all()).grid(row=1, column=4)

    # ---- list of every pinned app (all monitors) ----
    lst = ttk.LabelFrame(root, text="Pinned apps (these stay in their zone)",
                         padding=4)
    lst.pack(fill="both", expand=True, padx=8, pady=2)
    cols = ("monitor", "zone", "app", "filter", "status")
    tree = ttk.Treeview(lst, columns=cols, show="headings", height=5)
    for c, wd in zip(cols, (90, 50, 330, 160, 110)):
        tree.heading(c, text=c.capitalize())
        tree.column(c, width=wd, anchor="w")
    sb = ttk.Scrollbar(lst, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="left", fill="y")
    ttk.Button(lst, text="Unpin selected",
               command=lambda: unpin_selected()).pack(side="left", padx=6,
                                                      anchor="n")

    bot = ttk.Frame(root, padding=8)
    bot.pack(fill="x")
    ttk.Checkbutton(bot, text="Keep apps in place (Ctrl+Alt+P to pause/resume)",
                    variable=enabled_var,
                    command=lambda: toggle()).pack(side="left")
    ttk.Button(bot, text="Launch missing apps",
               command=lambda: launch()).pack(side="right")
    ttk.Button(bot, text="Start with Windows",
               command=lambda: autostart()).pack(side="right", padx=6)
    ttk.Button(bot, text="Pin all open apps",
               command=lambda: pin_all()).pack(side="right")
    ttk.Button(bot, text="Apply now",
               command=lambda: apply_now()).pack(side="right")
    ttk.Label(root, textvariable=status_var, foreground="#555").pack(
        fill="x", padx=10)

    def cur_dev():
        return monitors[mon_names.index(mon_var.get())][0]

    def cur_mon():
        dev = cur_dev()
        m = cfg["monitors"].setdefault(dev, {"layout": "Halves", "zones": {}})
        return m

    def refresh_wins():
        state["wins"] = list_windows(root.winfo_id())
        win_cb["values"] = [
            f"{os.path.basename(e)}  -  {t[:60]}" for _, e, t in state["wins"]]

    def refresh_pinned():
        tree.delete(*tree.get_children())
        running = running_exe_names()
        for mi, (dev, _) in enumerate(monitors):
            m = cfg["monitors"].get(dev)
            if not m:
                continue
            for z, rule in sorted(m["zones"].items(), key=lambda kv: int(kv[0])):
                exe = rule["exe"]
                tree.insert("", "end", iid=f"{mi}:{z}", values=(
                    f"Monitor {mi + 1}", int(z) + 1, os.path.basename(exe),
                    rule.get("title", "") or "(all windows)",
                    "running" if os.path.basename(exe).lower() in running
                    or exe.lower().endswith("applicationframehost.exe")
                    else "not running"))

    def unpin_selected():
        sel = tree.selection()
        if not sel:
            status_var.set("Select an app in the list first.")
            return
        for iid in sel:
            mi, z = iid.split(":")
            cfg["monitors"][monitors[int(mi)][0]]["zones"].pop(z, None)
        persist()
        redraw()
        status_var.set(f"Unpinned {len(sel)} app(s).")

    def on_pick(_=None):
        sel = tree.selection()
        if sel:
            mi, z = sel[0].split(":")
            mon_var.set(mon_names[int(mi)])
            state["zone"] = int(z)
            redraw(refresh=False)
    tree.bind("<<TreeviewSelect>>", on_pick)

    def redraw(refresh=True):
        canvas.delete("all")
        m = cur_mon()
        if refresh:               # (picking a row must not rebuild the list,
            refresh_pinned()      #  or the selection would be lost)
        try:
            det = monitor_details()[mon_names.index(mon_var.get())]
            info_var.set(describe_monitor(det))
        except Exception:
            info_var.set("")
        layout_var.set(m["layout"])
        cw, ch = 720, 300
        for i, fr in enumerate(LAYOUTS[m["layout"]]):
            x0, y0 = fr[0] * cw + 3, fr[1] * ch + 3
            x1, y1 = (fr[0] + fr[2]) * cw - 3, (fr[1] + fr[3]) * ch - 3
            sel = i == state["zone"]
            canvas.create_rectangle(x0, y0, x1, y1,
                                    fill="#3b5b8c" if sel else "#3a3a3a",
                                    outline="#7fb0ff" if sel else "#666",
                                    width=2)
            rule = m["zones"].get(str(i))
            label = os.path.basename(rule["exe"]) if rule else "(empty)"
            if rule and rule.get("title"):
                label += f"\n[{rule['title']}]"
            canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2,
                               text=f"Zone {i + 1}\n{label}", fill="white",
                               font=("Segoe UI", 11), justify="center")

    def on_click(ev):
        m = cur_mon()
        for i, fr in enumerate(LAYOUTS[m["layout"]]):
            if (fr[0] * 720 <= ev.x <= (fr[0] + fr[2]) * 720 and
                    fr[1] * 300 <= ev.y <= (fr[1] + fr[3]) * 300):
                state["zone"] = i
                m_rule = m["zones"].get(str(i))
                title_var.set(m_rule.get("title", "") if m_rule else "")
                redraw()
                return

    def assign():
        sel = win_cb.current()
        if sel < 0:
            messagebox.showinfo("SnapPin", "Pick a window from the list first.")
            return
        _, exe, title = state["wins"][sel]
        tf = title_var.get().strip()
        if exe.lower().endswith("applicationframehost.exe") and not tf:
            # (fallback only: real app couldn't be identified)
            tf = title  # Store apps share one exe - must match by title
            title_var.set(tf)
        cur_mon()["zones"][str(state["zone"])] = {"exe": exe, "title": tf}
        persist()
        redraw()
        apply_now()

    def clear():
        rule = cur_mon()["zones"].pop(str(state["zone"]), None)
        persist()
        redraw()
        if not rule:
            status_var.set("That zone is already empty. Click the zone you "
                           "want to clear in the preview first.")
            return
        title_var.set("")
        name = os.path.basename(rule["exe"])
        others = sum(1 for mm in cfg["monitors"].values()
                     for v in mm["zones"].values()
                     if os.path.normcase(v["exe"]) ==
                     os.path.normcase(rule["exe"]))
        status_var.set(f"Cleared zone {state['zone'] + 1} ({name})."
                       + (f" {name} is still pinned in {others} other zone(s)"
                          " - use 'Clear all' to remove everything."
                          if others else ""))

    def clear_all():
        n = sum(len(m["zones"]) for m in cfg["monitors"].values())
        if not n:
            status_var.set("Nothing is pinned.")
            return
        if not messagebox.askyesno(
                "Clear all", f"Remove all {n} pinned app(s) on every monitor?"):
            return
        for m in cfg["monitors"].values():
            m["zones"] = {}
        title_var.set("")
        persist()
        redraw()
        status_var.set(f"Cleared all {n} pinned app(s). Nothing is pinned now.")

    def persist():
        cfg["enabled"] = enabled_var.get()
        save_config(cfg)

    def on_layout(_=None):
        m = cur_mon()
        m["layout"] = layout_var.get()
        n = len(LAYOUTS[m["layout"]])
        m["zones"] = {k: v for k, v in m["zones"].items() if int(k) < n}
        state["zone"] = 0
        persist()
        redraw()

    def toggle():
        persist()
        status_var.set("Pinning ON" if enabled_var.get() else "Pinning PAUSED")

    def apply_now():
        n = enforce(cfg, monitors, root.winfo_id())
        status_var.set(f"Moved {n} window(s).")

    def find_displays():
        """Rescan monitors, then flash a big number on each one."""
        monitors[:] = get_monitors()
        mon_names[:] = [f"Monitor {i + 1} ({n.lstrip(chr(92) + '.')})"
                        for i, (n, _) in enumerate(monitors)]
        mon_cb["values"] = mon_names
        if mon_var.get() not in mon_names:
            mon_var.set(mon_names[0])
        redraw()
        details = monitor_details()
        for i, (n, (x, y, w, h)) in enumerate(monitors):
            fw, fh = details[i]["full"][2:]
            t = tk.Toplevel(root)
            t.overrideredirect(True)
            t.attributes("-topmost", True)
            bw, bh = 420, 300
            t.geometry(f"{bw}x{bh}+{x + (w - bw) // 2}+{y + (h - bh) // 2}")
            t.configure(bg="#1f3b66")
            tk.Label(t, text=str(i + 1), font=("Segoe UI", 120, "bold"),
                     fg="white", bg="#1f3b66").pack(expand=True)
            tk.Label(t, text=f"{fw} x {fh}  @ {details[i]['scale']}%"
                     + ("  (main)" if i == 0 else ""),
                     font=("Segoe UI", 14), fg="#bcd", bg="#1f3b66").pack(
                         pady=(0, 14))
            root.after(3000, t.destroy)
        status_var.set(f"Found {len(monitors)} display(s).")

    def pin_all():
        n = pin_all_open(cfg, monitors, root.winfo_id())
        persist()
        redraw()
        status_var.set(f"Pinned {n} open app(s) to the zone they're in. "
                       "Set your layout first, and arrange windows where "
                       "you want them before clicking.")

    def launch():
        s = launch_missing(cfg)
        status_var.set(f"Launched {len(s)} app(s). They snap in automatically.")

    def autostart():
        script = os.path.abspath(sys.argv[0])
        cmd = f'"{pythonw_path()}" "{script}" --minimized'
        r = subprocess.run(
            ["schtasks", "/create", "/f", "/tn", "SnapPin", "/sc", "onlogon",
             "/rl", "highest", "/tr", cmd], capture_output=True, text=True)
        status_var.set("Will start with Windows." if r.returncode == 0
                       else "Autostart failed: " + (r.stderr or r.stdout)[:100])

    def tick():
        # hotkey: Ctrl+Alt+P
        down = all(user32.GetAsyncKeyState(k) & 0x8000
                   for k in (VK_CONTROL, VK_MENU, VK_P))
        if down and not state["paused_hotkey_down"]:
            enabled_var.set(not enabled_var.get())
            toggle()
        state["paused_hotkey_down"] = down
        try:
            enforce(cfg, monitors, root.winfo_id())
            bad = stuck_report()
            if bad:
                status_var.set("Can't fit zone (would overlap): "
                               + "; ".join(bad[:2]))
        except Exception as e:  # never let the loop die
            status_var.set(f"error: {e}")
        root.after(500, tick)

    # Closing the window with X only minimizes, so pinning keeps working.
    # Use the Exit button to really quit.
    root.protocol("WM_DELETE_WINDOW", root.iconify)
    ttk.Button(bot, text="Exit SnapPin",
               command=root.destroy).pack(side="right", padx=6)

    def restart():
        persist()
        keep = [a for a in sys.argv[1:] if a == "--no-admin"]
        exe = pythonw_path() if "--no-admin" not in sys.argv else sys.executable
        subprocess.Popen([exe, os.path.abspath(sys.argv[0])] + keep,
                         cwd=os.path.dirname(os.path.abspath(sys.argv[0])))
        root.destroy()
    ttk.Button(bot, text="Restart",
               command=restart).pack(side="right")

    # On every start: apply the saved layout right away and (optionally)
    # open any pinned apps that aren't running yet.
    def on_start():
        if cfg["enabled"] and cfg.get("launch_on_start", True):
            launch_missing(cfg)
        enforce(cfg, monitors, root.winfo_id())
    root.after(200, on_start)

    canvas.bind("<Button-1>", on_click)
    lay_cb.bind("<<ComboboxSelected>>", on_layout)
    mon_cb.bind("<<ComboboxSelected>>", lambda e: (state.update(zone=0),
                                                    redraw()))
    refresh_wins()
    redraw()
    status_var.set("Pinning ON" if cfg["enabled"] else "Pinning PAUSED")
    if "--restart-test" in sys.argv:       # self-test hook (not carried over)
        root.after(1500, restart)
    if "--identify" in sys.argv:
        root.after(800, find_displays)
    if "--minimized" in sys.argv:
        root.iconify()
    root.after(500, tick)
    root.mainloop()


if __name__ == "__main__":
    if not is_admin() and "--no-admin" not in sys.argv:
        relaunch_as_admin()
        sys.exit(0)
    run_ui()

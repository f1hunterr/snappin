# SnapPin

Pin apps to Windows 11 snap-layout zones and **keep them there** — after you
close and reopen them, minimize and restore them, drag them away, or restart
SnapPin or Windows.

Pure Python standard library (`ctypes` + `tkinter`). No dependencies.

## Features

- 20 layouts: the 6 distinct Windows 11 snap layouts (halves, 2/3–1/3, left +
  stacked right, 2×2, thirds, 25/50/25) plus extras (rows, 4 columns, 3×2 grid…)
- Per-monitor layouts, with measured screen size, scale and usable area
  (taskbar excluded); **Find displays** flashes a number on each screen
- Pinned windows snap back within ~0.5 s of opening, restoring or being moved
  (it waits while you are dragging, so it doesn't fight you)
- Apps that refuse to shrink below a minimum size don't overlap their
  neighbours: the shared zone boundary shifts to fit them
- Microsoft Store apps are matched by their real program, not their title
- **Pin all open apps** - assign every open window to the zone it sits in
- List of all pinned apps with **Unpin selected**, **Clear zone**, **Clear all**
- **Launch missing apps**, **Start with Windows** (scheduled task), **Restart**
- Closing the window only minimizes it so pinning keeps working;
  `Ctrl+Alt+P` pauses/resumes

## Run

Requires Windows 10/11 and Python 3.9+ (tkinter is included with the
python.org installer).

```
run.bat
```

SnapPin asks for administrator rights (UAC) so it can also move windows of
apps that run as administrator. Use `python snappin.py --no-admin` to skip.

Settings are stored in `%APPDATA%\SnapPin\config.json`.

## Tests

The tests open Notepad and a small Tk window on your desktop:

```
python test_snappin.py    # drag / minimize / restore / close+reopen
python test_elastic.py    # minimum-size app does not overlap its neighbour
```

## Limitations

- All windows of a pinned app go to the same zone (e.g. every Chrome window).
- The layout preview shows normal zone sizes, not boundary shifts.
- Windows only; uses the Win32 API directly.

## License

MIT

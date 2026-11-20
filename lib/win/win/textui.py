"""端末での対話（layout -i -t）。"""

import os
import re
import subprocess
import sys
import time

from .common import CURRENT_FILE, TILE_APP_ID
from .shortcuts import WIN_BIN


def ascii_map(rects, area, current, labels, cols=64, rows=15):
    ax, ay, aw, ah = area
    grid = [[" "] * cols for _ in range(rows)]
    for i, (x, y, w, h) in enumerate(rects):
        c0 = round((x - ax) * (cols - 1) / aw)
        c1 = max(c0 + 2, round((x + w - ax) * (cols - 1) / aw))
        r0 = round((y - ay) * (rows - 1) / ah)
        r1 = max(r0 + 2, round((y + h - ay) * (rows - 1) / ah))
        for c in range(c0, c1 + 1):
            grid[r0][c] = grid[r1][c] = "="  if i == current else "-"
        for r in range(r0, r1 + 1):
            grid[r][c0] = grid[r][c1] = "#" if i == current else "|"
        text = f"{i + 1}{'*' if i == current else ''} {labels[i]}"[:max(0, c1 - c0 - 1)]
        mid = (r0 + r1) // 2
        for k, ch in enumerate(text):
            grid[mid][c0 + 1 + k] = ch
    return "\n".join("".join(row).rstrip() for row in grid)


def start_placeholders(wc, rects):
    procs = []
    for i in range(1, len(rects) + 1):
        procs.append(subprocess.Popen(
            [sys.executable, WIN_BIN, "_tile", str(i), str(len(rects))],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    deadline = time.time() + 10
    found = {}
    while time.time() < deadline and len(found) < len(rects):
        for w in wc.list():
            m = re.fullmatch(r"win-tile (\d+)", w.get("title") or "")
            if w.get("wm_class") == TILE_APP_ID and m:
                found[int(m.group(1))] = w["id"]
        time.sleep(0.2)
    for i, wid in found.items():
        wc.move_resize(wid, *rects[i - 1])
    return procs


def stop_placeholders(procs):
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(3)
        except subprocess.TimeoutExpired:
            p.kill()
    try:
        os.remove(CURRENT_FILE)
    except OSError:
        pass


def set_current(i):
    with open(CURRENT_FILE, "w") as f:
        f.write(str(i))

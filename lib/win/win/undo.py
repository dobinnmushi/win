"""元に戻す（win undo）。layout・place・here・group・send などが窓を動かす直前に、動かす窓の状態を記録し、戻せるようにする。

記録するのは、動かす窓だけ（位置・最小化・最大化・デスクトップ・重なり順・前面の窓）。操作が起動した窓は閉じない。
保存先は ~/.local/state/win/undo.json（WIN_UNDO で差し替え可）。直近の 10 件を残す。
"""

from concurrent.futures import ThreadPoolExecutor
import json
import os
import time

from .common import WinError
from .i18n import tr
from .dbus import normal_windows
from .placement import place_settled

UNDO_FILE = os.environ.get("WIN_UNDO") or os.path.join(
    os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "win", "undo.json")
KEEP = 10


class Entry:
    """1 回の操作で動かす窓の、動かす前の状態。add() で足して、commit() で保存する（窓が 1 枚もなければ保存しない）。"""

    def __init__(self, wc, what):
        self.what, self.wins = what, {}
        wins = normal_windows(wc)                                      # 1 回の問い合わせで、重なり順（下 → 上）・前面の窓・デスクトップを得る
        self._order = [w["id"] for w in wins]
        self._focus = next((w["id"] for w in wins if w.get("focus")), None)
        self._ws = {w["id"]: w.get("workspace", 0) for w in wins}

    def add(self, wc, windows):
        for w in windows:
            wid = w["id"] if isinstance(w, dict) else w
            if wid in self.wins or wid not in self._ws:
                continue
            d = wc.details(wid)
            self.wins[wid] = {"id": wid, "rect": [d["x"], d["y"], d["width"], d["height"]], "min": bool(d.get("minimized")),
                              "max": bool(d.get("maximized_horizontally") and d.get("maximized_vertically")), "ws": self._ws[wid]}

    def commit(self):
        if not self.wins:
            return
        data = _read()
        data.append({"t": int(time.time()), "what": self.what, "windows": list(self.wins.values()),
                     "z": [i for i in self._order if i in self.wins], "focus": self._focus})
        _write(data[-KEEP:])


def begin(wc, what):
    return Entry(wc, what)


def _read():
    try:
        with open(UNDO_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write(data):
    os.makedirs(os.path.dirname(UNDO_FILE), exist_ok=True)
    tmp = UNDO_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, UNDO_FILE)


def entries():
    """記録（新しい順）。"""
    return list(reversed(_read()))


def clear():
    try:
        os.remove(UNDO_FILE)
    except OSError:
        pass


def undo_last(wc):
    """直前の操作を戻す。(操作の名前, 戻した窓の数, 閉じていた窓の数) を返す。記録がなければ WinError。"""
    data = _read()
    if not data:
        raise WinError(tr("元に戻せる操作がありません"))
    ent = data.pop()
    _write(data)
    alive = {w["id"]: w for w in normal_windows(wc)}
    todo = [w for w in ent["windows"] if w["id"] in alive]

    def restore(w):
        wid, cur = w["id"], wc.details(w["id"])
        if cur.get("minimized") and not w["min"]:
            wc.simple("Unminimize", wid)
        if (cur.get("maximized_horizontally") or cur.get("maximized_vertically")) and not w["max"]:
            wc.simple("Unmaximize", wid)
        if alive[wid].get("workspace", 0) != w["ws"] and alive[wid].get("workspace") is not None:
            wc.call("MoveToWorkspace", "uu", wid, w["ws"])
        if w["max"]:
            wc.simple("Maximize", wid)
        else:
            place_settled(wc, wid, tuple(w["rect"]))
        if w["min"]:
            wc.simple("Minimize", wid)

    with ThreadPoolExecutor(max_workers=max(1, len(todo))) as ex:       # 置いたあとの定着待ちは、窓ごとに並行して行う
        list(ex.map(restore, todo))
    ids = {w["id"] for w in todo}
    for wid in ent.get("z", []):                                       # 元の重なり順（下 → 上）で前面へ
        if wid in ids and not next(w for w in todo if w["id"] == wid)["min"]:
            wc.simple("Activate", wid)
    if ent.get("focus") in alive:
        wc.simple("Activate", ent["focus"])
    return ent["what"], len(todo), len(ent["windows"]) - len(todo)

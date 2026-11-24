"""対話型の小窓を、拡張とコマンドから使うための部品（Dialog と、1 回で終わる関数）。

小窓（子プロセス）は描画だけを受け持ち、状態は親（この Python）が持つ。親は Dialog に行・地図・通知を渡して、
events() で返ってくる出来事（選んだ・キーを押した・文字を入力した・取り消した）に応じて、渡す内容を更新する。
"""

import contextlib
import dataclasses
import fcntl
import json
import os
import subprocess
from typing import Any

from .common import TILEPICK_APP_ID, WinError
from .i18n import tr
from .dbus import WindowCalls, usable_windows
from .store import icon_for_class
from .pickwin import center_and_focus
from .placement import launch
from .tilepick import launch_app, list_apps, spawn_tilepick

HINT = tr("↑↓ 選択 ・ Enter 決定 ・ Esc 取り消す")


_locks = []                                     # 取ったロックを、プロセスが終わるまで持っておく（閉じると解放される）


def single_instance(name):
    """同じ名前の対話が、すでに別のプロセスで動いていなければ、その印（ロック）を取って True を返す。
    動いていれば、その小窓を前面に出して False を返す（ロックはプロセスの終了で自動的に解放される）。"""
    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), f"win-{name}.lock")
    f = open(path, "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.seek(0)
        owner = f.read().strip()
        f.close()
        _raise_dialog_of(int(owner) if owner.isdigit() else None)
        return False
    f.seek(0)
    f.truncate()
    f.write(str(os.getpid()))
    f.flush()
    _locks.append(f)
    return True


def _raise_dialog_of(owner_pid):
    """プロセス owner_pid が開いている小窓（その子プロセスの窓）を前面に出す。見つからなければ何もしない。"""
    if owner_pid is None:
        return
    wc = WindowCalls()
    for w in wc.list():
        if w.get("wm_class") != TILEPICK_APP_ID:
            continue
        try:
            with open(f"/proc/{w.get('pid')}/stat", encoding="utf-8") as fh:
                ppid = int(fh.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        if ppid == owner_pid:
            with contextlib.suppress(WinError):
                wc.simple("Activate", w["id"])
            return


@dataclasses.dataclass
class Item:
    """一覧の 1 行。value は選ばれたときに返ってくる値（任意）。"""
    label: str
    sub: str = ""
    icon: str = ""
    value: Any = None


@dataclasses.dataclass
class Map:
    """ミニ地図。rects は作業領域に対する割合の (x, y, 幅, 高さ) のリスト。monitor は、その作業領域があるモニタの添字。"""
    rects: list
    labels: list | None = None
    current: int = -1
    free: list | None = None
    monitor: int | None = None


@dataclasses.dataclass
class Event:
    """小窓からの出来事。kind は "select"（行を決めた。via は "enter" か "tab"）・"key"・"text"・"highlight"（選択が動いた）・
    "launched"（! でアプリを起動した。window がその窓、text がその起動コマンド）・"edit"（入力欄の文字が変わった。watch=True のとき）・
    "cancel"。行がないまま Tab を押すと、item が None の "select"（via="tab"）になる。"""
    kind: str
    item: Item | None = None
    index: int | None = None
    via: str | None = None
    key: str | None = None
    text: str | None = None
    window: Any = None


class Dialog:
    """対話型の小窓 1 つ。with で開き、events() で出来事を受け取る。

    with Dialog("置き先を選ぶ", keys=("Left", "Right")) as d:
        d.rows([Item("a"), Item("b")])
        for ev in d.events():
            if ev.kind == "select": return ev.item
            if ev.kind == "key": d.notice("…")
    """

    def __init__(self, title="", *, hint=HINT, placeholder=tr("文字で絞り込み"), filter=True, entry=True, ask=False, show_list=True,
                 launch=False, highlight=False, keys=(), keep_selection=False, empty="", chip="", window_title="win",
                 vim=False, numbers=False, watch=False,
                 screen=None, wrap=None):
        self.title, self.hint, self.placeholder, self.window_title = title, hint, placeholder, window_title
        self.opts = {"filter": filter, "entry": entry, "ask": ask, "list": show_list, "launch": launch, "highlight": highlight,
                     "keep_selection": keep_selection, "empty": empty, "chip": chip, "vim": vim, "numbers": numbers, "watch": watch}
        self._keys, self._rows, self._map, self._notice, self._text = list(keys), [], None, "", None
        self._screen, self._wrap = screen, wrap or (lambda w: w)
        self._child = self._wc = self._wid = None
        self._apps_sent = False
        self._rows_dirty = True

    # -- 渡す内容
    def rows(self, items):
        """一覧の行を差し替える。"""
        self._rows = list(items)
        self._rows_dirty = True

    def options(self, **kw):
        """画面の設定（filter・entry・ask・show_list・launch・highlight・keep_selection・empty・chip・window_title・vim・numbers・watch・
        title・hint・placeholder）を、あとから変える。"""
        for k, v in kw.items():
            if k in ("title", "hint", "placeholder", "window_title"):
                setattr(self, k, v)
            elif k in self.opts:
                self.opts[k] = v
            else:
                raise TypeError(tr("知らない設定: {0}").format(k))

    def map(self, m):
        """ミニ地図を差し替える（None で隠す）。"""
        self._map = m

    def notice(self, text):
        """赤字の通知を出す（"" で消す）。"""
        self._notice = text or ""

    def keys(self, *names):
        """親へ渡してほしいキー（"Left"・"Right"・"Up"・"Down"・"Ctrl+s" など）。"""
        self._keys = list(names)

    def text(self, value):
        """入力欄の文字を置き換える（次の show で 1 回だけ）。"""
        self._text = value

    # -- 開閉
    def __enter__(self):
        self._wc = WindowCalls()
        self._child = spawn_tilepick(self._screen)
        return self

    def __exit__(self, *exc):
        with contextlib.suppress(OSError, ValueError):
            self._send({"cmd": "quit"})
        try:
            self._child.wait(3)
        except subprocess.TimeoutExpired:
            self._child.kill()
        return False

    def _send(self, msg):
        self._child.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self._child.stdin.flush()

    def _state(self, kind):
        m = {"cmd": kind, "title": self.title, "window_title": self.window_title, "hint": self.hint, "placeholder": self.placeholder, "notice": self._notice,
             "keys": self._keys, **self.opts}
        if kind == "show" or self._rows_dirty:
            m["rows"] = [{"title": i.label, "sub": i.sub, "icon": i.icon} for i in self._rows]
            self._rows_dirty = False
        if kind == "show":
            if self._text is not None:
                m["text"], self._text = self._text, None
            if self.opts["launch"] and not self._apps_sent:
                m["apps"], self._apps_sent = list_apps(), True
        mp = self._map
        m["map"] = None if mp is None else {"rects": mp.rects, "labels": mp.labels or [], "index": mp.current,
                                             "free": mp.free or [], "mon": mp.monitor}
        return m

    def _read(self):
        line = self._child.stdout.readline()
        try:
            return json.loads(line) if line else {"act": "cancel"}
        except ValueError:
            return {"act": "cancel"}

    def _refocus(self):
        if self._wid:
            with contextlib.suppress(WinError):
                self._wc.simple("Activate", self._wid)

    # -- 出来事
    def events(self):
        """小窓を開いて、出来事を 1 つずつ返す。出来事を受け取ったあと、次の出来事を待つ前に、現在の内容を小窓へ渡し直す。"""
        self._send(self._state("show"))
        if self._wid is None:                                # 2 回目以降の events() では、窓の位置を動かさない
            self._wid = center_and_focus(self._wc, self._child, TILEPICK_APP_ID)
        while True:
            res = self._read()
            act = res.get("act")
            if act == "cancel":
                yield Event("cancel")
                return
            if act in ("highlight", "edit"):                 # 返信を待たない通知: 変わった所だけ更新して続ける
                yield (Event("highlight", item=self._item(res["index"]), index=res["index"]) if act == "highlight"
                       else Event("edit", text=res.get("text", "")))
                self._send(self._state("patch"))
                continue
            ev = None
            try:
                if act == "select":
                    ev = Event("select", item=self._item(res["index"]), index=res["index"], via=res.get("via"))
                elif act == "key":
                    ev = Event("key", key=res.get("key"))
                elif act == "none":                                # 行がないまま Tab
                    ev = Event("select", via=res.get("via"))
                elif act == "text":
                    ev = Event("text", text=res.get("text", ""))
                elif act in ("app", "cmd"):
                    self._send({"cmd": "busy", "text": tr("起動しています…")})
                    if act == "app":
                        w, cmdline = launch_app(self._wc, res["id"], 12)
                    else:
                        w, cmdline = launch(self._wc, res["text"], 12), res["text"]
                    ev = Event("launched", window=self._wrap(w), text=cmdline, via=res.get("via"))
            except WinError as e:
                self.notice(str(e))
            if ev is not None:
                yield ev
            self._send(self._state("show"))
            self._refocus()

    def _item(self, index):
        return self._rows[index] if 0 <= index < len(self._rows) else None


# ---------------------------------------------------------------- 1 回で終わる関数

def window_items(wc, exclude=(), wrap=None):
    """今のワークスペースで最小化されていない窓を、一覧の行にする（前面に近い順）。value は窓（wrap を渡せば wrap した値）。"""
    wrap = wrap or (lambda w: w)
    skip = {w if isinstance(w, int) else w["id"] if isinstance(w, dict) else w.id for w in exclude}
    return [Item((w.get("title") or w.get("wm_class") or "")[:90], w.get("wm_class") or "", icon_for_class(w.get("wm_class")), wrap(w))
            for w in usable_windows(wc) if w["id"] not in skip]


def choose(title, items, *, preview=None, placeholder=tr("文字で絞り込み"), hint=HINT, filter=True, screen=None):
    """一覧から 1 つ選ぶ。選んだ Item、取り消したら None。preview(item) -> Map を渡すと、選択が動くたびに地図を出す。"""
    items = list(items)
    with Dialog(title, hint=hint, placeholder=placeholder, filter=filter, highlight=preview is not None, screen=screen) as d:
        d.rows(items)
        if preview and items:
            d.map(preview(items[0]))
        for ev in d.events():
            if ev.kind == "select":
                return ev.item
            if ev.kind == "highlight" and preview and ev.item is not None:
                d.map(preview(ev.item))
            if ev.kind == "cancel":
                return None
    return None


def confirm(title, text="", *, yes=tr("はい"), no=tr("いいえ"), screen=None):
    """はい・いいえを選ぶ。はいなら True（Esc は False）。"""
    with Dialog(title, hint=tr("↑↓ 選択 ・ Enter 決定 ・ Esc いいえ"), entry=False, screen=screen) as d:
        d.rows([Item(yes, text), Item(no)])
        for ev in d.events():
            if ev.kind == "select":
                return ev.index == 0
            if ev.kind == "cancel":
                return False
    return False


def ask(title, *, placeholder="", initial="", hint=tr("Enter 決定 ・ Esc 取り消す"), screen=None):
    """1 行の文字を入力する。入力した文字、取り消したら None。"""
    with Dialog(title, hint=hint, placeholder=placeholder, ask=True, show_list=False, screen=screen) as d:
        d.text(initial)
        for ev in d.events():
            if ev.kind == "text":
                return ev.text
            if ev.kind == "cancel":
                return None
    return None


def move_toward(rects, index, key):
    """rects（x, y, 幅, 高さ）の中で、index のタイルから見て key（"Left"・"Right"・"Up"・"Down"）の向きにいちばん近いタイルの添字。なければ index。"""
    cx = [x + w / 2 for x, y, w, h in rects]
    cy = [y + h / 2 for x, y, w, h in rects]
    dx, dy = {"Left": (-1, 0), "Right": (1, 0), "Up": (0, -1), "Down": (0, 1)}[key]
    best = [(abs(cx[k] - cx[index]) + abs(cy[k] - cy[index]), k) for k in range(len(rects))
            if k != index and (cx[k] - cx[index]) * dx + (cy[k] - cy[index]) * dy > 1e-9]
    return min(best)[1] if best else index


def pick_tile(title, rects, *, labels=None, current=0, free=None, monitor=None, screen=None):
    """ミニ地図の上でタイルを選ぶ（矢印キーで、その向きの隣のタイルへ）。選んだタイルの添字、取り消したら None。"""
    cur = current
    with Dialog(title, hint=tr("←↑↓→ 動かす ・ Enter 決定 ・ Esc 取り消す"), entry=False, show_list=False,
                keys=("Left", "Right", "Up", "Down"), screen=screen) as d:
        d.rows([Item(tr("ここに決める"))])
        d.map(Map(rects, labels, cur, free, monitor))
        for ev in d.events():
            if ev.kind == "key":
                cur = move_toward(rects, cur, ev.key)
                d.map(Map(rects, labels, cur, free, monitor))
            elif ev.kind == "select":
                return cur
            elif ev.kind == "cancel":
                return None
    return None


def pick_window(title=tr("窓を選ぶ"), *, launch=True, exclude=(), map=None, screen=None, wrap=None):
    """窓を 1 枚選ぶ（launch なら、先頭 ! でアプリを起動してその窓）。選んだ窓、取り消したら None。map（Map）で地図も出せる。"""
    with Dialog(title, hint=tr("↑↓ 選択 ・ Enter 決定") + (tr(" ・ 先頭 ! でアプリを探して新しく起動") if launch else "") + tr(" ・ Esc 取り消す"),
                placeholder=tr("文字で絞り込み　先頭に！でアプリを探して新規起動") if launch else tr("文字で絞り込み"),
                launch=launch, screen=screen, wrap=wrap) as d:
        d.rows(window_items(d._wc, exclude, wrap))
        d.map(map)
        for ev in d.events():
            if ev.kind == "select":
                return ev.item.value
            if ev.kind == "launched":
                return ev.window
            if ev.kind == "cancel":
                return None
    return None

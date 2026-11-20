"""win — GNOME の窓をコマンドで操作する。

Window Calls 拡張（window-calls@domandoman.xyz）の D-Bus を呼んで、
一覧・前面化・移動・サイズ変更・状態変更・分割配置（layout）を行う。

  win list                       窓の一覧
  win focus firefox              窓を前面に出す
  win layout                     小窓で型を選ぶ（Enter でタイルごとに選ぶ・Tab で前面の窓から自動配置）
  win layout quad                前面の窓から順に 2x2 に並べる
  win layout lr firefox '!ptyxis'   左に Firefox、右に新しく ptyxis を起動
  win layout quad firefox ...    1枚目に Firefox、残りは前面の窓から順に
  win layout "v(1,h(1,1))" -i    型だけ作って、タイルごとに絞り込んで選ぶ小窓（文字で絞り込み・
                                 先頭 ! でアプリを新規起動・Tab で残りを自動・Ctrl+S 空ける・Ctrl+B 戻る）
  win layouts                    登録済みの型の一覧
  win here                       選んだ窓（先頭 ! でアプリ）を、いまの窓と同じ位置・大きさにして前面へ
  win pick                       窓の一覧を小さく出し、j/k・矢印・Enter で選んで前面に出す
  win nav left|right|up|down     表に出ている窓の間で、その向きの窓にフォーカスを移す
  win prompt                     コマンドを 1 行打って窓を操作する小窓（Tab 補完・履歴つき）

型の式: full / v(a,b,...) 左右に分ける / h(a,b,...) 上下に分ける。
引数 a は割合の数（葉）、式（部分）、または「割合:式」。
"""
import argparse
import configparser
import contextlib
import glob
import hashlib
import importlib
import inspect
import io
import functools
import itertools
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
import types
import typing
import unicodedata
import tomllib

import gi
from gi.repository import Gio, GLib

try:                      # Gio.UnixInputStream / Gio.DesktopAppInfo は非推奨になった
    from gi.repository import GioUnix
except ImportError:
    GioUnix = None

WC_NAME = "org.gnome.Shell"
WC_PATH = "/org/gnome/Shell/Extensions/Windows"
WC_IFACE = "org.gnome.Shell.Extensions.Windows"
TILE_APP_ID = "local.win.tile"
PICK_APP_ID = "local.win.pick"
PROMPT_APP_ID = "local.win.prompt"
NVPROMPT_APP_ID = "local.win.nvprompt"
TILEPICK_APP_ID = "local.win.tilepick"
SETPICK_APP_ID = "local.win.setpick"
HISTORY = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "win", "history")
CONFIG = os.path.expanduser("~/.config/win/layouts.toml")
CURRENT_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "win-tile-current")

# 設定ファイルが無いときの作業領域の余白（上は GNOME の上部バー）
DEFAULT_INSETS = {"top": 32, "bottom": 0, "left": 0, "right": 0}

BUILTIN_LAYOUTS = {
    "full": "full",
    "lr": "v(1,1)",
    "tb": "h(1,1)",
    "thirds": "v(1,1,1)",
    "quad": "h(v(1,1),v(1,1))",
    "l1r2": "v(1,h(1,1))",
    "l2r1": "v(h(1,1),1)",
    "t1b2": "h(1,v(1,1))",
    "t2b1": "h(v(1,1),1)",
}


class WinError(Exception):
    pass


# ---------------------------------------------------------------- D-Bus

class WindowCalls:
    def __init__(self):
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None,
                WC_NAME, WC_PATH, WC_IFACE, None)
        except GLib.Error as e:
            raise WinError(f"GNOME Shell に接続できません: {e.message}")

    def call(self, method, fmt=None, *args):
        params = GLib.Variant(f"({fmt})", args) if fmt else None
        try:
            return self.proxy.call_sync(method, params, Gio.DBusCallFlags.NONE, 5000, None).unpack()
        except GLib.Error as e:
            raise WinError(f"Window Calls の {method} が失敗しました（拡張が無効かもしれません）: {e.message}")

    def list(self):
        return json.loads(self.call("List")[0])

    def details(self, wid):
        return json.loads(self.call("Details", "u", wid)[0])

    def rect(self, wid):
        r = json.loads(self.call("GetFrameRect", "u", wid)[0])
        return r["x"], r["y"], r["width"], r["height"]

    def move_resize(self, wid, x, y, w, h):
        self.call("MoveResize", "uiiuu", wid, x, y, w, h)

    def simple(self, method, wid):
        self.call(method, "u", wid)


def is_normal(w):
    return w.get("window_type") == 0 and w.get("wm_class") not in (TILE_APP_ID, PICK_APP_ID, PROMPT_APP_ID, TILEPICK_APP_ID,
                                                                NVPROMPT_APP_ID)


def normal_windows(wc):
    """通常の窓。順序は Window Calls が返すスタッキング順（下 → 上）。"""
    return [w for w in wc.list() if is_normal(w)]


def usable_windows(wc):
    """今のワークスペースにあり、最小化されていない窓。前面にあるものが先頭。"""
    out = []
    for w in reversed(normal_windows(wc)):
        if not w.get("in_current_workspace"):
            continue
        if wc.details(w["id"]).get("minimized"):
            continue
        out.append(w)
    return out


def match(w, sel):
    if sel.isdigit() and len(sel) >= 5:
        return w["id"] == int(sel)
    s = sel.lower()
    return any(s in (w.get(k) or "").lower() for k in ("wm_class", "wm_class_instance", "title"))


def find_windows(wc, sel, pool=None):
    """一致する窓。クラス名が完全一致するものを先に、あとは前面に近い順。@ で始まる指定は、位置・状態で選んだ 1 枚。"""
    if sel.startswith("@"):
        ids = None if pool is None else {x["id"] for x in pool}
        return [w for w in at_windows(wc, sel) if ids is None or w["id"] in ids]
    pool = usable_windows(wc) if pool is None else pool
    found = [w for w in pool if match(w, sel)]
    exact = [w for w in found if (w.get("wm_class") or "").lower() == sel.lower()]
    return exact + [w for w in found if w not in exact]


def selector_for(w, all_windows):
    """この窓だけを指す指定（クラス名 → 題名 → ID の順に、一意なものを使う）。"""
    cls, title = w.get("wm_class") or "", w.get("title") or ""
    if cls and sum(1 for x in all_windows if x.get("wm_class") == cls) == 1:
        return cls
    if title and sum(1 for x in all_windows if title.lower() in (x.get("title") or "").lower()) == 1:
        return title
    return str(w["id"])


def focused(wc):
    for w in normal_windows(wc):
        if w.get("focus"):
            return w
    raise WinError("前面の窓が見つかりません（-w で窓を指定してください）")


def targets(wc, sel):
    """命令をかける窓のリスト。省けば前面の窓、@visible・@class: などなら当たる窓すべて、ほかは 1 枚。"""
    if sel is not None and is_multi(sel):
        found = find_windows(wc, sel)
        if not found:
            raise WinError(f"窓が見つかりません: {sel}")
        return found
    return [target(wc, sel)]


def target(wc, sel):
    if sel is None:
        return focused(wc)
    found = find_windows(wc, sel, normal_windows(wc)[::-1])
    if not found:
        raise WinError(f"窓が見つかりません: {sel}")
    return found[0]


# 位置・状態で窓を選ぶ指定（窓の指定を書ける所ならどこでも使える）
AT_SELECTORS = [
    ("@focused", "前面の窓"),
    ("@prev", "前面の窓の次に手前にある窓（たいてい直前に使っていた窓）"),
    ("@left", "前面の窓の左にある窓（nav と同じ判定）"), ("@right", "前面の窓の右にある窓"),
    ("@up", "前面の窓の上にある窓"), ("@down", "前面の窓の下にある窓"),
    ("@largest", "見えている窓のうち、いちばん大きい窓"), ("@smallest", "見えている窓のうち、いちばん小さい窓"),
    ("@monitor:", "そのモニタでいちばん手前の窓（@monitor:primary・@monitor:eDP-1 など）"),
    ("@slot:", "いまの並び（窓の位置から逆算）の N 番目のタイルの窓（@slot:1 など。番号は layout の窓の列と同じ順。@slot:0 は前面の窓）"),
    ("@visible", "【複数】見えている窓すべて（前面に近い順）"),
    ("@others", "【複数】前面の窓以外の、見えている窓すべて"),
    ("@all", "【複数】このワークスペースの窓すべて（最小化も含む）"),
    ("@class:", "【複数】そのクラスの窓すべて（@class:firefox など。大文字小文字は区別しない）"),
    ("@pick", "その場で選ぶ（layout -i と同じ小窓。先頭 ! でアプリを起動して、その窓。Esc で命令ごと取り消す）"),
]
MULTI_SELECTORS = ("@visible", "@others", "@all", "@class:")


def is_multi(sel):
    """複数の窓に当たりうる @ の指定か。"""
    return bool(sel) and sel.lower().startswith(MULTI_SELECTORS)


def at_windows(wc, sel):
    """@ で始まる指定に当たる窓のリスト（前面に近い順。1 枚の指定なら 0〜1 枚）。知らない指定は WinError。"""
    key = sel.lower()
    if key == "@visible":
        return [w for w, _r in reversed(visible_windows(wc))]
    if key == "@others":
        return [w for w, _r in reversed(visible_windows(wc)) if not w.get("focus")]
    if key == "@all":
        return [w for w in reversed(normal_windows(wc)) if w.get("in_current_workspace")]
    if key.startswith("@class:"):
        cls = key.split(":", 1)[1]
        return [w for w in reversed(normal_windows(wc))
                if w.get("in_current_workspace") and (w.get("wm_class") or "").lower() == cls]
    if key == "@pick":
        w = pick_interactive(wc)
        if w is None:
            raise WinError("@pick: 選ぶのを取り消しました")
        return [w]
    if key.startswith("@slot:"):
        try:
            k = int(key.split(":", 1)[1])
        except ValueError:
            raise WinError(f"@slot: の後は番号です（@slot:1 など）: {sel}")
        if k == 0:                                        # 0 は前面の窓（番号だけで「いまの窓」を指せるように）
            w = at_window(wc, "@focused")
            return [] if w is None else [w]
        cfg = load_config()
        cur = current_tiles(wc, cfg)
        if cur["tree"] is None:
            return []
        order = tile_order(cur, cfg)[1]
        return [cur["by_id"][order[k - 1]]] if 1 <= k <= len(order) else []
    w = at_window(wc, sel)
    return [] if w is None else [w]


def at_window(wc, sel):
    """@ で始まる指定を窓 1 枚にする。当てはまる窓がなければ None。知らない指定は WinError。"""
    key = sel.lower()
    if key.startswith(MULTI_SELECTORS) or key.startswith("@slot:") or key == "@pick":
        found = at_windows(wc, sel)
        return found[0] if found else None
    if key == "@focused":
        return next((w for w in normal_windows(wc) if w.get("focus")), None)
    if key == "@prev":
        return next((w for w in usable_windows(wc) if not w.get("focus")), None)
    if key in ("@left", "@right", "@up", "@down"):
        vis = visible_windows(wc)
        cur = next(((w, r) for w, r in vis if w.get("focus")), None)
        if cur is None:
            return None
        return nav_pick(cur[1], [(w, r) for w, r in vis if w["id"] != cur[0]["id"]], key[1:])
    if key in ("@largest", "@smallest"):
        vis = visible_windows(wc)
        if not vis:
            return None
        pick = max if key == "@largest" else min
        return pick(vis, key=lambda wr: wr[1][2] * wr[1][3])[0]
    if key.startswith("@monitor:"):
        name = sel.split(":", 1)[1]
        monitors, logical = display_state()
        rects = [(lm, logical_rect(lm, monitors)) for lm in logical]
        hit = next((r for lm, r in rects if (name == "primary" and lm[4]) or name in [c[0] for c in lm[5]]), None)
        if hit is None:
            names = [c[0] for lm, _ in rects for c in lm[5]]
            raise WinError(f"モニタが見つかりません: {name}（使えるのは primary, {', '.join(names)}）")
        mx, my, mw, mh = hit
        for w in usable_windows(wc):                          # 前面に近い順
            x, y, rw, rh = wc.rect(w["id"])
            if mx <= x + rw / 2 < mx + mw and my <= y + rh / 2 < my + mh:
                return w
        return None
    raise WinError(f"知らない指定です: {sel}（使えるのは {', '.join(s for s, _ in AT_SELECTORS)}）")


# ---------------------------------------------------------------- 画面

def display_state():
    """(物理モニタの一覧, 論理モニタの一覧)。"""
    try:
        p = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None,
            "org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
            "org.gnome.Mutter.DisplayConfig", None)
        _serial, monitors, logical, _props = p.call_sync(
            "GetCurrentState", None, Gio.DBusCallFlags.NONE, 5000, None).unpack()
    except GLib.Error as e:
        raise WinError(f"画面の情報を取れません: {e.message}")
    return monitors, logical


def logical_rect(lm, monitors):
    """論理モニタ lm の領域 (x, y, w, h)。拡大率と回転を反映する。"""
    x, y, scale, transform = lm[0], lm[1], lm[2], lm[3]
    connector = lm[5][0][0]
    mon = next(m for m in monitors if m[0][0] == connector)
    mode = next(md for md in mon[1] if md[6].get("is-current"))
    w, h = mode[1], mode[2]
    if transform in (1, 3, 5, 7):
        w, h = h, w
    return x, y, round(w / scale), round(h / scale)


_MONITOR = {"rect": None, "primary": True}     # この実行で基準にするモニタの領域と、それが主モニタか（最初に 1 回だけ決める）


def resolve_monitor(choice=None):
    """基準にするモニタを決めて保持する。choice: None・"current"＝いまの窓があるモニタ、"primary"＝主モニタ、
    接続名（例 eDP-1）。choice を省いたときは、すでに決めていればそれを使う（小窓が開いてフォーカスが動いても変えない）。"""
    if choice is None and _MONITOR["rect"] is not None:
        return _MONITOR["rect"]
    monitors, logical = display_state()
    rects = [(lm, logical_rect(lm, monitors)) for lm in logical]
    primary = next(((lm, r) for lm, r in rects if lm[4]), rects[0])
    if choice in (None, "current"):
        chosen = primary
        try:
            wc = WindowCalls()
            x, y, w, h = wc.rect(focused(wc)["id"])
            cx, cy = x + w / 2, y + h / 2
            best = None
            for lm, r in rects:                       # 窓の中心が入るモニタ。なければ、重なりが最大のモニタ
                inside = r[0] <= cx < r[0] + r[2] and r[1] <= cy < r[1] + r[3]
                ov = max(0, min(x + w, r[0] + r[2]) - max(x, r[0])) * max(0, min(y + h, r[1] + r[3]) - max(y, r[1]))
                key = (inside, ov)
                if best is None or key > best[0]:
                    best = (key, (lm, r))
            if best and (best[0][0] or best[0][1] > 0):
                chosen = best[1]
        except (WinError, OSError, ValueError, KeyError, TypeError):
            pass                                      # 前面の窓が分からなければ、主モニタ
    elif choice == "primary":
        chosen = primary
    else:
        names = [c[0] for lm, _ in rects for c in lm[5]]
        chosen = next(((lm, r) for lm, r in rects if choice in [c[0] for c in lm[5]]), None)
        if chosen is None:
            raise WinError(f"モニタが見つかりません: {choice}（使えるのは primary, current, {', '.join(names)}）")
    _MONITOR["rect"], _MONITOR["primary"] = chosen[1], bool(chosen[0][4])
    return chosen[1]


def monitor_rect():
    """基準のモニタの論理領域 (x, y, w, h)。拡大率と回転を反映する。"""
    return _MONITOR["rect"] or resolve_monitor()


def load_config():
    cfg = {"layouts": dict(BUILTIN_LAYOUTS), "insets": dict(DEFAULT_INSETS), "gap": 0}
    if os.path.exists(CONFIG):
        with open(CONFIG, "rb") as f:
            user = tomllib.load(f)
        cfg["layouts"].update(user.get("layouts", {}))
        cfg["insets"].update(user.get("workarea", {}))
        cfg["gap"] = user.get("gap", 0)
    return cfg


def work_area(cfg):
    x, y, w, h = monitor_rect()
    i = dict(cfg["insets"])
    if not _MONITOR["primary"]:
        i["top"] = 0                                   # 上部バーは主モニタにしか出ないので、その高さの余白は主モニタだけに適用する
    return x + i["left"], y + i["top"], w - i["left"] - i["right"], h - i["top"] - i["bottom"]


# ---------------------------------------------------------------- 型

SHORT_LAYOUT_RE = re.compile(r"[\d\s:/(),.]+")


def is_shorthand_layout(text):
    """略記の式か（数字・空白・: / ( ) . だけでできている）。"""
    return bool(SHORT_LAYOUT_RE.fullmatch(text)) and any(c.isdigit() for c in text)


def shorthand_to_long(text):
    """型の略記を、v(…)/h(…) の式に直す。
    `,`（または空白）＝左右に並べる（v）、/＝上下に重ねる（h）、( ) でまとめる、重み:式 で割合。/ は , より強く結びつく。
    例: `1,2,1` = v(1,2,1)、`1,2:1/1/1,1` = v(1,2:h(1,1,1),1)、`(1,1/1)/1/(1,1)` = h(v(1,h(1,1)),1,v(1,1))。
    `数:` の後が数の並び（a/b/c）なら、並び全体への重み。かっこの式への重みは `数:(…)`。"""
    def err(msg):
        raise WinError(f"型の式（略記）が読めません（{msg}）: {text!r}")

    toks = re.findall(r"\d+(?:\.\d+)?|[:/(),]|\s+|.", text)
    toks = ["SP" if t.isspace() else t for t in toks]
    if any(len(t) == 1 and not (t.isdigit() or t in ":/(),") for t in toks if t != "SP"):
        err("使えない文字があります")
    st = {"i": 0}

    def tok(k=0):
        j = st["i"] + k
        return toks[j] if j < len(toks) else None

    def isnum(t):
        return t is not None and t not in ("SP", ":", "/", "(", ")", ",")

    def build(items):
        if len(items) == 1:
            return items[0][1]
        return ("split", "v", items)

    def parse_cols():
        items, comma = [], False                         # comma: 直前が , で、次の要素を待っている
        while True:
            while tok() == "SP":
                st["i"] += 1
            if tok() == ",":
                if not items or comma:
                    err("「,」の前に要素がありません")
                comma = True
                st["i"] += 1
                continue
            if tok() is None or tok() == ")":
                break
            items.append(parse_item())
            comma = False
        if comma:
            err("末尾の「,」の後に要素が必要です")
        if not items:
            err("空です")
        return items

    def parse_item():
        pre = None
        if isnum(tok()) and tok(1) == ":" and isnum(tok(2)):         # 数:数/数… ＝ 並び全体への重み
            pre = float(tok())
            st["i"] += 2
        chain = [parse_elem()]
        while tok() == "/":
            st["i"] += 1
            chain.append(parse_elem())
        if len(chain) == 1:
            if pre is not None:
                err("「重み:数」は使えません。重みは「重み:式」の形です")
            return chain[0]
        return (1.0 if pre is None else pre, ("split", "h", chain))

    def parse_elem():
        t = tok()
        if isnum(t):
            if tok(1) == ":":
                if tok(2) != "(":
                    err("「数:」の後には ( か数の並びが必要です")
                st["i"] += 2
                return (float(t), parse_group())
            st["i"] += 1
            return (float(t), None)
        if t == "(":
            return (1.0, parse_group())
        err("数か ( が必要です")

    def parse_group():
        st["i"] += 1                                                  # (
        node = build(parse_cols())
        if tok() != ")":
            err(") が必要です")
        st["i"] += 1
        return node

    def emit(node):
        if node is None:
            return "full"
        _, d, items = node
        args = []
        for w, n in items:
            args.append(f"{w:g}" if n is None else (emit(n) if w == 1 else f"{w:g}:{emit(n)}"))
        return f"{d}({','.join(args)})"

    node = build(parse_cols())
    if st["i"] < len(toks):
        err("対応しない ) があります")
    return emit(node)


class LayoutParser:
    """full | v(arg,...) | h(arg,...)。arg は 数 | 式 | 数:式。略記（`1 2 1` など）も読める（shorthand_to_long）。"""

    def __init__(self, text):
        self.s = shorthand_to_long(text) if is_shorthand_layout(text) else text
        self.i = 0

    def err(self, msg):
        raise WinError(f"型の式が読めません（{msg}）: {self.s!r} の {self.i} 文字目")

    def ws(self):
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def parse(self):
        node = self.expr()
        self.ws()
        if self.i != len(self.s):
            self.err("余分な文字")
        return node

    def expr(self):
        self.ws()
        if self.s.startswith("full", self.i):
            self.i += 4
            return ("leaf",)
        m = re.compile(r"([vh])\s*\(").match(self.s, self.i)
        if not m:
            self.err("full か v( h( が必要")
        self.i = m.end()
        args = [self.arg()]
        while True:
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1
                args.append(self.arg())
            else:
                break
        if self.i >= len(self.s) or self.s[self.i] != ")":
            self.err(") が必要")
        self.i += 1
        return ("split", m.group(1), args)

    def arg(self):
        self.ws()
        m = re.compile(r"\d+(?:\.\d+)?").match(self.s, self.i)
        if m:
            weight = float(m.group())
            self.i = m.end()
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ":":
                self.i += 1
                return weight, self.expr()
            return weight, ("leaf",)
        return 1.0, self.expr()


def leaf_rects(node, rect):
    """木を、葉の矩形 (x0, y0, x1, y1) のリストにする（左→右・上→下の順）。"""
    x0, y0, x1, y1 = rect
    if node[0] == "leaf":
        return [rect]
    _, direction, args = node
    total = sum(w for w, _ in args)
    span = (x1 - x0) if direction == "v" else (y1 - y0)
    out, cum, prev = [], 0.0, 0
    for weight, child in args:
        cum += weight
        pos = round(span * cum / total)
        if direction == "v":
            out += leaf_rects(child, (x0 + prev, y0, x0 + pos, y1))
        else:
            out += leaf_rects(child, (x0, y0 + prev, x1, y0 + pos))
        prev = pos
    return out


def compute_rects(expr, area, gap):
    ax, ay, aw, ah = area
    rects = leaf_rects(LayoutParser(expr).parse(), (ax, ay, ax + aw, ay + ah))
    out = []
    for x0, y0, x1, y1 in rects:
        lo, hi = gap // 2, gap - gap // 2
        if x0 > ax: x0 += hi
        if y0 > ay: y0 += hi
        if x1 < ax + aw: x1 -= lo
        if y1 < ay + ah: y1 -= lo
        out.append((x0, y0, x1 - x0, y1 - y0))
    return out


def resolve_layout(cfg, text):
    return cfg["layouts"].get(text, text)


# ---------------------------------------------------------------- 配置

def place(wc, wid, rect):
    wc.simple("Unminimize", wid) if wc.details(wid).get("minimized") else None
    wc.move_resize(wid, *rect)


def place_settled(wc, wid, rect, tries=8):
    """窓を rect に置き、起動直後にアプリ自身が動かして元に戻る場合に備えて、定着するまで繰り返す。

    位置が合っていて、大きさが要求以上なら（最小サイズで縮まらないだけなので）それで確定する。
    返り値は None（ぴったり）か、実際の枠 (x, y, w, h)。
    """
    rect, got = tuple(rect), None
    for _ in range(tries):
        place(wc, wid, rect)
        time.sleep(0.3)
        got = tuple(wc.rect(wid))
        if got[:2] != rect[:2]:
            # 最小サイズより小さい大きさを求めると、Mutter は大きさだけ直して位置を動かさない。位置だけ別に動かす
            wc.call("Move", "uii", wid, rect[0], rect[1])
            time.sleep(0.2)
            got = tuple(wc.rect(wid))
        if got == rect:
            return None
        if got[:2] == rect[:2] and got[2] >= rect[2] and got[3] >= rect[3]:
            return got
    return got


def raise_group(wc, windows, prefer=None):
    """配置した窓をすべて前面に出す（それ以前の重なりは無視する）。

    最後にフォーカスを持つのは、prefer（配置した窓の中にあれば）か、先頭のタイルの窓。
    prefer が配置した窓の中に無いときは、前面は配置した窓だけにして、prefer は上に出さない。
    """
    ids = [w["id"] for w in windows]
    if not ids:
        return
    for wid in reversed(ids):               # 先頭のタイルが最後（いちばん上）になる
        wc.simple("Activate", wid)
    if prefer in ids and prefer != ids[0]:
        wc.simple("Activate", prefer)


def verify(wc, wid, rect):
    """配置後の実際の枠を確かめる。最小サイズなどで合わないとき、その旨を返す。"""
    time.sleep(0.2)
    got = wc.rect(wid)
    return None if tuple(got) == tuple(rect) else got


def wait_new_window(wc, before, timeout, what):
    """before に無かった通常の窓が現れるまで待って返す。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        new = [w for w in normal_windows(wc) if w["id"] not in before]
        if new:
            time.sleep(0.5)  # 窓が落ち着くのを待つ
            return new[-1]
        time.sleep(0.2)
    raise WinError(f"{timeout} 秒待っても新しい窓が現れませんでした: {what}")


# 引数なしで起動すると、起動中のとき新しい窓を作らず既存の窓を前面に出すだけのアプリ（2 回目の起動で窓が増えないのを実機で確認したもの）
NEW_WINDOW_APPS = {"ptyxis": ["--new-window"], "gnome-text-editor": ["--new-window"], "nautilus": ["--new-window"],
                   # Chrome は --new-window だけだと窓が出ない（URL があると出る。chrome://newtab でも出ないのを確認）ので about:blank を開く
                   "google-chrome-stable": ["--new-window", "about:blank"], "google-chrome": ["--new-window", "about:blank"]}


def launch(wc, cmdline, timeout=20):
    """コマンドを起動し、新しく現れた窓を返す。"""
    argv = shlex.split(cmdline)
    if not argv:
        raise WinError("起動するコマンドが空です")
    if argv[0] == "win":                                  # PATH に win が無い環境（ショートカットなど）でも動くように
        argv = [sys.executable, WIN_BIN] + argv[1:]
    if len(argv) == 1 and os.path.basename(argv[0]) in NEW_WINDOW_APPS:    # 引数なしは、起動中なら既存の窓を前面にするだけで窓が増えない
        argv += NEW_WINDOW_APPS[os.path.basename(argv[0])]
    before = {w["id"] for w in normal_windows(wc)}
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        raise WinError(f"起動できません: {argv[0]}: {e}")
    try:
        return wait_new_window(wc, before, timeout, cmdline)
    except WinError as e:
        name = os.path.basename(argv[0])
        running = subprocess.run(["pgrep", "-x", name[:15]], capture_output=True).returncode == 0
        if running:
            raise WinError(f"{e}\n  {name} はすでに起動中です。起動中のアプリは、新しい窓を作らず既存の窓を前面に出すだけのことがあります"
                           f"（新しい窓を作る引数が要るか確かめてください。例: ptyxis --new-window）")
        raise


def describe(w):
    return f"{w['id']} {w.get('wm_class')} 「{(w.get('title') or '')[:40]}」"


def parse_window_spec(sel):
    """窓の指定を (照合する語, 窓がなければ起動するか, 起動コマンド) に分ける。
    `クラス名?` ＝ なければ、アプリ一覧から探したコマンドで起動。`クラス名?コマンド` ＝ なければ、そのコマンドで起動。"""
    m = re.fullmatch(r"([\w.\-]+)\?(.*)", sel, re.S)
    if m:
        return m.group(1), True, m.group(2).strip()
    if sel.endswith("?") and len(sel) > 1:
        return sel[:-1], True, ""
    return sel, False, ""


def expand_multi(wc, sels, n):
    """窓の列の @visible・@class: などを、当たる窓の ID に広げる（ほかの指定のぶんを除いた、残りのタイルの数まで）。"""
    if not any(is_multi(x) for x in sels):
        return sels
    free = n - sum(1 for x in sels if not is_multi(x))
    out, used = [], set()
    pool = usable_windows(wc)
    for x in sels:                                        # 個別に指定した窓は、複数の指定から除く（同じ窓が 2 つのタイルに入らないように）
        if not is_multi(x) and x not in ("-", "_") and not x.startswith("!") and x.lower() != "@pick":
            hit = [w for w in find_windows(wc, parse_window_spec(x)[0], pool) if w["id"] not in used]
            if hit:
                used.add(hit[0]["id"])
    for x in sels:
        if not is_multi(x):
            out.append(x)
            continue
        got = [w for w in find_windows(wc, x) if w["id"] not in used][:max(0, free)]
        if not got:
            raise WinError(f"窓が見つかりません: {x}")
        free -= len(got)
        used |= {w["id"] for w in got}
        out += [str(w["id"]) for w in got]
    return out


def cmd_layout(args):
    wc = WindowCalls()
    cfg = load_config()
    gap = cfg["gap"] if args.gap is None else args.gap
    area = work_area(cfg)
    if args.layout is None:
        return gui_layout_flow(wc, args, cfg, area, gap)
    expr = resolve_layout(cfg, args.layout)
    rects = compute_rects(expr, area, gap)
    n = len(rects)
    if args.interactive:
        return (interactive if args.text else gui_interactive)(wc, args, expr, rects, area)

    plan = [None] * n
    if args.windows:
        sels = [a for a in args.windows]
        rest = sels[-1] in ("...", "…")          # 末尾の ... は「残りは前面の窓から順に」
        if rest:
            sels = sels[:-1]
        sels = expand_multi(wc, sels, n)
        if len(sels) > n:
            raise WinError(f"タイルは {n} 枚ですが、窓の指定が {len(sels)} 個あります")
        pool = usable_windows(wc)
        taken = set()
        for i, sel in enumerate(sels):
            if sel in ("-", "_"):
                continue
            if sel.startswith("!"):
                plan[i] = ("run", sel[1:])
                continue
            base, optional, fallback = parse_window_spec(sel)         # クラス名?＝窓がなければ起動、クラス名?コマンド＝そのコマンドで起動
            found = [w for w in find_windows(wc, base, pool) if w["id"] not in taken]
            if not found and optional:
                cmdline = fallback or launch_for_class(base)
                if not cmdline:
                    raise WinError(f"タイル {i + 1}: 窓が見つからず、起動コマンドも分かりません: {base}")
                plan[i] = ("run", cmdline)
                continue
            if not found:
                raise WinError(f"タイル {i + 1}: 窓が見つかりません: {sel}")
            plan[i] = ("win", found[0])
            taken.add(found[0]["id"])
        # 同じ指定が複数のタイルにあるときは、各窓がいまある位置にいちばん近いタイルへ入れる
        # （前面の順で割り当てると、同じ命令を繰り返すたびに窓が入れ替わる）
        groups = {}
        for i, sel in enumerate(sels):
            if sel not in ("-", "_") and not sel.startswith("!"):
                groups.setdefault(parse_window_spec(sel)[0], []).append(i)
        for idxs in groups.values():
            idxs = [i for i in idxs if plan[i] is not None and plan[i][0] == "win"]
            if not 2 <= len(idxs) <= 6:
                continue
            wins = [plan[i][1] for i in idxs]
            center = lambda r: (r[0] + r[2] / 2, r[1] + r[3] / 2)
            now = {w["id"]: center(tuple(wc.rect(w["id"]))) for w in wins}
            best = min(itertools.permutations(wins),
                       key=lambda perm: sum(math.dist(now[w["id"]], center(rects[i])) for w, i in zip(perm, idxs)))
            for w, i in zip(best, idxs):
                plan[i] = ("win", w)
        if rest:
            others = [w for w in pool if w["id"] not in taken]
            for i in range(len(sels), n):
                if others:
                    plan[i] = ("win", others.pop(0))
    else:
        for i, w in enumerate(usable_windows(wc)[:n]):
            plan[i] = ("win", w)

    for i, (r, p) in enumerate(zip(rects, plan), 1):
        what = "（空）" if p is None else (f"起動: {p[1]}" if p[0] == "run" else describe(p[1]))
        print(f"タイル {i}: x={r[0]} y={r[1]} {r[2]}x{r[3]}  ← {what}")
    if args.dry_run:
        return 0

    try:
        me = focused(wc)["id"]
    except WinError:
        me = None
    placed, results = [], []
    for i, (r, p) in enumerate(zip(rects, plan), 1):
        if p is None:
            continue
        w = launch(wc, p[1]) if p[0] == "run" else p[1]
        place_settled(wc, w["id"], r)
        placed.append(w)
        results.append((w["id"], r, i))
    raise_group(wc, placed, me)
    # 前面に出したあとに、アプリ自身が大きさを戻すことがある（Firefox で 5px 足りなくなった例）。ずれた窓は、もう一度置き直す
    launched = any(p is not None and p[0] == "run" for p in plan)
    got_by = {}
    for delay in ((0.5, 1.5) if launched else (0.5,)):        # 起動した窓は、セッションの復元などで遅れて動くことがあるので、もう 1 回確認する
        time.sleep(delay)
        for wid, r, i in results:
            got_by[i] = None if tuple(wc.rect(wid)) == tuple(r) else place_settled(wc, wid, r, tries=6)
    for wid, r, i in results:
        got = got_by.get(i)
        if got:
            print(f"  注意: タイル {i} の窓は希望の大きさにならず {got[2]}x{got[3]}@({got[0]},{got[1]}) です"
                  f"（最小サイズなど）", file=sys.stderr)
    return 0


def apply_one(wc, wid, rect, index):
    got = place_settled(wc, wid, rect)
    if got:
        print(f"  注意: タイル {index} の窓は希望の大きさにならず "
              f"{got[2]}x{got[3]}@({got[0]},{got[1]}) です（最小サイズなど）", file=sys.stderr)


# ---------------------------------------------------------------- 対話

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


# ---------------------------------------------------------------- 窓の一覧から選ぶ

def row_title(w, d=None):
    t = w.get("title") or ""
    if d and d.get("minimized"):
        t += "  （最小化）"
    if not w.get("in_current_workspace"):
        t += f"  [WS {w.get('workspace', 0) + 1}]"
    return t


def center_and_focus(wc, proc, app_id, timeout=8):
    """子プロセスの窓が出たら、作業領域の中央付近に動かして前面にする（Wayland では窓自身が位置を決められない）。
    出た直後に動かすと、GNOME が新しい窓を自分で置き直すことがあるので、狙った位置に来たのを確かめるまで動かし直す。"""
    deadline = time.time() + timeout
    ax, ay, aw, ah = work_area(load_config())
    while time.time() < deadline and proc.poll() is None:
        wid = next((w["id"] for w in wc.list() if w.get("wm_class") == app_id), None)
        if wid:
            settle = time.time() + 0.6
            while True:
                _, _, w, h = wc.rect(wid)
                if (w == 0 or h == 0) and time.time() < settle:   # 見つけた直後は、まだ大きさ 0 で置かれていない
                    time.sleep(0.01)
                    continue
                target = (ax + (aw - w) // 2, ay + (ah - h) // 3, w, h)
                wc.move_resize(wid, *target)                      # 確かめる値（枠の座標）と同じ基準で動かす
                time.sleep(0.03)
                if tuple(wc.rect(wid)) == target or time.time() > settle:
                    break
            wc.simple("Activate", wid)
            return wid
        time.sleep(0.02)
    return None


def pick_window(wc, windows, extras, title="窓を選ぶ"):
    """窓の一覧を小さく出し、選ばれた行の動作 {"act": ...} を返す（取消は None）。"""
    rows = [{"cls": w.get("wm_class") or "", "title": row_title(w, wc.details(w["id"])),
             "icon": icon_for_class(w.get("wm_class")), "act": {"act": "win", "id": w["id"]}} for w in windows]
    rows += [{"cls": "", "title": label, "act": {"act": act}} for act, label in extras]
    if not rows:
        return None
    proc = subprocess.Popen([sys.executable, WIN_BIN, "_pick"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    proc.stdin.write(json.dumps({"title": title, "rows": rows}))
    proc.stdin.close()
    center_and_focus(wc, proc, PICK_APP_ID)
    out = proc.stdout.read()
    proc.wait()
    for line in reversed(out.strip().splitlines()):
        try:
            res = json.loads(line)
        except ValueError:
            continue
        return None if res.get("act") == "cancel" else res
    return None


def line_from_picker(wc, pool):
    """一覧の選択を、対話モードの入力文字列に直す（取消は None）。"""
    res = pick_window(wc, pool, [("cmd", "コマンドを入力して新しく起動…"),
                                 ("skip", "このタイルは空けておく"),
                                 ("back", "前のタイルへ戻る")], "このタイルに入れる窓")
    if res is None:
        return None
    if res["act"] == "win":
        return str(next(k for k, w in enumerate(pool, 1) if w["id"] == res["id"]))
    if res["act"] == "cmd":
        cmd = input("起動するコマンド > ").strip()
        return "!" + cmd if cmd else None
    return {"skip": "", "back": "<"}[res["act"]]


def ask_line(wc, pool, i, n, auto_pick):
    """タイルの入力を 1 行読む。p で一覧、--pick なら最初に一覧を出す。"""
    while True:
        if auto_pick:
            auto_pick = False
            line = line_from_picker(wc, pool)
            if line is not None:
                return line
        line = input(f"タイル {i + 1}/{n} > ").strip()
        if line == "p":
            line = line_from_picker(wc, pool)
            if line is None:
                continue
        return line


def run_pick():
    """一覧を出して、j/k・矢印で動き、Enter で決める小さな窓。結果は 1 行の JSON で標準出力へ。"""
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    spec = json.load(sys.stdin)
    rows_spec = spec["rows"]

    class App(Adw.Application):
        def __init__(self):
            super().__init__(application_id=PICK_APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)

        def finish(self, act):
            print(json.dumps(act), flush=True)
            self.quit()

        def do_activate(self):
            listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.BROWSE, activate_on_single_click=True)
            listbox.add_css_class("boxed-list")
            rows = []
            for k, r in enumerate(rows_spec, 1):
                box = Gtk.Box(spacing=12, margin_top=7, margin_bottom=7, margin_start=12, margin_end=12)
                num = Gtk.Label(label=str(k) if k <= 9 else "", width_chars=2, xalign=1)
                num.add_css_class("dim-label")
                cls = Gtk.Label(label=r["cls"], xalign=0, width_chars=16, max_width_chars=16,
                                ellipsize=3)
                cls.add_css_class("dim-label")
                title = Gtk.Label(label=r["title"], xalign=0, hexpand=True, ellipsize=3, max_width_chars=48)
                parts = (num, icon_widget(Gtk, Gdk, r["icon"]), cls, title) if "icon" in r else (num, cls, title)
                for wdg in parts:
                    box.append(wdg)
                row = Gtk.ListBoxRow()
                row.set_child(box)
                listbox.append(row)
                rows.append(row)

            def select(i):
                i = max(0, min(len(rows) - 1, i))
                listbox.select_row(rows[i])
                rows[i].grab_focus()

            def current():
                sel = listbox.get_selected_row()
                return sel.get_index() if sel else 0

            def on_key(_ctrl, keyval, _keycode, state):
                name = Gdk.keyval_name(keyval)
                if name in ("j", "Down", "n"):
                    select(current() + 1)
                elif name in ("k", "Up", "p"):
                    select(current() - 1)
                elif name in ("g", "Home"):
                    select(0)
                elif name in ("G", "End"):
                    select(len(rows) - 1)
                elif name in ("Return", "KP_Enter", "l"):
                    self.finish(rows_spec[current()]["act"])
                elif name in ("Escape", "q", "h"):
                    self.finish({"act": "cancel"})
                elif name and len(name) == 1 and name in "123456789" and int(name) <= len(rows):
                    self.finish(rows_spec[int(name) - 1]["act"])
                else:
                    return False
                return True

            listbox.connect("row-activated", lambda _lb, row: self.finish(rows_spec[row.get_index()]["act"]))
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                        max_content_height=440, child=listbox, margin_top=6, margin_bottom=6,
                                        margin_start=8, margin_end=8)
            hint = Gtk.Label(label="j/k ↑↓ 移動 ・ Enter/l 決定 ・ 1–9 直接 ・ Esc/q/h 取消", margin_bottom=8)
            hint.add_css_class("dim-label")
            hint.add_css_class("caption")
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            outer.append(scroll)
            outer.append(hint)
            header = Adw.HeaderBar(title_widget=Gtk.Label(label=spec["title"]), show_end_title_buttons=False)
            view = Adw.ToolbarView(content=outer)
            view.add_top_bar(header)
            win = Adw.ApplicationWindow(application=self, title="win-pick", default_width=620, content=view)
            ctrl = Gtk.EventControllerKey()
            ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            ctrl.connect("key-pressed", on_key)
            win.add_controller(ctrl)
            win.connect("close-request", lambda _w: (self.finish({"act": "cancel"}), True)[1])
            win.present()
            select(0)

    App().run([])


# ---------------------------------------------------------------- 絞り込みで選ぶ対話モード（既定）

def fuzzy(query, text, subseq=True):
    """query の各語（空白区切り）がすべて text に含まれれば点数、そうでなければ None。

    連続した部分文字列 > 語頭 > 飛び飛びの部分列 の順に高い点を付ける（subseq=False なら部分列は不一致）。
    """
    low, total = text.lower(), 0
    for term in query.lower().split():
        i = low.find(term)
        if i >= 0:
            total += 100 - min(i, 50) + (20 if i == 0 or low[i - 1] in " -_./(" else 0)
            continue
        if not subseq:
            return None
        pos, gaps = -1, 0
        for ch in term:
            j = low.find(ch, pos + 1)
            if j < 0:
                return None
            gaps += (j - pos - 1) if pos >= 0 else 0
            pos = j
        total += max(1, 50 - gaps)
    return total


def tile_candidates(text, windows, apps):
    """入力文字列に対する候補。先頭が ! ならアプリ（と、コマンドとして実行）、そうでなければ窓。

    戻り値は (モード, [{"act": 動作, "title": ..., "sub": ..., "icon": ...}])。
    同点なら元の順（窓は前面が先）を保つ。
    """
    if text.startswith("!"):
        q = text[1:].strip()
        scored = []
        for k, a in enumerate(apps):
            sc = 0
            if q:
                sc = fuzzy(q, a["name"])                      # 名前は飛び飛びの一致も許す
                if sc is None:                                # 説明・ID は連続一致だけ（雑音を避ける）
                    sc = fuzzy(q, f"{a['desc']} {a['id']}", subseq=False)
                    sc = None if sc is None else sc - 40
            if sc is not None:
                scored.append((-sc, k, a))
        scored.sort(key=lambda t: (t[0], t[1]))
        rows = [{"act": {"act": "app", "id": a["id"]}, "title": a["name"], "sub": a["desc"], "icon": a["icon"]}
                for _, _, a in scored[:60]]
        if q:
            rows.append({"act": {"act": "cmd", "text": q}, "title": f"コマンドとして実行: {q}", "sub": "",
                         "icon": "utilities-terminal-symbolic"})
        return "app", rows
    q = text.strip()
    scored = []
    for k, w in enumerate(windows):
        sc = fuzzy(q, f"{w['cls']} {w['title']}") if q else 0
        if sc is not None:
            scored.append((-sc, k, w))
    scored.sort(key=lambda t: (t[0], t[1]))
    return "win", [{"act": {"act": "win", "id": w["id"]}, "title": w["title"] or w["cls"], "sub": w["cls"],
                    "icon": w.get("icon", "")} for _, _, w in scored]


def layout_candidates(text, items):
    """型の選択画面の候補。items は [{"name", "expr", "n", "rects"}]。式（v( h( full）を直接打つこともできる。"""
    q = text.strip()
    scored = []
    for k, it in enumerate(items):
        sc = fuzzy(q, f"{it['name']} {it['expr']}") if q else 0
        if sc is not None:
            scored.append((-sc, k, it))
    scored.sort(key=lambda t: (t[0], t[1]))
    rows = [{"act": {"act": "layout", "name": it["name"]}, "title": it["name"],
             "sub": f"{it['expr']}　{it['n']}枚", "icon": None, "rects": it["rects"]} for _, _, it in scored]
    if re.match(r"(full|[vh]\s*\()", q) or is_shorthand_layout(q):        # 略記（1,2,2 や 1/1 など）も式として使える
        rows.append({"act": {"act": "layout", "name": q}, "title": f"式として使う: {q}", "sub": "", "icon": None,
                     "rects": []})
    return rows


def list_apps():
    apps = []
    for a in Gio.AppInfo.get_all():
        if not a.should_show():
            continue
        icon = a.get_icon()
        desc = getattr(a, "get_generic_name", lambda: None)() or a.get_description() or ""
        apps.append({"id": a.get_id(), "name": a.get_name(), "desc": desc, "icon": icon.to_string() if icon else ""})
    apps.sort(key=lambda a: a["name"].lower())
    return apps


def app_commandline(info):
    return re.sub(r"\s*%[a-zA-Z%]", "", info.get_commandline() or "").strip()


def launch_app(wc, app_id, timeout=12):
    """アプリを起動し、新しく現れた窓と起動コマンドを返す。"""
    info = (GioUnix.DesktopAppInfo if GioUnix else Gio.DesktopAppInfo).new(app_id)
    if info is None:
        raise WinError(f"アプリが見つかりません: {app_id}")
    cmdline = app_commandline(info)
    return launch(wc, cmdline, timeout), cmdline


TILE_PLACEHOLDER = "文字で絞り込み　先頭に ! でアプリを探して新規起動"
TILE_HINT = "↑↓ 選択 ・ Enter 決定 ・ Tab 決定して残りを自動 ・ Ctrl+S 空ける ・ Ctrl+B 戻る ・ Esc 終了"


def screen_info():
    """ミニ地図に描く、画面全体（全モニタ）と作業領域の位置。{"monitors": [(x, y, w, h)…], "work": (x, y, w, h)}。取れなければ None。"""
    try:
        monitors, logical = display_state()
        return {"monitors": [logical_rect(lm, monitors) for lm in logical], "work": work_area(load_config())}
    except (WinError, StopIteration):
        return None


def spawn_tilepick():
    """絞り込みの小窓（_tilepick）を起動する。画面の位置は環境変数で渡す（ミニ地図に全モニタを薄く描くため）。"""
    env = dict(os.environ)
    info = screen_info()
    if info:
        env["WIN_SCREEN"] = json.dumps(info)
    return subprocess.Popen([sys.executable, WIN_BIN, "_tilepick"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, bufsize=1, env=env)


def run_tilepick():
    """タイルごとに窓（先頭 ! でアプリ）を絞り込んで選ぶ小窓。親と 1 行 1 JSON でやり取りする。"""
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk, Pango

    MAP_W, MAP_H = 300, 150
    scr = None                                    # 全モニタを囲む枠 bbox・作業領域 work・各モニタ monitors（画面の座標）。無ければ従来どおり作業領域だけの地図
    try:
        info = json.loads(os.environ.get("WIN_SCREEN") or "null")
        if info and info["monitors"]:
            mons = [tuple(m) for m in info["monitors"]]
            bx, by = min(m[0] for m in mons), min(m[1] for m in mons)
            bw, bh = max(m[0] + m[2] for m in mons) - bx, max(m[1] + m[3] for m in mons) - by
            k = min(MAP_W / bw, MAP_H / bh)             # 縦横比を保って 300x150 に収める
            MAP_W, MAP_H = max(60, round(bw * k)), max(30, round(bh * k))
            scr = {"bbox": (bx, by, bw, bh), "work": tuple(info["work"]), "monitors": mons}
    except (ValueError, KeyError, TypeError):
        scr = None
    st = {"windows": [], "apps": [], "rows": [], "busy": True, "stage": "tile", "layouts": []}

    class App(Adw.Application):
        def __init__(self):
            super().__init__(application_id=TILEPICK_APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)

        # -- 親への返信
        def reply(self, act):
            if st["busy"]:
                return
            st["busy"] = True
            self.entry.set_sensitive(False)
            print(json.dumps(act, ensure_ascii=False), flush=True)
            if act.get("act") == "cancel":
                self.quit()

        # -- 画面の更新
        def set_notice(self, text):
            self.notice.set_text(text or "")
            self.notice.set_visible(bool(text))

        def draw_map(self, rects, cur, labels):
            child = self.map.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                self.map.remove(child)
                child = nxt
            if scr:
                bx, by, bw, bh = scr["bbox"]
                for mx, my, mw, mh in scr["monitors"]:           # 画面全体を薄く描く（タイルはその上）
                    mon = Gtk.Box()
                    mon.add_css_class("screen-box")
                    mon.set_size_request(max(4, round(mw / bw * MAP_W)), max(4, round(mh / bh * MAP_H)))
                    self.map.put(mon, round((mx - bx) / bw * MAP_W), round((my - by) / bh * MAP_H))
                wx, wy, ww, wh = scr["work"]                     # タイルの座標は作業領域に対する割合なので、地図全体に対する割合へ直す
                rects = [((wx + x * ww - bx) / bw, (wy + y * wh - by) / bh, w * ww / bw, h * wh / bh)
                         for x, y, w, h in rects]
            for i, (x, y, w, h) in enumerate(rects):
                label = labels[i] if labels else ""
                lab = Gtk.Label(label=f"{i + 1}" + (f"\n{label}" if label else ""), ellipsize=Pango.EllipsizeMode.END,
                                max_width_chars=1, justify=Gtk.Justification.CENTER)
                lab.add_css_class("tile-box")
                if i == cur:
                    lab.add_css_class("cur")
                elif label:
                    lab.add_css_class("done")
                lab.set_size_request(max(8, int(w * MAP_W) - 2), max(8, int(h * MAP_H) - 2))
                self.map.put(lab, int(x * MAP_W) + 1, int(y * MAP_H) + 1)

        def set_tile(self, m):
            self.title_lab.set_text(m.get("title") or f"タイル {m['index'] + 1} / {m['n']}　{m['layout']}")
            self.draw_map(m["rects"], m["index"], m["labels"])

        def on_row_selected(self, _lb, row):
            if st["stage"] == "layout" and row is not None and 0 <= row.get_index() < len(st["rows"]):
                self.draw_map(st["rows"][row.get_index()].get("rects", []), -1, None)

        def populate(self):
            if st["stage"] == "layout":
                rows = layout_candidates(self.entry.get_text(), st["layouts"])
                self.chip.set_text("型")
            else:
                mode, rows = tile_candidates(self.entry.get_text(), st["windows"], st["apps"])
                self.chip.set_text("アプリを新規起動" if mode == "app" else "開いている窓")
            st["rows"] = rows
            while (r := self.listbox.get_row_at_index(0)) is not None:
                self.listbox.remove(r)
            for r in rows:
                box = Gtk.Box(spacing=10, margin_top=5, margin_bottom=5, margin_start=10, margin_end=10)
                if "icon" in r:                               # 窓・アプリの行（型の行には出さない）
                    box.append(icon_widget(Gtk, Gdk, r["icon"]))
                title = Gtk.Label(label=r["title"], xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                                  max_width_chars=44)
                sub = Gtk.Label(label=r["sub"], xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=22)
                sub.add_css_class("dim-label")
                box.append(title)
                box.append(sub)
                row = Gtk.ListBoxRow(can_focus=False)
                row.set_child(box)
                self.listbox.append(row)
            if not rows:
                self.listbox.append(Gtk.ListBoxRow(can_focus=False, selectable=False, child=Gtk.Label(
                    label=("一致する型がありません" if st["stage"] == "layout"
                           else "一致する窓がありません（先頭に ! でアプリを探す）"), margin_top=14, margin_bottom=14)))
            else:
                self.listbox.select_row(self.listbox.get_row_at_index(0))
            self.scroller.get_vadjustment().set_value(0)

        def move(self, d):
            rows = st["rows"]
            if not rows:
                return
            sel = self.listbox.get_selected_row()
            i = max(0, min(len(rows) - 1, (sel.get_index() if sel else 0) + d))
            row = self.listbox.get_row_at_index(i)
            self.listbox.select_row(row)
            adj, a = self.scroller.get_vadjustment(), row.get_allocation()
            if a.y < adj.get_value():
                adj.set_value(a.y)
            elif a.y + a.height > adj.get_value() + adj.get_page_size():
                adj.set_value(a.y + a.height - adj.get_page_size())

        def choose(self, rest):
            row = self.listbox.get_selected_row()
            if row is None or not st["rows"]:
                if rest:
                    self.reply({"act": "none", "rest": True})
                return
            act = dict(st["rows"][row.get_index()]["act"])
            if rest:
                act["rest"] = True
            self.reply(act)

        # -- 親からの命令
        def on_message(self, m):
            c = m.get("cmd")
            if c == "layouts":
                st["stage"], st["layouts"] = "layout", m["items"]
                self.title_lab.set_text("型を選ぶ")
                self.entry.set_placeholder_text("型の名前で絞り込み（式も打てます: 1,2,2・1/1・v(1,h(1,1)) など）")
                self.hint.set_text("↑↓ 選択（ミニ地図が変わる） ・ Enter 決定してタイルごとに選ぶ ・ "
                                   "Tab 決定して前面の窓で自動配置 ・ Esc 閉じる")
                self.set_notice(m.get("notice"))
                st["busy"] = False
                self.entry.set_sensitive(True)
                self.entry.set_text("")
                self.populate()
                self.entry.grab_focus_without_selecting()
            elif c == "tile":
                st["stage"] = "tile"
                self.entry.set_placeholder_text(m.get("placeholder") or TILE_PLACEHOLDER)
                self.hint.set_text(m.get("hint") or TILE_HINT)
                st["windows"] = m["windows"]
                if "apps" in m:
                    st["apps"] = m["apps"]
                self.set_tile(m)
                self.set_notice(m.get("notice"))
                st["busy"] = False
                self.entry.set_sensitive(True)
                self.entry.set_text("")
                self.populate()
                self.entry.grab_focus_without_selecting()
            elif c == "busy":
                st["busy"] = True
                self.entry.set_sensitive(False)
                self.set_notice(m.get("text"))
            elif c == "quit":
                self.quit()

        def got_line(self, stream, res):
            try:
                line, _ = stream.read_line_finish_utf8(res)
            except GLib.Error:
                line = None
            if line is None:
                self.quit()
                return
            if line.strip():
                self.on_message(json.loads(line))
            stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self.got_line)

        def do_activate(self):
            css = Gtk.CssProvider()
            css.load_from_string(
                ".tile-box { border: 1px solid alpha(currentColor, .35); border-radius: 4px; font-size: 8pt; }"
                ".screen-box { background: alpha(currentColor, .05); border: 1px solid alpha(currentColor, .18); border-radius: 3px; }"
                ".tile-box.cur { background: @accent_bg_color; color: @accent_fg_color; border-color: @accent_bg_color; }"
                ".tile-box.done { background: alpha(currentColor, .12); }"
                ".mode-chip { padding: 2px 10px; border-radius: 12px; background: alpha(currentColor, .12); font-size: 9pt; }")
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.title_lab = Gtk.Label(xalign=0, margin_start=14, margin_top=10)
            self.title_lab.add_css_class("heading")
            self.map = Gtk.Fixed(halign=Gtk.Align.CENTER, margin_top=8, margin_bottom=6)
            self.map.set_size_request(MAP_W, MAP_H)
            self.chip = Gtk.Label()
            self.chip.add_css_class("mode-chip")
            self.entry = Gtk.Entry(hexpand=True, placeholder_text=TILE_PLACEHOLDER)
            self.entry.set_sensitive(False)
            row = Gtk.Box(spacing=8, margin_start=12, margin_end=12)
            row.append(self.chip)
            row.append(self.entry)
            self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.BROWSE, can_focus=False)
            self.listbox.add_css_class("boxed-list")
            self.listbox.connect("row-activated", lambda _lb, _r: self.choose(False))
            self.listbox.connect("row-selected", self.on_row_selected)
            self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=self.listbox,
                                               min_content_height=300, max_content_height=300,
                                               margin_top=8, margin_start=12, margin_end=12)
            self.notice = Gtk.Label(xalign=0, wrap=True, margin_top=6, margin_start=14, margin_end=14, visible=False)
            self.notice.add_css_class("error")
            hint = self.hint = Gtk.Label(margin_top=8, margin_bottom=10, label=TILE_HINT)
            hint.add_css_class("dim-label")
            hint.add_css_class("caption")
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            for wdg in (self.title_lab, self.map, row, self.scroller, self.notice, hint):
                outer.append(wdg)
            header = Adw.HeaderBar(title_widget=Gtk.Label(label="窓を並べる"), show_end_title_buttons=False)
            view = Adw.ToolbarView(content=outer)
            view.add_top_bar(header)
            win = Adw.ApplicationWindow(application=self, title="win-tilepick", default_width=720, content=view)

            def on_key(_c, keyval, _kc, state_mask):
                name = Gdk.keyval_name(keyval)
                ctrl = bool(state_mask & Gdk.ModifierType.CONTROL_MASK)
                if name == "Escape":
                    self.reply({"act": "cancel"})
                elif name == "Down" or (ctrl and name in ("n", "j")):
                    self.move(1)
                elif name == "Up" or (ctrl and name in ("p", "k")):
                    self.move(-1)
                elif name in ("Return", "KP_Enter"):
                    self.choose(False)
                elif name in ("Tab", "ISO_Left_Tab"):
                    self.choose(True)
                elif ctrl and name == "s" and st["stage"] == "tile":
                    self.reply({"act": "skip"})
                elif ctrl and name == "b" and st["stage"] == "tile":
                    self.reply({"act": "back"})
                elif ctrl and name == "u":
                    self.entry.set_text("")
                else:
                    return False
                return True

            ctrl = Gtk.EventControllerKey()
            ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            ctrl.connect("key-pressed", on_key)
            win.add_controller(ctrl)
            self.entry.connect("changed", lambda _e: self.populate() if not st["busy"] else None)
            win.connect("close-request", lambda _w: (self.reply({"act": "cancel"}), self.quit(), True)[2])
            win.present()
            unix = (GioUnix.InputStream if GioUnix else Gio.UnixInputStream).new(0, False)
            stream = Gio.DataInputStream.new(unix)
            stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self.got_line)

    run_with_ascii_input(lambda: App().run([]))


PICK_HINT = "↑↓ 選択 ・ Enter 決定 ・ 先頭 ! でアプリを探して新しく起動 ・ Esc 取り消す"


def pick_interactive(wc, title="窓を選ぶ", rects=None, index=0, labels=None, allow_launch=True, exclude=()):
    """layout -i と同じ小窓で窓を 1 枚選ぶ（先頭 ! でアプリを起動して、その窓）。選んだ窓、取り消しなら None。
    rects（作業領域を 0〜1 にした (x, y, 幅, 高さ) のリスト）と index を渡すと、小窓の地図でそのタイルを強調する。"""
    if rects is None:                                     # 地図には、いまの並び（どこに何があるか）を出す。強調はしない
        rects, labels = slot_map(wc)
        index = -1
    rects = rects or [(0.0, 0.0, 1.0, 1.0)]
    exclude = set(exclude)
    child = spawn_tilepick()

    def send(msg):
        child.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        child.stdin.flush()

    def msg(notice="", first=False):
        m = {"cmd": "tile", "index": index, "n": len(rects), "layout": "", "rects": rects, "notice": notice,
             "labels": labels or [""] * len(rects), "title": title,
             "hint": PICK_HINT if allow_launch else "↑↓ 選択 ・ Enter 決定 ・ Esc 取り消す",
             "placeholder": TILE_PLACEHOLDER if allow_launch else "文字で絞り込み",
             "windows": [{"id": w["id"], "cls": w.get("wm_class") or "", "title": (w.get("title") or "")[:90],
                           "icon": icon_for_class(w.get("wm_class"))}
                         for w in usable_windows(wc) if w["id"] not in exclude]}
        if first:
            m["apps"] = list_apps() if allow_launch else []
        return m

    wid = None
    try:
        send(msg(first=True))
        wid = center_and_focus(wc, child, TILEPICK_APP_ID)
        while True:
            line = child.stdout.readline()
            try:
                res = json.loads(line) if line else {"act": "cancel"}
            except ValueError:
                res = {"act": "cancel"}
            act = res.get("act")
            if act == "cancel":
                return None
            try:
                if act == "win":
                    w = next((x for x in normal_windows(wc) if x["id"] == res["id"]), None)
                    if w is None:
                        raise WinError("その窓はもう閉じられました")
                    return w
                if act in ("app", "cmd") and not allow_launch:
                    raise WinError("ここでは新しく起動できません。開いている窓から選んでください")
                if act in ("app", "cmd"):
                    send({"cmd": "busy", "text": "起動しています…"})
                    return launch_app(wc, res["id"])[0] if act == "app" else launch(wc, res["text"], 12)
            except WinError as e:
                send(msg(str(e)))
            else:
                send(msg())                               # 空ける・戻る などは、1 枚選ぶときは使わない
            if wid:
                with contextlib.suppress(WinError):
                    wc.simple("Activate", wid)
    finally:
        with contextlib.suppress(OSError, ValueError):
            send({"cmd": "quit"})
        try:
            child.wait(3)
        except subprocess.TimeoutExpired:
            child.kill()


def slot_map(wc, n=None):
    """いまの並び（逆算）の、小窓の地図用のタイル（0〜1 の割合）と、各タイルの窓のクラス名。"""
    cfg = load_config()
    cur = current_tiles(wc, cfg)
    if cur["tree"] is None:
        return None, None
    order = tile_order(cur, cfg)[1]
    box = {it[0]: it[1:5] for it in cur["items"]}
    rects = [(box[i][0], box[i][1], box[i][2] - box[i][0], box[i][3] - box[i][1]) for i in order]
    labels = [(cur["by_id"][i].get("wm_class") or "")[:14] for i in order]
    return rects, labels


def gui_layout_flow(wc, args, cfg, area, gap):
    """型の名前なしで呼ばれたとき: 小窓で型を選び、Enter ならタイルごとの選択へ、Tab なら前面の窓で自動配置。"""
    if args.windows or args.dry_run:
        raise WinError("型を省くときは、窓の指定や -n は使えません")
    ax, ay, aw, ah = area
    items = []
    for name, expr in cfg["layouts"].items():
        r = compute_rects(expr, area, 0)
        items.append({"name": name, "expr": expr, "n": len(r),
                      "rects": [((x - ax) / aw, (y - ay) / ah, w / aw, h / ah) for x, y, w, h in r]})
    child = spawn_tilepick()

    def send(msg):
        child.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        child.stdin.flush()

    def close_child():
        try:
            send({"cmd": "quit"})
        except (OSError, ValueError):
            pass
        try:
            child.wait(3)
        except subprocess.TimeoutExpired:
            child.kill()

    handed_over = False
    try:
        send({"cmd": "layouts", "items": items})
        wid = center_and_focus(wc, child, TILEPICK_APP_ID)
        while True:
            line = child.stdout.readline()
            try:
                res = json.loads(line) if line else {"act": "cancel"}
            except ValueError:
                res = {"act": "cancel"}
            if res.get("act") != "layout":
                return 0
            expr = resolve_layout(cfg, res["name"])
            try:
                rects = compute_rects(expr, area, gap)
            except WinError as e:
                send({"cmd": "layouts", "items": items, "notice": str(e)})
                wc.simple("Activate", wid)
                continue
            args.layout = res["name"]
            if res.get("rest"):
                close_child()
                time.sleep(0.3)                      # 小窓が閉じて、元の窓にフォーカスが戻るのを待つ
                args.interactive, args.windows = False, []
                return cmd_layout(args)
            handed_over = True
            return gui_interactive(wc, args, expr, rects, area, child, [wid])
    finally:
        if not handed_over:
            close_child()


def gui_interactive(wc, args, expr, rects, area, child=None, child_wid=None):
    n = len(rects)
    ax, ay, aw, ah = area
    norm = [((x - ax) / aw, (y - ay) / ah, w / aw, h / ah) for x, y, w, h in rects]
    try:
        me = focused(wc)["id"]
    except WinError:
        me = None
    assigned = [None] * n                    # (窓, 再現用の指定) か None
    procs = start_placeholders(wc, rects) if args.preview else []
    reuse = child is not None                # 型の選択画面から引き継いだ小窓
    if not reuse:
        child = spawn_tilepick()
        child_wid = [None]

    def send(msg):
        child.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        child.stdin.flush()

    def refocus():
        if child_wid[0]:
            try:
                wc.simple("Activate", child_wid[0])
            except WinError:
                pass

    def tile_msg(i, notice="", first=False):
        taken = {a[0]["id"] for a in assigned if a}
        msg = {"cmd": "tile", "index": i, "n": n, "layout": args.layout, "rects": norm, "notice": notice,
               "labels": [(a[0].get("wm_class") or "")[:14] if a else "" for a in assigned],
               "windows": [{"id": w["id"], "cls": w.get("wm_class") or "", "title": (w.get("title") or "")[:90],
                           "icon": icon_for_class(w.get("wm_class"))}
                           for w in usable_windows(wc) if w["id"] not in taken]}
        if first:
            msg["apps"] = list_apps()
        return msg

    def read_reply():
        line = child.stdout.readline()
        if not line:
            return {"act": "cancel"}
        try:
            return json.loads(line)
        except ValueError:
            return {"act": "cancel"}

    def place_checked(w, i):
        got = place_settled(wc, w["id"], rects[i])
        return (f"タイル {i + 1} の窓は希望の大きさにならず {got[2]}x{got[3]} です（最小サイズなど）" if got else "")

    i, notice, auto_from = 0, "", None
    try:
        send(tile_msg(i, first=True))
        if not reuse:
            child_wid[0] = center_and_focus(wc, child, TILEPICK_APP_ID)
        while True:
            res = read_reply()
            act, notice = res.get("act"), ""
            if act == "cancel":
                break
            chosen = None
            try:
                if act == "win":
                    w = next((x for x in normal_windows(wc) if x["id"] == res["id"]), None)
                    if w is None:
                        raise WinError("その窓はもう閉じられました")
                    chosen = (w, selector_for(w, normal_windows(wc)))
                elif act in ("app", "cmd"):
                    send({"cmd": "busy", "text": "起動しています…"})
                    if act == "app":
                        w, cmdline = launch_app(wc, res["id"])
                    else:
                        w, cmdline = launch(wc, res["text"], 12), res["text"]
                    chosen = (w, "!" + cmdline)
                elif act == "skip":
                    i += 1
                elif act == "back":
                    i = max(0, i - 1)
                    assigned[i] = None
            except WinError as e:
                notice = str(e)
                send(tile_msg(i, notice))
                refocus()
                continue
            if chosen:
                notice = place_checked(chosen[0], i)
                assigned[i] = chosen
                i += 1
            if res.get("rest"):
                auto_from = i
                taken = {a[0]["id"] for a in assigned if a}
                others = [w for w in usable_windows(wc) if w["id"] not in taken]
                for j in range(i, n):
                    if not others:
                        break
                    w = others.pop(0)
                    place_checked(w, j)
                    assigned[j] = (w, selector_for(w, normal_windows(wc)))
                break
            if i >= n:
                break
            send(tile_msg(i, notice))
            refocus()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            send({"cmd": "quit"})
        except (OSError, ValueError):
            pass
        try:
            child.wait(3)
        except subprocess.TimeoutExpired:
            child.kill()
        stop_placeholders(procs)
        try:
            raise_group(wc, [a[0] for a in assigned if a], me)
        except WinError:
            pass
    explicit = assigned[:auto_from] if auto_from is not None else assigned
    toks = [shlex.quote(a[1]) if a else "-" for a in explicit]
    while toks and toks[-1] == "-":
        toks.pop()
    if auto_from is not None:
        toks.append("...")
    if toks:
        recipe = "layout " + shlex.quote(args.layout) + " " + " ".join(toks)
        print("同じ配置を再現するコマンド:\n  win " + recipe)
        save_history(recipe)
    return 0


def interactive(wc, args, expr, rects, area):
    n = len(rects)
    me = focused(wc)
    assigned = [None] * n      # (window, recipe) か None
    labels = [""] * n
    procs = [] if args.no_preview else start_placeholders(wc, rects)
    wc.simple("Activate", me["id"])
    print(f"型 {args.layout}（{expr}）: タイル {n} 枚")
    print("入力: 窓の番号 / 検索語（既存の窓）/ !コマンド（新しく起動）/ p 一覧から選ぶ / 空行（空けておく）/ < 戻る / q 終了")
    i = 0
    try:
        while i < n:
            set_current(i + 1)
            print("\n" + ascii_map(rects, area, i, labels))
            taken = {a[0]["id"] for a in assigned if a}
            pool = [w for w in usable_windows(wc) if w["id"] not in taken]
            for k, w in enumerate(pool, 1):
                mark = "（このターミナル）" if w["id"] == me["id"] else ""
                print(f"  {k:>2}  {w.get('wm_class')}  「{(w.get('title') or '')[:40]}」{mark}")
            try:
                line = ask_line(wc, pool, i, n, args.pick)
            except EOFError:
                line = "q"
            if line == "q":
                break
            if line == "<":
                if i > 0:
                    i -= 1
                    assigned[i], labels[i] = None, ""
                continue
            if line == "":
                i += 1
                continue
            try:
                if line.startswith("!"):
                    w = launch(wc, line[1:].strip())
                    recipe = "!" + line[1:].strip()
                elif line.isdigit() and 1 <= int(line) <= len(pool):
                    w = pool[int(line) - 1]
                    recipe = selector_for(w, normal_windows(wc))
                else:
                    found = find_windows(wc, line, pool)
                    if not found:
                        print(f"  見つかりません: {line}")
                        continue
                    if len(found) > 1:
                        print(f"  {len(found)} 件に一致しました。番号で選んでください:")
                        for w in found:
                            print(f"    {pool.index(w) + 1:>2}  {describe(w)}")
                        continue
                    w = found[0]
                    recipe = selector_for(w, normal_windows(wc))
            except WinError as e:
                print(f"  {e}")
                continue
            apply_one(wc, w["id"], rects[i], i + 1)
            wc.simple("Activate", me["id"])
            assigned[i] = (w, recipe)
            labels[i] = (w.get("wm_class") or "")[:20]
            i += 1
    except KeyboardInterrupt:
        print("\n中断しました（ここまでの配置は残ります）")
    finally:
        stop_placeholders(procs)
        try:
            raise_group(wc, [a[0] for a in assigned if a], me["id"])
        except WinError:
            pass
    toks = [shlex.quote(a[1]) if a else "-" for a in assigned]
    while toks and toks[-1] == "-":
        toks.pop()
    print("\n同じ配置を再現するコマンド:")
    print("  win layout " + shlex.quote(args.layout) + (" " + " ".join(toks) if toks else ""))
    return 0


def run_tile(idx, total):
    """対話モードで各タイルの位置に出す、番号つきの目印の窓。"""
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    parent = os.getppid()

    class App(Adw.Application):
        def __init__(self):
            super().__init__(application_id=TILE_APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)

        def do_activate(self):
            css = Gtk.CssProvider()
            css.load_from_string(
                ".tile-num { font-size: 96pt; font-weight: 800; opacity: .35; }"
                ".tile-cur { background: @accent_bg_color; }"
                ".tile-cur .tile-num { opacity: .9; color: @accent_fg_color; }")
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            box = Gtk.Box()
            label = Gtk.Label(label=str(idx), hexpand=True, vexpand=True)
            label.add_css_class("tile-num")
            box.append(label)
            win = Adw.ApplicationWindow(application=self, title=f"win-tile {idx}",
                                        default_width=240, default_height=160, content=box)

            def tick():
                if os.getppid() != parent:
                    self.quit()
                    return False
                try:
                    cur = int(open(CURRENT_FILE).read().strip())
                except (OSError, ValueError):
                    cur = 0
                (box.add_css_class if cur == idx else box.remove_css_class)("tile-cur")
                return True

            GLib.timeout_add(200, tick)
            win.present()

    App().run([])


# ---------------------------------------------------------------- その他の命令

def cmd_list(args):
    wc = WindowCalls()
    rows = []
    for w in (wc.list() if args.all else normal_windows(wc)):
        d = wc.details(w["id"])
        flags = ("*" if w.get("focus") else "") + ("m" if d.get("minimized") else "")
        rows.append((str(w["id"]), (w.get("wm_class") or "")[:24], (w.get("title") or "")[:36],
                     str(w.get("workspace")), str(d["x"]), str(d["y"]), str(d["width"]), str(d["height"]), flags))
    head = ("ID", "CLASS", "TITLE", "WS", "X", "Y", "W", "H", "")
    widths = [max(len(r[k]) for r in rows + [head]) for k in range(len(head))]
    for r in [head] + rows:
        print("  ".join(c.ljust(widths[k]) for k, c in enumerate(r)).rstrip())
    return 0


def cmd_layouts(args):
    cfg = load_config()
    for name, expr in cfg["layouts"].items():
        n = len(leaf_rects(LayoutParser(expr).parse(), (0, 0, 1, 1)))
        print(f"{name:<10} {expr:<24} タイル {n} 枚")
    print(f"\n作業領域の余白: {cfg['insets']}  タイル間の隙間: {cfg['gap']}px  設定: {CONFIG}")
    return 0


def cmd_focus(args):
    wc = WindowCalls()
    found = find_windows(wc, args.selector, normal_windows(wc)[::-1])
    if not found:
        raise WinError(f"窓が見つかりません: {args.selector}")
    group = found if is_multi(args.selector) else found[:1]       # 複数の指定なら全部を前面へ（先頭がいちばん上）
    for w in reversed(group):
        if wc.details(w["id"]).get("minimized"):
            wc.simple("Unminimize", w["id"])
        wc.simple("Activate", w["id"])
    for w in group:
        print(describe(w))
    return 0


# ---------------------------------------------------------------- 上下左右のフォーカス移動

def visible_windows(wc):
    """今のワークスペースで、最小化されておらず、他の窓に隠れきっていない窓と、その枠。"""
    items = []
    for w in normal_windows(wc):          # 下 → 上
        if not w.get("in_current_workspace"):
            continue
        d = wc.details(w["id"])
        if d.get("minimized"):
            continue
        items.append((w, (d["x"], d["y"], d["width"], d["height"])))

    def covered(px, py, rects):
        return any(x <= px < x + rw and y <= py < y + rh for x, y, rw, rh in rects)

    out = []
    for k, (w, (x, y, rw, rh)) in enumerate(items):
        above = [r for _, r in items[k + 1:]]
        points = [(x + rw * a, y + rh * b) for a in (.1, .3, .5, .7, .9) for b in (.1, .3, .5, .7, .9)]
        if w.get("focus") or any(not covered(px, py, above) for px, py in points):
            out.append((w, (x, y, rw, rh)))
    return out


EPS = 8  # 中心がこれ以内しかずれていない窓は、その向きにあるとはみなさない（px）


def nav_pick(current, others, direction):
    """current から direction の向きにある、いちばん自然な窓を選ぶ。見つからなければ None。

    向きに垂直な方向で重なっている窓を優先し、その中で近いもの。同点なら上・左を先に。
    """
    cx, cy, cw, ch = current
    ccx, ccy = cx + cw / 2, cy + ch / 2
    best, best_key = None, None
    for w, (x, y, rw, rh) in others:
        mx, my = x + rw / 2, y + rh / 2
        if direction in ("left", "right"):
            ahead = mx > ccx + EPS if direction == "right" else mx < ccx - EPS
            overlap = min(cy + ch, y + rh) - max(cy, y) > 0
            gap = (x - (cx + cw)) if direction == "right" else (cx - (x + rw))
            perp = abs(my - ccy)
        else:
            ahead = my > ccy + EPS if direction == "down" else my < ccy - EPS
            overlap = min(cx + cw, x + rw) - max(cx, x) > 0
            gap = (y - (cy + ch)) if direction == "down" else (cy - (y + rh))
            perp = abs(mx - ccx)
        if not ahead:
            continue
        key = (0 if overlap else 1, max(0, gap), perp, y, x)
        if best_key is None or key < best_key:
            best, best_key = w, key
    return best


def cmd_nav(args):
    wc = WindowCalls()
    if args.direction in ("next", "prev"):               # いまの並びの番号順に回る（最後の次は最初）
        cfg = load_config()
        cur = current_tiles(wc, cfg)
        if cur["tree"] is None:
            return 0
        order = tile_order(cur, cfg)[1]
        try:
            i = order.index(focused(wc)["id"])
        except (WinError, ValueError):
            i = -1 if args.direction == "next" else 0     # 並びの外にいるとき: next は 1 番目、prev は最後へ
        wc.simple("Activate", order[(i + (1 if args.direction == "next" else -1)) % len(order)])
        return 0
    vis = visible_windows(wc)
    cur = next(((w, r) for w, r in vis if w.get("focus")), None)
    if cur is None:
        return 0                          # 前面が通常の窓でなければ何もしない
    best = nav_pick(cur[1], [(w, r) for w, r in vis if w["id"] != cur[0]["id"]], args.direction)
    if best is not None:
        wc.simple("Activate", best["id"])
    return 0


# ---------------------------------------------------------------- コマンド入力（win prompt）

SUBCOMMANDS = [("here", "選んだ窓を今の窓と同じ位置・大きさにして前面へ"), ("focus", "窓を前面に出す"), ("nav", "上下左右の窓へ"), ("layout", "窓を分割配置する"),
               ("pick", "窓の一覧から選ぶ"), ("list", "窓の一覧を表示"), ("layouts", "型の一覧を表示"),
               ("move", "窓を移動する"), ("size", "大きさを変える"), ("state", "最大化・最小化・常に手前"),
               ("max", "窓を最大化する"), ("unmax", "最大化を戻す"), ("min", "窓を最小化する"),
               ("unmin", "最小化を戻す"), ("close", "窓を閉じる"), ("run", "登録したコマンド・保存した並びを実行"),
               ("save", "いまの窓の並びを名前をつけて保存"), ("set", "保存した並び（セット）を選んで適用"),
               ("term", "端末を作業ディレクトリのタブつきで開く"), ("browse", "Firefox を URL のタブつきで開く"),
               ("config", "設定の画面を開く"), ("help", "命令の書式と説明を表示")]
STATE_ACTIONS = ["max", "unmax", "min", "unmin", "above", "unabove"]
SHOW_OUTPUT = {"list", "layouts", "help"}   # 結果を入力欄の下に出す命令


def run_with_ascii_input(run):
    """run() の間だけ、IBus を Mozc を通さない配列だけのエンジンにして、終わったら戻す（英字がかな・全角にならないように。
    mozc-off でも Mozc の中が全角・かなのことがあった）。切り替え（ibus の起動 2 回、約 0.08 秒）は窓を作るのと同時に進める。"""
    state = {"prev": ""}

    def switch():
        state["prev"] = ibus_engine()
        if state["prev"].startswith("mozc"):
            ibus_engine("xkb:jp::jpn")

    th = threading.Thread(target=switch, daemon=True)
    th.start()
    try:
        return run()
    finally:
        th.join()
        if state["prev"].startswith("mozc"):
            ibus_engine(state["prev"])


def ibus_engine(name=None):
    """IBus の入力エンジン名を返す。name があれば先に切り替える。ibus が無ければ空文字。"""
    try:
        if name:
            subprocess.run(["ibus", "engine", name], capture_output=True)
        return subprocess.run(["ibus", "engine"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def load_history():
    try:
        with open(HISTORY, encoding="utf-8") as f:
            return [ln.rstrip("\n") for ln in f if ln.strip()]
    except OSError:
        return []


def save_history(line):
    hist = [h for h in load_history() if h != line] + [line]
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    with open(HISTORY, "w", encoding="utf-8") as f:
        f.write("\n".join(hist[-100:]) + "\n")


def suggest(text, spec):
    """入力中の文字列に対する候補 [(挿入する語, 説明)]。最後の語を置き換える。"""
    parts = text.split(" ")
    cur, first = parts[-1], parts[0]
    ext = spec.get("ext", {})                          # 拡張の命令 {名前: {"summary", "win": [位置引数ごとに窓か], "rep": 残りが窓か}}
    if len(parts) == 1:
        return [(c + " ", d) for c, d in SUBCOMMANDS if c.startswith(cur)] + \
               [(n + " ", e["summary"]) for n, e in ext.items() if n.startswith(cur)]
    prev = parts[-2]
    if first == "help" and len(parts) == 2:
        topics = [("api", "拡張で使える関数の一覧"), ("commands", "登録したコマンドの一覧"), ("sets", "セットの一覧"),
                  ("layouts", "型の一覧")]
        return [(t + " ", d) for t, d in topics if t.startswith(cur)] + \
               [(c + " ", d) for c, d in SUBCOMMANDS if c.startswith(cur)] + \
               [(n + " ", e["summary"]) for n, e in ext.items() if n.startswith(cur)]
    if first == "nav":
        return [(d + " ", "") for d in ("next", "prev", "left", "right", "up", "down") if d.startswith(cur)]
    if first in ("run", "set") and len(parts) == 2:
        pool = spec.get("commands", {}) if first == "run" else spec.get("sets", {})
        return [(shlex.quote(n) + " ", (set_summary(c) if first == "set" else describe_command(c))[:40])
                for n, c in pool.items() if n.startswith(cur)]
    if first == "state" and len(parts) == 2:
        return [(a + " ", "") for a in STATE_ACTIONS if a.startswith(cur)]
    if first == "layout" and len(parts) == 2:
        return [(n + " ", f"{e}") for n, e in spec["layouts"].items() if n.startswith(cur)]
    if cur.startswith("-") and first in SIGNATURES:
        return [(p[1] + " ", p[3] if p[0] == "opt" else p[2]) for p in SIGNATURES[first][0]
                if p[0] in ("opt", "flag") and p[1].startswith(cur)]
    if cur.startswith("-") and first in ext:
        return [(p[1] + " ", p[-1]) for p in spec.get("ext_sig", {}).get(first, [[]])[0]
                if p[0] in ("opt", "flag") and p[1].startswith(cur)]
    wants_window = first in ("focus", "here") or prev in ("-w", "--window") or (first == "layout" and len(parts) > 2)
    if first in ext:                                   # 拡張の命令は、いま打っている位置の引数が窓なら
        k = len([t for t in parts[1:-1] if t and not t.startswith("-")])
        kinds = ext[first]["win"]
        wants_window = kinds[k] if k < len(kinds) else ext[first]["rep"]
    if wants_window and cur.lower().startswith("@class:"):    # @class: の後は、いま開いている窓のクラス名
        classes = dict.fromkeys(w["cls"] for w in spec["windows"] if w["cls"])
        return [(f"@class:{c} ", "【複数】このクラスの窓すべて") for c in classes if f"@class:{c}".lower().startswith(cur.lower())]
    if wants_window:
        low = cur.lower().lstrip("!")
        ats = [(s, d) for s, d in AT_SELECTORS if s.startswith(cur)] if cur.startswith("@") or not cur else []
        return [(shlex.quote(w["sel"]) + " ", f"{w['cls']} — {w['title']}") for w in spec["windows"]
                if not cur.startswith("@") and (not low or low in (w["cls"] + " " + w["title"]).lower())] + \
               [(s if s.endswith(":") else s + " ", d) for s, d in ats]
    return []


def run_prompt():
    """コマンドを 1 行打つ小さな窓。結果は 1 行の JSON（{"act": "run", "line": ...} か cancel）で標準出力へ。"""
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    spec = json.load(sys.stdin)
    SIGNATURES.update({n: (parts, summary) for n, (parts, summary) in spec.get("ext_sig", {}).items()})
    hist, hist_pos = spec.get("history", []), [None]

    class App(Adw.Application):
        def __init__(self):
            super().__init__(application_id=PROMPT_APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)

        def finish(self, act):
            print(json.dumps(act), flush=True)
            self.quit()

        def do_activate(self):
            try:
                from gi.repository import GLibUnix
                GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (self.quit(), False)[1])
            except ImportError:
                GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (self.quit(), False)[1])
            entry = Gtk.Entry(hexpand=True, text=spec.get("initial", ""),
                              placeholder_text="例: layout quad / focus firefox / nav right")
            entry.set_position(-1)
            row = Gtk.Box(spacing=8, margin_top=10, margin_start=12, margin_end=12)
            prefix = Gtk.Label(label="win")
            prefix.add_css_class("heading")
            row.append(prefix)
            row.append(entry)
            sugg = Gtk.ListBox(selection_mode=Gtk.SelectionMode.BROWSE, can_focus=False, margin_top=6,
                               margin_start=12, margin_end=12)
            sugg.add_css_class("boxed-list")
            sugg_box = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=sugg,
                                          min_content_height=215, max_content_height=215)
            shown = []                      # 表示中の候補 [(挿入する語, 説明)]

            sig = Gtk.Label(xalign=0, wrap=True, use_markup=True, visible=False, margin_top=6, margin_start=14, margin_end=14)
            sig.add_css_class("caption")

            def refresh(*_):
                while (r := sugg.get_row_at_index(0)) is not None:
                    sugg.remove(r)
                shown[:] = suggest(entry.get_text(), spec)[:8]
                markup = signature_markup(entry.get_text())     # 打っている命令の書式（いま打っている引数は太字）
                sig.set_markup(markup or "")
                sig.set_visible(bool(markup))
                for ins, desc in shown:
                    box = Gtk.Box(spacing=12, margin_top=4, margin_bottom=4, margin_start=10, margin_end=10)
                    a = Gtk.Label(label=ins.strip(), xalign=0, width_chars=14)
                    b = Gtk.Label(label=desc, xalign=0, hexpand=True, ellipsize=3, max_width_chars=50)
                    b.add_css_class("dim-label")
                    box.append(a)
                    box.append(b)
                    r = Gtk.ListBoxRow(can_focus=False)
                    r.set_child(box)
                    sugg.append(r)
                if shown:
                    sugg.select_row(sugg.get_row_at_index(0))

            def move(d):
                if shown:
                    sel = sugg.get_selected_row()
                    sugg.select_row(sugg.get_row_at_index(((sel.get_index() if sel else 0) + d) % len(shown)))

            def complete():
                sel = sugg.get_selected_row()
                if not shown or sel is None:
                    return
                parts = entry.get_text().split(" ")
                parts[-1] = shown[sel.get_index()][0]
                entry.set_text(" ".join(parts))
                entry.set_position(-1)

            def history(d):
                if not hist:
                    return
                pos = len(hist) if hist_pos[0] is None else hist_pos[0]
                pos = max(0, min(len(hist), pos + d))
                hist_pos[0] = pos
                entry.set_text(hist[pos] if pos < len(hist) else "")
                entry.set_position(-1)

            entry.connect("changed", refresh)
            entry.connect("activate", lambda _e: self.finish({"act": "run", "line": entry.get_text()}))

            def on_key(_c, keyval, _kc, state):
                name = Gdk.keyval_name(keyval)
                ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
                if name == "Escape":
                    self.finish({"act": "cancel"})
                elif name in ("Tab", "ISO_Left_Tab"):
                    complete()
                elif ctrl and name == "Up":
                    history(-1)
                elif ctrl and name == "Down":
                    history(1)
                elif name == "Down" or (ctrl and name == "n"):
                    move(1)
                elif name == "Up" or (ctrl and name == "p"):
                    move(-1)
                else:
                    return False
                return True

            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_bottom=10)
            outer.append(row)
            outer.append(sig)
            outer.append(sugg_box)
            for text, css in ((spec.get("error"), "error"), (spec.get("info"), "monospace")):
                if text:
                    lab = Gtk.Label(label=text, xalign=0, wrap=True, margin_top=8, margin_start=14, margin_end=14,
                                    selectable=True)
                    lab.add_css_class(css)
                    outer.append(lab)
            hint = Gtk.Label(label="Tab 補完 ・ ↑↓ 候補 ・ Ctrl+↑↓ 履歴 ・ Enter 実行 ・ Esc 閉じる", margin_top=8)
            hint.add_css_class("dim-label")
            hint.add_css_class("caption")
            outer.append(hint)
            header = Adw.HeaderBar(title_widget=Gtk.Label(label="窓の操作"), show_end_title_buttons=False)
            view = Adw.ToolbarView(content=outer)
            view.add_top_bar(header)
            win = Adw.ApplicationWindow(application=self, title="win-prompt", default_width=640, content=view)
            ctrl = Gtk.EventControllerKey()
            ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            ctrl.connect("key-pressed", on_key)
            win.add_controller(ctrl)
            win.connect("close-request", lambda _w: (self.finish({"act": "cancel"}), True)[1])
            refresh()
            win.present()
            entry.grab_focus_without_selecting()

    run_with_ascii_input(lambda: App().run([]))


def run_inline(argv):
    """win の命令をこのプロセスで実行し、(終了コード, 標準出力, 標準エラー) を返す。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = main(argv)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
    return rc or 0, out.getvalue(), err.getvalue()


def cmd_prompt_gtk(args):
    """1 行の入力欄（GTK）。win prompt の既定。"""
    wc = WindowCalls()
    cfg = load_config()
    all_windows = normal_windows(wc)
    spec = {"layouts": cfg["layouts"], "commands": load_commands(), "sets": load_sets(), "history": load_history(), "initial": "",
            **ext_spec(),
            "error": None, "info": None,
            "windows": [{"sel": selector_for(w, all_windows), "cls": w.get("wm_class") or "",
                         "title": (w.get("title") or "")[:60]} for w in reversed(all_windows)]}
    while True:
        proc = subprocess.Popen([sys.executable, WIN_BIN, "_prompt"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        proc.stdin.write(json.dumps(spec))
        proc.stdin.close()
        center_and_focus(wc, proc, PROMPT_APP_ID)
        out = proc.stdout.read()
        proc.wait()
        res = None
        for line in reversed(out.strip().splitlines()):
            try:
                res = json.loads(line)
                break
            except ValueError:
                continue
        if not res or res.get("act") != "run" or not res.get("line", "").strip():
            return 0
        line = res["line"].strip()
        try:
            argv = shlex.split(line)
        except ValueError as e:
            spec.update(initial=line, error=f"引用符が閉じていません: {e}", info=None)
            continue
        if argv and argv[0] == "win":
            argv = argv[1:]
        problem = None
        if not argv:
            return 0
        if argv[0] == "prompt":
            problem = "ここでは prompt は使えません"
        if problem:
            spec.update(initial=line, error=problem, info=None)
            continue
        time.sleep(0.25)            # 入力窓が閉じて、元の窓にフォーカスが戻るのを待つ
        rc, so, se = run_inline(argv)
        if rc == 0:
            if not (argv[0] == "layout" and any(a in ("-i", "--interactive") for a in argv)):
                save_history(line)
            if argv[0] in SHOW_OUTPUT and so.strip():
                if argv[0] == "list":
                    so = "\n".join(f"{'*' if w.get('focus') else ' '} {(w.get('wm_class') or '')[:22]:<22} "
                                    f"{(w.get('title') or '')[:48]}" for w in reversed(normal_windows(wc)))
                spec.update(initial="", error=None, info=so.rstrip())
                spec["history"] = load_history()
                continue
            return 0
        msg = (se.strip() or so.strip() or f"失敗しました（終了コード {rc}）")
        spec.update(initial=line, error=msg, info=None)


NVPROMPT_LUA = r'''-- win prompt（nvim の入力欄）。win が開くたびに書き出すファイルなので、編集しても上書きされます。
local buf = vim.api.nvim_get_current_buf()
vim.bo[buf].filetype = "win"
vim.bo[buf].swapfile = false
vim.lsp.start({ name = "win", cmd = { vim.g.win_python, vim.g.win_bin, "lsp" }, root_dir = vim.fn.fnamemodify(vim.g.win_result, ":h") },
  { bufnr = buf })

local function finish(line)
  local f = io.open(vim.g.win_result, "w")
  if f then
    f:write(line or "")
    f:close()
  end
  vim.cmd("qall!")
end

-- Enter: カーソルのある行を実行する（# の行・空の行では何もしない）
vim.keymap.set({ "n", "i" }, "<CR>", function()
  local line = vim.api.nvim_get_current_line()
  if line:match("^%s*$") or line:match("^%s*#") then
    return
  end
  finish(line)
end, { buffer = buf, desc = "win: この行を実行" })
-- ノーマルモードの Esc・q、どのモードでも Ctrl+C: 何もせずに閉じる
vim.keymap.set("n", "<Esc>", function() finish(nil) end, { buffer = buf, desc = "win: 閉じる" })
vim.keymap.set("n", "q", function() finish(nil) end, { buffer = buf, desc = "win: 閉じる" })
vim.keymap.set({ "n", "i" }, "<C-c>", function() finish(nil) end, { buffer = buf, desc = "win: 閉じる" })

-- 書式・説明の浮き窓。nvim 標準の表示は markdown の構文解析器を使い、入っていないと失敗するので、普通の文字で出す
local float = {}
local function close_float()
  if float.win and vim.api.nvim_win_is_valid(float.win) then
    vim.api.nvim_win_close(float.win, true)
  end
  float.win = nil
end
local function show_float(lines, active, at_top)
  close_float()
  if not lines or #lines == 0 then
    return
  end
  local width = 10
  for _, l in ipairs(lines) do
    width = math.max(width, vim.fn.strdisplaywidth(l))
  end
  width = math.min(width, vim.o.columns - 4)
  local b = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_buf_set_lines(b, 0, -1, false, lines)
  if active then
    vim.api.nvim_buf_set_extmark(b, vim.api.nvim_create_namespace("win_prompt"), active, 0,
      { end_row = active + 1, hl_group = "Search", hl_eol = true })
  end
  local below = vim.fn.winline() < vim.api.nvim_win_get_height(0) - #lines - 1
  local pos = at_top and { relative = "editor", row = 0, col = vim.o.columns - width - 2 }      -- 補完の一覧と重ならない、右上
    or { relative = "cursor", row = below and 1 or -math.min(#lines, 10) - 2, col = 0 }
  float.win = vim.api.nvim_open_win(b, false, vim.tbl_extend("force", pos, {
    width = width, height = math.min(#lines, 10), style = "minimal", border = "rounded", focusable = false, zindex = 60,
  }))
end
local function request(method, cb)
  local client = vim.lsp.get_clients({ bufnr = buf, name = "win" })[1]
  if not client then
    return
  end
  local params = vim.lsp.util.make_position_params(0, client.offset_encoding)
  client:request(method, params, function(err, result)
    if not err then
      cb(result)
    end
  end, buf)
end
local function signature()
  request("textDocument/signatureHelp", function(r)
    local sig = r and r.signatures and r.signatures[1]
    if not sig then
      close_float()
      return
    end
    local lines, active = { sig.label .. "　" .. (sig.documentation or "") }, nil
    for k, prm in ipairs(sig.parameters or {}) do
      table.insert(lines, prm.label .. "　" .. (prm.documentation or ""))
      if r.activeParameter == k - 1 then
        active = k
      end
    end
    show_float(lines, active, true)
  end)
end
local function hover()
  request("textDocument/hover", function(r)
    local text = r and r.contents and r.contents.value
    if not text then
      return
    end
    local lines = {}
    for _, l in ipairs(vim.split(text, "\n")) do
      if not l:match("^```") then
        table.insert(lines, (l:gsub("`", "")))
      end
    end
    show_float(lines)
  end)
end
vim.keymap.set("n", "K", hover, { buffer = buf, desc = "win: 説明" })
vim.api.nvim_create_autocmd({ "InsertLeave", "CursorMoved" }, { buffer = buf, callback = close_float })

-- 空白を打ったら、引数の書式を出し、補完の候補も出す（行が空・コメントなら閉じる）
vim.api.nvim_create_autocmd("TextChangedI", {
  buffer = buf,
  callback = function()
    local col = vim.api.nvim_win_get_cursor(0)[2]
    local line = vim.api.nvim_get_current_line()
    if line:match("^%s*$") or line:match("^%s*#") then
      close_float()
    elseif col > 0 and line:sub(col, col) == " " then
      signature()
      local ok, blink = pcall(require, "blink.cmp")
      if ok then
        vim.schedule(function() pcall(blink.show) end)
      end
    end
  end,
})

-- 最後の行（入力の行）の末尾から、挿入モードで始める
vim.api.nvim_win_set_cursor(0, { vim.api.nvim_buf_line_count(buf), 0 })
vim.cmd("startinsert!")
if vim.g.win_error and vim.g.win_error ~= "" then
  vim.schedule(function() vim.api.nvim_echo({ { vim.g.win_error, "ErrorMsg" } }, false, {}) end)
end
'''


def nvim_prompt_available():
    if not shutil.which("nvim"):
        return False
    try:
        gi.require_version("Vte", "2.91")
        return True
    except ValueError:
        return False


def nvim_prompt_once(wc, initial, notes, error):
    """nvim の入力欄を 1 回開き、実行する行（取り消しなら None）を返す。上に履歴、その下に notes（# の行）、最後が入力の行。"""
    d = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "win")
    os.makedirs(d, mode=0o700, exist_ok=True)
    text_path, result_path, lua_path = (os.path.join(d, n) for n in ("prompt.win", "prompt.result", "prompt.lua"))
    hist = load_history()[-30:]                           # 古い順（ファイルも古い順。新しいものほど入力の行の近く）
    lines = hist + [f"# {n}" for n in notes] + [initial]
    with open(text_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(lua_path, "w", encoding="utf-8") as f:
        f.write(NVPROMPT_LUA)
    with contextlib.suppress(FileNotFoundError):
        os.remove(result_path)
    proc = subprocess.Popen([sys.executable, WIN_BIN, "_nvprompt", text_path, result_path, lua_path, error or ""],
                            stdin=subprocess.DEVNULL)
    center_and_focus(wc, proc, NVPROMPT_APP_ID)
    proc.wait()
    try:
        with open(result_path, encoding="utf-8") as f:
            line = f.read().strip()
    except FileNotFoundError:
        return None
    return line or None


def run_nvprompt(text_path, result_path, lua_path, error):
    """nvim を中に持つ小さな窓（GTK3 + VTE）。nvim が終わったら閉じる。"""
    gi.require_version("Gtk", "3.0")
    gi.require_version("Vte", "2.91")
    from gi.repository import Gtk, Vte

    GLib.set_prgname(NVPROMPT_APP_ID)                    # GTK3 の窓のクラス名（Wayland の app id）はプログラム名になる
    app = Gtk.Application(application_id=NVPROMPT_APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)

    def activate(a):
        win = Gtk.ApplicationWindow(application=a, title="win prompt")
        term = Vte.Terminal()
        term.set_size(100, 20)
        win.add(term)
        argv = ["nvim", "--cmd", f"let g:win_bin = {json.dumps(WIN_BIN)} | let g:win_python = {json.dumps(sys.executable)}"
                f" | let g:win_result = {json.dumps(result_path)} | let g:win_error = {json.dumps(error)}",
                "-c", f"luafile {lua_path}", text_path]
        term.spawn_async(Vte.PtyFlags.DEFAULT, os.path.dirname(text_path), argv, None, GLib.SpawnFlags.SEARCH_PATH,
                         None, None, -1, None, None)
        term.connect("child-exited", lambda *_: a.quit())
        win.connect("delete-event", lambda *_: (a.quit(), False)[1])
        win.show_all()
        term.grab_focus()

    app.connect("activate", activate)
    run_with_ascii_input(lambda: app.run([]))


def prompt_execute(wc, line):
    """入力欄で打った 1 行を実行する。("done", None)・("show", 出力)・("error", 説明) のどれかを返す。"""
    try:
        argv = shlex.split(line)
    except ValueError as e:
        return "error", f"引用符が閉じていません: {e}"
    if argv and argv[0] == "win":
        argv = argv[1:]
    if not argv:
        return "done", None
    if argv[0] == "prompt":
        return "error", "ここでは prompt は使えません"
    time.sleep(0.25)            # 入力窓が閉じて、元の窓にフォーカスが戻るのを待つ
    rc, so, se = run_inline(argv)
    if rc == 0:
        if not (argv[0] == "layout" and any(a in ("-i", "--interactive") for a in argv)):
            save_history(line)
        if argv[0] in SHOW_OUTPUT and so.strip():
            if argv[0] == "list":
                so = "\n".join(f"{'*' if w.get('focus') else ' '} {(w.get('wm_class') or '')[:22]:<22} "
                                f"{(w.get('title') or '')[:48]}" for w in reversed(normal_windows(wc)))
            return "show", so.rstrip()
        return "done", None
    return "error", "\n".join(l.removeprefix("win: ") for l in (se.strip() or so.strip() or f"失敗しました（終了コード {rc}）").splitlines())


def cmd_prompt(args):
    if not getattr(args, "nvim", False) or not nvim_prompt_available():
        return cmd_prompt_gtk(args)
    wc = WindowCalls()
    initial, notes, error = "", [], None
    load_extensions()
    notes = [f"読み込めなかった拡張: {os.path.basename(f)}: {m}" for f, m in EXT_ERRORS]
    while True:
        line = nvim_prompt_once(wc, initial, notes, error)
        if not line:
            return 0
        kind, payload = prompt_execute(wc, line)
        if kind == "done":
            return 0
        if kind == "show":
            initial, notes, error = "", payload.splitlines(), None
        else:
            initial, notes, error = line, [f"✗ {l}" for l in payload.splitlines()], payload.splitlines()[0]


# ---------------------------------------------------------------- ショートカットの管理（GNOME のカスタムショートカット）

MK_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
MK_ENTRY = MK_SCHEMA + ".custom-keybinding"
MK_BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
WIN_BIN = os.path.abspath(sys.argv[0])  # 起動役（~/.local/bin/win）。子のプロセスもこれで起こし、解析結果のキャッシュを使わせる

# win の標準の操作（slug, 表示名, 引数, 既定のキー）。slug は dconf の項目名
WIN_ACTIONS = [
    ("win-pick", "窓を選んで前面に出す", "pick", "<Super><Alt>p"),
    ("win-prompt", "コマンドを入力して窓を操作", "prompt", "<Super><Alt>semicolon"),
    ("win-layout", "型を選んで窓を並べる", "layout", "<Super><Alt>m"),
    ("win-here", "選んだ窓を今の窓と同じ形にする", "here", "<Super><Alt>o"),
    ("win-set", "保存した並び（セット）を選んで適用", "set", "<Super><Alt>s"),
    ("win-nav-next", "次の窓へ（いまの並びの番号順）", "nav next", "<Super><Alt>j"),
    ("win-nav-prev", "前の窓へ（いまの並びの番号順）", "nav prev", "<Super><Alt>k"),
    *[(f"win-slot-{n}", f"{n} 番目のタイルの窓へ", f"focus @slot:{n}", f"<Super><Alt>{n}") for n in range(1, 10)],
    ("win-config", "win の設定を開く", "config", "<Super><Alt>comma"),
]


def command_slug(name):
    """登録したコマンド名に対応する、ショートカットの項目名（名前が日本語でも使える固定長の形）。"""
    return "win-run-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]


def ext_slug(name):
    """拡張の命令に対応する、ショートカットの項目名。"""
    return "win-ext-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]


def set_slug(name):
    """セットの名前に対応する、ショートカットの項目名。"""
    return "win-set-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]


def kb_entry(slug):
    return Gio.Settings.new_with_path(MK_ENTRY, f"{MK_BASE}{slug}/")


def kb_slugs():
    return [p.rstrip("/").rsplit("/", 1)[-1] for p in Gio.Settings.new(MK_SCHEMA).get_strv("custom-keybindings")]


def kb_list():
    """[{slug, name, command, binding}]（GNOME の設定アプリの「カスタムショートカット」と同じもの）"""
    out = []
    for slug in kb_slugs():
        e = kb_entry(slug)
        out.append({"slug": slug, "name": e.get_string("name"), "command": e.get_string("command"),
                    "binding": e.get_string("binding")})
    return out


def kb_set(slug, name=None, command=None, binding=None):
    """項目を作る（無ければ）か、指定した値だけ更新する。反映まで数秒かかることがある（gsd-media-keys の再読み込み）。"""
    st = Gio.Settings.new(MK_SCHEMA)
    paths = st.get_strv("custom-keybindings")
    path = f"{MK_BASE}{slug}/"
    if path not in paths:
        st.set_strv("custom-keybindings", paths + [path])
    e = kb_entry(slug)
    for key, val in (("name", name), ("command", command), ("binding", binding)):
        if val is not None:
            e.set_string(key, val)
    Gio.Settings.sync()


def kb_remove(slug):
    st = Gio.Settings.new(MK_SCHEMA)
    path = f"{MK_BASE}{slug}/"
    st.set_strv("custom-keybindings", [p for p in st.get_strv("custom-keybindings") if p != path])
    e = kb_entry(slug)
    for key in ("name", "command", "binding"):
        e.reset(key)
    Gio.Settings.sync()


def _gtk():
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk, Gtk
    return Gtk, Gdk


def accel_parse(accel):
    Gtk, _ = _gtk()
    ok, key, mods = Gtk.accelerator_parse(accel)
    return (key, mods) if ok and key else None


def accel_norm(accel):
    """比べるための正規化（修飾キーの順序や表記の違いをそろえる）。読めなければ None。"""
    p = accel_parse(accel)
    return _gtk()[0].accelerator_name(*p) if p else None


# 日本語キーボードの特殊キー（キーシンボル名 → 画面での表記）。半角/全角は jp 配列で GRAVE（`）の位置にある
JP_KEYS = {"Henkan": "変換", "Muhenkan": "無変換", "Zenkaku_Hankaku": "半角/全角",
           "Hiragana_Katakana": "ひらがな/カタカナ"}


# 同じ物理キーを指す別名（日本語配列の半角/全角は `` ` `` と同じキー。GNOME の Above_Tab はこのキー）
PHYSICAL_KEY_ALIASES = {"above_tab": "grave", "zenkaku_hankaku": "grave", "kanji": "grave", "asciitilde": "grave"}
MOD_ALIASES = {"primary": "control", "ctrl": "control", "control": "control", "mod1": "alt", "alt": "alt",
               "mod4": "super", "super": "super", "shift": "shift", "meta": "meta", "hyper": "hyper"}


def accel_id(accel):
    """衝突を調べるための識別子（修飾キーの別名・順序と、同じ物理キーを指す別名をそろえる）。読めなければ None。
    GTK が解析できない表記（Above_Tab など）でも、文字列として比べられる。"""
    m = re.fullmatch(r"\s*((?:<[^<>]+>)*)\s*(\S*)\s*", accel or "")
    if not m or not m.group(2):
        return None
    mods = sorted({MOD_ALIASES.get(t.lower(), t.lower()) for t in re.findall(r"<([^<>]+)>", m.group(1))})
    key = m.group(2).lower()
    key = PHYSICAL_KEY_ALIASES.get(key, key)
    return "+".join(mods + [key])


# 変換＋キー: keyd（/etc/keyd/default.conf）の [win] レイヤーが、変換を押しながらのキーを Super+Alt+キー にする。
# GNOME 側は Super+Alt+キー のショートカットとして登録するので、keyd さえ全キー分あれば、あとは sudo なしで付け外しできる。
KEYD_CONF = "/etc/keyd/default.conf"
KEYD_GENERATED = os.path.expanduser("~/.config/win/keyd-default.conf")
# 変換＋キーにできるキー: keyd のキー名 → (GNOME のキー名, 表示)。日本語配列と US 配列で同じ文字になるものだけ
# （@・[・^ などは配列で文字が変わり、keyd が出すキーと GNOME の登録が食い違うので外す）
HENKAN_KEYS = {**{c: (c, c.upper()) for c in "abcdefghijklmnopqrstuvwxyz"}, **{d: (d, d) for d in "0123456789"},
               "minus": ("minus", "-"), "semicolon": ("semicolon", ";"), "comma": ("comma", ","),
               "dot": ("period", "."), "slash": ("slash", "/")}


def keyd_win_layer(path=KEYD_CONF):
    """keyd の [win] レイヤー {keyd のキー名: 出すもの（例 M-A-e）}。読めなければ空。"""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return {}
    out, inside = {}, False
    for line in text.splitlines():
        t = line.strip()
        if t.startswith("["):
            inside = t == "[win]"
        elif inside and "=" in t and not t.startswith("#"):
            k, v = (x.strip() for x in t.split("=", 1))
            out[k] = v
    return out


def henkan_map():
    """{GNOME の Super+Alt+キー の識別子: 変換＋何キーで出るか（表示）}。keyd の設定から作る。"""
    names = {k: v for k, v in HENKAN_KEYS.items()}
    out = {}
    for key, produced in keyd_win_layer().items():
        m = re.fullmatch(r"M-A-(\w+)", produced)
        if m and m.group(1) in names and key in names:
            out[accel_id(f"<Super><Alt>{names[m.group(1)][0]}")] = names[key][1]
    return out


def keyd_full_layer_text(path=KEYD_CONF):
    """今の keyd の設定の [win] レイヤーだけを、変換＋キーにできる全キー（キー → Super+Alt+同じキー）にした設定の全文。"""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        text = "[ids]\n*\n\n[main]\nhenkan = overload(win, henkan)\n"
    lines, out, inside, done = text.splitlines(), [], False, False
    body = ["# 変換を押しながら: 英字・数字・- ; , . / を Super+Alt+同じキー にする（win の設定画面が作った。",
            "# GNOME のショートカット Super+Alt+キー で win などを呼ぶ。付け外しは win config のショートカットのページで）",
            "[win]"] + [f"{k} = M-A-{k}" for k in HENKAN_KEYS]
    for line in lines:
        t = line.strip()
        if t.startswith("["):
            if inside:
                inside = False
            if t == "[win]":
                inside, done = True, True
                while out and out[-1].lstrip().startswith("#"):   # [win] の直前の説明のコメントも差し替える
                    out.pop()
                out += body
                continue
        if not inside:
            out.append(line)
    if not done:
        out += [""] + body
    return "\n".join(out).rstrip("\n") + "\n"


def henkan_layer_missing():
    """変換＋キーにできるのに、keyd がまだ Super+Alt+同じキー にしていないキー（表示）。"""
    layer = keyd_win_layer()
    return [disp for k, (_g, disp) in HENKAN_KEYS.items() if layer.get(k) != f"M-A-{k}"]


def accel_label(accel):
    """画面に出す表記（例: 変換＋M、Super+Alt+M、変換、Super+半角/全角）。空なら「（未割り当て）」。"""
    if not accel:
        return "（未割り当て）"
    henkan = henkan_map().get(accel_id(accel))
    if henkan:
        return f"変換＋{henkan}"
    p = accel_parse(accel)
    if not p:
        return accel
    Gtk, Gdk = _gtk()
    label = Gtk.accelerator_get_label(*p)
    jp = JP_KEYS.get(Gdk.keyval_name(p[0]) or "")
    bare = Gtk.accelerator_get_label(p[0], 0)
    if jp and label.endswith(bare):
        label = label[:len(label) - len(bare)] + jp
    return label


def scan_accelerators():
    """GNOME・拡張・自作のショートカットが使っているキー: {accel_id: [(使っている所, slug)]}。"""
    used = {}

    def add(accel, where, slug=None):
        n = accel_id(accel)
        if n:
            used.setdefault(n, []).append((where, slug))

    def scan_source(src, ids, label):
        for sid in ids:
            schema = src.lookup(sid, True)
            if schema is None:
                continue
            st = Gio.Settings.new_full(schema, None, None)
            for key in schema.list_keys():
                v = st.get_value(key)
                t = v.get_type_string()
                for acc in ([v.get_string()] if t == "s" else (list(v.get_strv()) if t == "as" else [])):
                    if "<" in acc:
                        summary = (schema.get_key(key).get_summary() or "").strip()      # GNOME が持つ説明文（英語のことが多い）
                        add(acc, f"{label}: {key}" + (f"（{summary}）" if summary else ""))

    default = Gio.SettingsSchemaSource.get_default()
    words = ("keybindings", "media-keys", "shell", "mutter", "wm", "settings-daemon")
    scan_source(default, [s for s in default.list_schemas(True)[0] if any(w in s for w in words)], "GNOME")
    for d in glob.glob(os.path.expanduser("~/.local/share/gnome-shell/extensions/*/schemas")):
        try:
            src = Gio.SettingsSchemaSource.new_from_directory(d, default, False)
        except GLib.Error:
            continue
        scan_source(src, src.list_schemas(False)[0], "拡張 " + d.split("/")[-2].split("@")[0])
    for e in kb_list():
        if e["binding"]:
            add(e["binding"], f"自作: {e['name'] or e['slug']}", e["slug"])
    return used


def accel_conflicts(used, accel, ignore_slug=None):
    """accel を、すでに使っている所の一覧（ignore_slug 自身は除く）。"""
    return [w for w, slug in used.get(accel_id(accel) or "", []) if ignore_slug is None or slug != ignore_slug]


def accel_note(accel):
    """Mozc オンの端末などで届かない可能性があるときの注意（なければ空文字）。確認済みで届くのは、
    Ctrl・Alt・Super のうち 2 つ以上と文字キーの組み合わせ（Shift なし）。"""
    p = accel_parse(accel)
    if not p:
        return "キーの形式が読めません"
    if accel_id(accel) in henkan_map():                  # 変換＋キー（keyd が出す Super+Alt+キー）は記号も含めて届く
        return ""
    key, mods = p
    _, Gdk = _gtk()
    name = Gdk.keyval_name(key) or ""
    if not mods:
        return ""                                              # 修飾キーなし（変換キーなど）は判断しない
    n = sum(1 for m in (Gdk.ModifierType.CONTROL_MASK, Gdk.ModifierType.ALT_MASK, Gdk.ModifierType.SUPER_MASK) if mods & m)
    if len(name) == 1 and name.isalnum() and n >= 2 and not mods & Gdk.ModifierType.SHIFT_MASK:
        return ""
    return ("Mozc オンの端末などで届かないことがあります。確認済みで届く形は、Ctrl・Alt・Super のうち 2 つ以上と"
            "文字キーの組み合わせ（Shift なし）です。")


# ---------------------------------------------------------------- 設定の保存（commands.toml・sets.toml）

COMMANDS = os.environ.get("WIN_COMMANDS") or os.path.expanduser("~/.config/win/commands.toml")      # 環境変数は試験用の差し替え
SETS = os.environ.get("WIN_SETS") or os.path.join(os.path.dirname(COMMANDS), "sets.toml")
TOML_HEADER = "# win config が書き換えます。手で編集してもかまいません（コメントは、保存し直すと消えます）。\n"


def _toml_key(k):
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k, ensure_ascii=False)


def _toml_val(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_val(x) for x in v) + "]"
    raise TypeError(f"TOML にできない値: {v!r}")


def _is_aot(v):
    return isinstance(v, list) and bool(v) and all(isinstance(x, dict) for x in v)


def toml_dumps(data, path=()):
    """小さな TOML の書き出し（文字列・数・真偽・それらの配列・表・表の配列。tomllib で読み返せる）。"""
    lines = [f"{_toml_key(k)} = {_toml_val(v)}" for k, v in data.items() if not isinstance(v, dict) and not _is_aot(v)]
    for k, v in data.items():
        sub = path + (k,)
        name = ".".join(_toml_key(x) for x in sub)
        if isinstance(v, dict):
            lines += ["", f"[{name}]", toml_dumps(v, sub)]
        elif _is_aot(v):
            for item in v:
                lines += ["", f"[[{name}]]", toml_dumps(item, sub)]
    return "\n".join(lines).strip("\n")


def write_toml(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(TOML_HEADER + "\n" + toml_dumps(data) + "\n")
    os.replace(tmp, path)


def _load_table(path, key):
    try:
        with open(path, "rb") as f:
            return tomllib.load(f).get(key, {})
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as e:
        raise WinError(f"{path} が読めません: {e}")


def load_commands():
    """{名前: {"type": "win"|"shell", ...}}。ファイルが無ければ空。"""
    migrate_sets()
    return _load_table(COMMANDS, "commands")


def save_commands(cmds):
    write_toml(COMMANDS, {"commands": cmds})


def load_sets():
    """{名前: {"type": "win", "run": …} か旧形式 {"type": "arrange", "windows": […]}}。ファイルが無ければ空。"""
    migrate_sets()
    return _load_table(SETS, "sets")


def save_sets(sets):
    write_toml(SETS, {"sets": sets})


def migrate_sets():
    """commands.toml に残っているセット（kind = "set" と旧形式 type = "arrange"）を sets.toml へ移す。付けたキーも付け替える。"""
    cmds = _load_table(COMMANDS, "commands")
    moving = {n: c for n, c in cmds.items() if is_set(c)}
    if not moving:
        return
    sets, renamed = _load_table(SETS, "sets"), {}
    for n, c in moving.items():
        new, i = n, 2
        while new in sets:                                    # 同じ名前のセットがあれば「名前 (2)」にする
            new, i = f"{n} ({i})", i + 1
        sets[new] = {k: v for k, v in c.items() if k != "kind"}
        renamed[n] = new
    save_sets(sets)                                           # 先にセット側へ書いてから消す（途中で止まっても失わない）
    save_commands({n: c for n, c in cmds.items() if n not in moving})
    try:
        kbs = {e["slug"]: e for e in kb_list()}
    except Exception:                                         # GNOME の設定に触れない環境（試験など）
        return
    for old, new in renamed.items():
        e = kbs.get(command_slug(old))
        if e:
            kb_remove(command_slug(old))
            kb_set(set_slug(new), name=f"win set: {new}", command=f"{WIN_BIN} set {shlex.quote(new)}", binding=e["binding"])


def win_lines(text):
    """win の命令の並び（1 行に 1 つ）から、空行と # で始まる行を除いた行のリスト。"""
    return [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]


def _check_win_one(line):
    try:
        argv = shlex.split(line)
    except ValueError as e:
        return f"引用符が閉じていません: {e}"
    if argv and argv[0] == "win":
        argv = argv[1:]
    if not argv:
        return "命令が空です"
    if argv[0] in ("run", "config", "set"):
        return f"「{argv[0]}」は、コマンドの中では使えません（無限に呼び合うのを防ぐため）"
    load_extensions()
    if argv[0] not in {c for c, _ in SUBCOMMANDS} | {"prompt"} | set(EXT):
        return f"知らない命令です: {argv[0]}"
    return None


def check_win_line(text):
    """win の命令（複数行可）として正しいか。問題があれば説明、なければ None。"""
    lines = win_lines(text)
    if not lines:
        return "命令が空です"
    for i, line in enumerate(lines, 1):
        err = _check_win_one(line)
        if err:
            return f"{i} 行目: {err}" if len(lines) > 1 else err
    return None


# 各命令の書式（打っている途中の引数の説明に使う）: 命令 → (書式の部品, {部品: 説明})。
# 部品は ("位置", 名前) か ("opt", "-w") のような印。位置の部品は順に対応し、最後が [窓 …] のように繰り返すものは "rep"。
WIN_OPT = ("opt", "-w", "窓", "対象の窓（クラス・題名の一部、@left・@prev など）。省くと前面の窓")
MONITOR_HELP = "基準にするモニタ（primary・current・eDP-1 など）。省くと、いまの窓があるモニタ"
MON_OPT = ("opt", "--monitor", "画面", "基準のモニタ（primary・current・eDP-1 など）。省くと、いまの窓があるモニタ")
SIGNATURES = {
    "here": ([("pos", "窓", "窓の指定（クラス・題名の一部）か !コマンド。省くと小窓で選ぶ", True), MON_OPT], "選んだ窓を今の窓と同じ位置・大きさにして前面へ"),
    "focus": ([("pos", "窓", "窓の指定（クラス・題名の一部）か、5 桁以上の ID", False)], "窓を前面に出す"),
    "nav": ([("pos", "方向", "next / prev（いまの並びの番号順）、left / right / up / down", False)], "フォーカスを次・前・上下左右の窓へ移す"),
    "layout": ([("pos", "型", "型の名前（win layouts）か式（例: v(1,h(1,1))。略記 1,2:1/1/1,1 も可）。省くと小窓で選ぶ", True),
                ("rep", "窓", "タイル順の窓。- は空け、!コマンド は新しく起動", True),
                ("opt", "--gap", "隙間", "タイル間の隙間（px）"), ("flag", "-n", "動かさず、割り当てだけ表示"),
                ("flag", "--pick", "タイルごとに窓の一覧を自動で出す"), ("flag", "-i", "タイルごとに窓を絞り込んで選ぶ"), MON_OPT],
               "窓を分割配置する"),
    "pick": ([("flag", "--id", "前面に出さず、選んだ窓の ID だけを表示"), MON_OPT], "窓の一覧から選んで前面に出す"),
    "move": ([WIN_OPT, ("pos", "x", "左端の位置（px）", False), ("pos", "y", "上端の位置（px）", False)], "窓を移動する"),
    "size": ([WIN_OPT, ("pos", "幅", "幅（px）", False), ("pos", "高さ", "高さ（px）", False)], "窓の大きさを変える"),
    "state": ([WIN_OPT, ("pos", "動作", "max / unmax / min / unmin / above / unabove", False)], "最大化・最小化・常に手前"),
    "max": ([WIN_OPT], "窓を最大化する"), "unmax": ([WIN_OPT], "最大化を戻す"),
    "min": ([WIN_OPT], "窓を最小化する"), "unmin": ([WIN_OPT], "最小化を戻す"), "close": ([WIN_OPT], "窓を閉じる"),
    "list": ([("flag", "-a", "通常の窓以外も表示")], "窓の一覧を表示する"),
    "layouts": ([], "型の一覧を表示する"),
    "run": ([("pos", "名前", "登録したコマンド・保存した並び", False)], "登録したコマンドを実行する"),
    "save": ([("pos", "名前", "保存する名前（win set 名前 で呼べる）", False),
              ("opt", "--state", "状態", "firefox / terminal / all。タブの URL・作業ディレクトリも保存（選んだときだけ）"), MON_OPT],
             "いまの窓の並びを、型と窓の列として保存する"),
    "term": ([("rep", "作業ディレクトリ", "タブごとの作業ディレクトリ", True)], "端末をタブつきで開く"),
    "browse": ([("rep", "URL", "開く URL（最初の 1 つで窓を開き、残りはタブ）", False)], "Firefox を URL のタブつきで開く"),
    "set": ([("pos", "名前", "セットの名前。省くと、絞り込みの小窓が開く", True), MON_OPT], "保存した並び（セット）を適用する"),
}


def signature_parts(line):
    """入力中の 1 行（先頭の win は省略可）の書式。{"cmd", "summary", "items": [(表示, 名前, 説明)], "active": いま打っている部品の名前}。
    命令が分からなければ None。"""
    tokens = line.lstrip().split(" ")
    if tokens[0] == "win":
        tokens = tokens[1:]
    if len(tokens) < 2 or tokens[0] not in SIGNATURES:
        return None
    cmd, rest = tokens[0], tokens[1:]
    parts, summary = SIGNATURES[cmd]
    opt_value = {p[1] for p in parts if p[0] == "opt"}
    positional, skip = 0, False                       # 入力済みの位置引数の数
    for tok in rest[:-1]:
        if skip:
            skip = False
        elif tok in opt_value:
            skip = True
        elif not tok.startswith("-"):
            positional += 1
    cur = rest[-1]
    active = None                                     # いま打っている部品（名前）
    if len(rest) >= 2 and rest[-2] in opt_value and not skip_flag_value(rest[:-1], opt_value):
        active = rest[-2]
    elif not cur.startswith("-"):
        pos_parts = [p for p in parts if p[0] in ("pos", "rep")]
        if pos_parts:
            last = pos_parts[-1]
            active = last[1] if positional >= len(pos_parts) and last[0] == "rep" else \
                (pos_parts[positional][1] if positional < len(pos_parts) else None)
    items = []
    for p in parts:
        if p[0] == "pos":
            label, desc, optional = p[1], p[2], p[3]
            text = f"[{label}]" if optional else label
        elif p[0] == "rep":
            label, desc = p[1], p[2]
            text = f"[{label} …]"
        elif p[0] == "opt":
            label, desc = p[1], p[3]
            text = f"[{p[1]} {p[2]}]"
        else:
            label, desc = p[1], p[2]
            text = f"[{p[1]}]"
        items.append((text, label, desc))
    return {"cmd": cmd, "summary": summary, "items": items, "active": active}


def signature_markup(line):
    """入力中の 1 行に対する、書式と引数の説明（Pango マークアップ）。命令が分からなければ None。"""
    esc = lambda t: GLib.markup_escape_text(t)
    sp = signature_parts(line)
    if sp is None:
        return None
    shown, lines = [], []
    for text, label, desc in sp["items"]:
        on = label == sp["active"]
        shown.append(f"<b><u>{esc(text)}</u></b>" if on else esc(text))
        lines.append(("<b>" if on else "") + f"{esc(text)}　{esc(desc)}" + ("</b>" if on else ""))
    head = f"<tt>win {esc(sp['cmd'])} {' '.join(shown)}</tt>　{esc(sp['summary'])}"
    return head + ("\n" + "\n".join(lines) if lines else "")


def skip_flag_value(done, opt_value):
    """done の末尾の語が、すでに値を受け取った後のオプションかどうか（直前の語が値なら True）。"""
    return len(done) >= 2 and done[-2] in opt_value


def describe_command(c):
    t = c.get("type", "win")
    if t == "arrange":
        return f"並び {len(c.get('windows', []))} 枚"
    run = c.get("run", "")
    if t == "win":
        return " → ".join(win_lines(run))                 # 複数行は「→」でつなぐ（コメント行は除く）
    lines = [l for l in run.splitlines() if l.strip()]
    return lines[0] + (" …" if len(lines) > 1 else "") if lines else ""


@functools.cache
def app_for_class(cls):
    """窓のクラス名に当たるアプリ（.desktop の StartupWMClass・ID・実行ファイル名で照合）。なければ None。"""
    if not cls:
        return None
    low = cls.lower()
    for a in Gio.AppInfo.get_all():
        if not a.should_show():
            continue
        wm = (getattr(a, "get_startup_wm_class", lambda: None)() or "").lower()
        aid = (a.get_id() or "").lower()
        aid = aid[:-8] if aid.endswith(".desktop") else aid
        exe = os.path.basename(a.get_executable() or "").lower()
        if low in (wm, aid, exe):
            return a
    return None


def launch_for_class(cls):
    """窓のクラス名から、起動コマンド（.desktop の Exec）を探す。見つからなければ空文字。"""
    a = app_for_class(cls)
    return app_commandline(a) if a else ""


def icon_for_class(cls):
    """窓のクラス名に当たるアプリのアイコン（Gio.Icon の文字列）。なければ空文字。"""
    a = app_for_class(cls)
    icon = a.get_icon() if a else None
    return icon.to_string() if icon else ""


def icon_widget(Gtk, Gdk, icon, size=24, fallback="application-x-executable-symbolic"):
    """一覧の行に出すアイコン。名前・ファイル・Gio.Icon の文字列を受け、テーマになければ fallback。"""
    img = None
    if icon:
        try:
            if os.path.isabs(icon):
                img = Gtk.Image.new_from_file(icon)
            else:
                g = Gio.Icon.new_for_string(icon)
                theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
                if isinstance(g, Gio.FileIcon) or theme.has_gicon(g):
                    img = Gtk.Image.new_from_gicon(g)
        except GLib.Error:
            img = None
    if img is None:
        img = Gtk.Image.new_from_icon_name(fallback)
    img.set_pixel_size(size)
    return img


# ---------------------------------------------------------------- アプリの状態（Firefox のタブ・端末の作業ディレクトリ）
# 「win save --state …」で選んだときだけ保存する。汎用のセットには入れない（開く場所が固定されてしまうため）。

def mozlz4_loads(data):
    """Firefox の mozlz4（目印＋展開後の大きさ＋ lz4 のブロック）を展開して JSON を読む。"""
    if data[:8] != b"mozLz40\0":
        raise ValueError("mozlz4 ではありません")
    src, out, i = data[12:], bytearray(), 0
    while i < len(src):
        token = src[i]
        i += 1
        n = token >> 4
        if n == 15:
            while True:
                b = src[i]
                i += 1
                n += b
                if b != 255:
                    break
        out += src[i:i + n]
        i += n
        if i >= len(src):
            break
        off = src[i] | (src[i + 1] << 8)
        i += 2
        m = token & 15
        if m == 15:
            while True:
                b = src[i]
                i += 1
                m += b
                if b != 255:
                    break
        start = len(out) - off
        for k in range(m + 4):                              # 重なるコピーは 1 バイトずつ
            out.append(out[start + k])
    return json.loads(out.decode("utf-8"))


def firefox_profile_dir():
    """既定の Firefox プロファイルのディレクトリ（なければ None）。"""
    for base in (os.path.expanduser("~/.config/mozilla/firefox"), os.path.expanduser("~/.mozilla/firefox")):
        paths = []
        cp = configparser.ConfigParser(interpolation=None)
        if cp.read(os.path.join(base, "installs.ini"), encoding="utf-8"):
            paths += [cp.get(sec, "Default") for sec in cp.sections() if cp.has_option(sec, "Default")]
        cp = configparser.ConfigParser(interpolation=None)
        if cp.read(os.path.join(base, "profiles.ini"), encoding="utf-8"):
            paths += [cp.get(sec, "Path") for sec in cp.sections()
                      if cp.has_option(sec, "Path") and cp.get(sec, "Default", fallback="0") == "1"]
        for pth in paths:
            d = pth if os.path.isabs(pth) else os.path.join(base, pth)
            if os.path.isdir(d):
                return d
    return None


def firefox_session_windows(profile=None):
    """Firefox のセッション（窓ごとのタブの一覧）。保存は 15 秒ほど遅れることがある。"""
    d = profile or firefox_profile_dir()
    if not d:
        raise WinError("Firefox のプロファイルが見つかりません")
    for name in ("sessionstore-backups/recovery.jsonlz4", "sessionstore.jsonlz4"):
        path = os.path.join(d, name)
        if os.path.exists(path):
            with open(path, "rb") as f:
                return mozlz4_loads(f.read()).get("windows", [])
    raise WinError("Firefox のセッション情報が見つかりません")


def _norm_title(t):
    t = "".join(c for c in (t or "") if unicodedata.category(c) != "Cf").strip()      # 目に見えない書式文字を除く
    return re.sub(r"\s*[—–-]\s*Mozilla Firefox$", "", t).strip()


def _firefox_tab_entry(tab):
    ents = tab.get("entries") or []
    return ents[min(max(tab.get("index", len(ents)), 1), len(ents)) - 1] if ents else {}


def firefox_window_title(sw):
    tabs = sw.get("tabs") or []
    return _norm_title(_firefox_tab_entry(tabs[min(max(sw.get("selected", 1), 1), len(tabs)) - 1]).get("title")) if tabs else ""


def firefox_tab_urls(sw):
    skip = ("about:blank", "about:newtab", "about:home", "about:privatebrowsing")
    urls = [_firefox_tab_entry(t).get("url", "") for t in sw.get("tabs") or []]
    return [u for u in urls if u and u not in skip and not u.startswith(("moz-extension:", "javascript:"))]


def _url_arg(u):
    """URL を、引用符なしで書ける形にする（空白・引用符・バックスラッシュだけを % 表記にする。URL としては同じ意味）。"""
    return re.sub(r"[\s'\"\\]", lambda m: "%%%02X" % ord(m.group()), u)


def firefox_state(windows, session=None):
    """Firefox の窓ごとに、タブを開き直す起動コマンド。({窓の id: コマンド}, 注意のリスト)。窓との対応は、いま表示中のタブの題名で取る。"""
    try:
        sess = firefox_session_windows() if session is None else session
    except (WinError, OSError, ValueError, KeyError, IndexError) as e:
        return {}, [f"Firefox のタブを読めませんでした（{e}）"]
    out, notes, used = {}, [], set()
    for w in windows:
        title = _norm_title(w.get("title"))
        cands = [k for k, sw in enumerate(sess) if k not in used and firefox_window_title(sw) == title]
        if not cands:
            notes.append(f"Firefox の窓「{title[:24]}」: セッションの窓と対応が取れませんでした（タブの保存は 15 秒ほど遅れます）")
            continue
        used.add(cands[0])
        urls = firefox_tab_urls(sess[cands[0]])
        if not urls:
            notes.append(f"Firefox の窓「{title[:24]}」: 保存できるタブがありません")
            continue
        out[w["id"]] = "win browse " + " ".join(_url_arg(u) for u in urls)
    return out, notes


def ptyxis_tabs():
    """端末（Ptyxis）の各タブの [(pts 番号, シェルの作業ディレクトリ)]。"""
    try:
        pids = subprocess.run(["pgrep", "-x", "ptyxis"], capture_output=True, text=True).stdout.split()
    except OSError:
        return []
    ptys = set()
    for pid in pids:
        fdir = f"/proc/{pid}/fd"
        try:
            for fd in os.listdir(fdir):
                if os.readlink(os.path.join(fdir, fd)) == "/dev/ptmx":
                    with open(f"/proc/{pid}/fdinfo/{fd}") as f:
                        m = re.search(r"^tty-index:\s*(\d+)", f.read(), re.M)
                    if m:
                        ptys.add(int(m.group(1)))
        except OSError:
            continue
    tabs = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/stat") as f:
                rest = f.read().rsplit(")", 1)[1].split()
            session, tty_nr = int(rest[3]), int(rest[4])
            if session == int(pid) and (tty_nr >> 8) == 136 and (tty_nr & 0xFF) in ptys:     # pts のセッションリーダー（シェル）
                tabs[tty_nr & 0xFF] = os.readlink(f"/proc/{pid}/cwd")
        except (OSError, IndexError, ValueError):
            continue
    return sorted(tabs.items())


def terminal_state(windows, tabs=None):
    """端末の窓ごとに、作業ディレクトリのタブを開き直す起動コマンド。({窓の id: コマンド}, 注意のリスト)。
    窓とタブの対応は、窓が 1 つのときと、題名（… ~/dir）から 1 対 1 に決まるときだけ取れる。"""
    tabs = ptyxis_tabs() if tabs is None else tabs
    if not tabs:
        return {}, ["端末のタブの作業ディレクトリを読めませんでした"]
    home = os.path.expanduser("~")
    short = lambda d: "~" + d[len(home):] if d == home or d.startswith(home + "/") else d
    if len(windows) == 1:
        return {windows[0]["id"]: "win term " + " ".join(shlex.quote(d) for _, d in tabs)}, []
    out, used = {}, set()
    for w in windows:
        title = (w.get("title") or "").strip()
        cands = [(n, d) for n, d in tabs if n not in used and title.endswith(short(d))]
        if len(cands) != 1:
            return {}, ["端末の窓が複数あり、窓とタブの対応が取れないため、端末の状態は保存しません"]
        used.add(cands[0][0])
        out[w["id"]] = "win term " + shlex.quote(cands[0][1])
    return out, ["端末の窓が複数あるため、各窓の表示中のタブの作業ディレクトリだけ保存します"]


def cmd_browse(args):
    """Firefox を新しい窓で開き、URL をタブとして並べる。
    （起動中の Firefox では、1 回の呼び出しに --new-window と --new-tab を並べると、タブが元の窓に入ってしまう。
    そのため、窓を開いて前面になってから、タブを 1 つずつ足す。）"""
    wc = WindowCalls()
    ff = shlex.split(os.environ.get("WIN_FIREFOX", "firefox"))        # 試験用に、別のプロファイルの Firefox へ差し替えられる
    before = {w["id"] for w in normal_windows(wc)}
    subprocess.Popen(ff + ["--new-window", args.urls[0]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    win = wait_new_window(wc, before, 25, "firefox")
    for u in args.urls[1:]:
        wc.simple("Activate", win["id"])
        time.sleep(0.5)
        subprocess.run(ff + ["--new-tab", u], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)
        time.sleep(0.8)
    return 0


def cmd_term(args):
    """端末（Ptyxis）を、作業ディレクトリごとのタブつきで新しく開く。"""
    wc = WindowCalls()
    dirs = [os.path.expanduser(d) for d in args.dirs] or [os.getcwd()]       # ~ も使えるように（手で書く行では、シェルが展開しないため）
    before = {w["id"] for w in normal_windows(wc)}
    subprocess.Popen(["ptyxis", "--new-window", "-d", dirs[0]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    win = wait_new_window(wc, before, 15, "ptyxis")
    for d in dirs[1:]:
        wc.simple("Activate", win["id"])                  # 「アクティブな窓」に新しいタブを作るので、先に前面にする
        time.sleep(0.4)
        subprocess.run(["ptyxis", "--tab", "-d", d], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10)
        time.sleep(0.5)
    return 0


SET_TOL = 0.03          # 窓の端を同じ線とみなす許容（作業領域に対する割合）。タイルの隙間を吸収する


def _weights_to_ints(ws):
    """幅の比を、小さい整数の比にする（合わなければ小数 1 桁）。"""
    lo = min(ws)
    r = [w / lo for w in ws]
    for m in range(1, 9):
        v = [x * m for x in r]
        if all(round(x) >= 1 and abs(x - round(x)) <= 0.06 * x for x in v):
            ints = [round(x) for x in v]
            g = functools.reduce(math.gcd, ints)
            return [i // g for i in ints]
    return [round(x, 1) for x in r]


def _split_groups(items, axis, tol):
    """どの窓も横切らない線で、axis（0=x, 1=y）方向に分けた窓の群。分けられなければ None。"""
    a0, a1 = (1, 3) if axis == 1 else (0, 2)
    items = sorted(items, key=lambda it: (it[1 + a0], it[1 + a1]))
    groups, end = [[items[0]]], items[0][1 + a1]
    for it in items[1:]:
        if it[1 + a0] >= end - tol:
            groups.append([it])
            end = it[1 + a1]
        else:
            groups[-1].append(it)
            end = max(end, it[1 + a1])
    return groups if len(groups) > 1 else None


def _build_tree(items, box, tol, dropped):
    """items: (id, x0, y0, x1, y1, z)。分割の木 ("leaf", id) / ("split", "v"|"h", 重み, 子) を返す。
    分けられない（重なった）窓は、他にいちばん多く重なるものから外して dropped に入れる。"""
    if len(items) == 1:
        return ("leaf", items[0][0])
    for axis, d in ((0, "v"), (1, "h")):
        groups = _split_groups(items, axis, tol)
        if not groups:
            continue
        a0, a1 = (1, 3) if axis == 1 else (0, 2)
        lo, hi = box[a0], box[a1]
        starts = [min(it[1 + a0] for it in g) for g in groups]
        ends = [max(it[1 + a1] for it in g) for g in groups]
        bounds = [lo] + [(ends[k - 1] + starts[k]) / 2 for k in range(1, len(groups))] + [hi]
        weights = _weights_to_ints([max(bounds[k + 1] - bounds[k], 1e-6) for k in range(len(groups))])
        kids = []
        for k, g in enumerate(groups):
            sub = list(box)
            sub[a0], sub[a1] = bounds[k], bounds[k + 1]
            kids.append(_build_tree(g, tuple(sub), tol, dropped))
        return ("split", d, weights, kids)
    def overlaps(a, b):
        return (min(a[3], b[3]) - max(a[1], b[1]) > tol) and (min(a[4], b[4]) - max(a[2], b[2]) > tol)

    # 分けられない: 他の窓にいちばん多く重なる窓（同数なら下にある窓）を外して、やり直す
    victim = max(items, key=lambda it: (sum(1 for o in items if o is not it and overlaps(it, o)), -it[5]))
    dropped.append(victim[0])
    return _build_tree([it for it in items if it is not victim], box, tol, dropped)


def _tree_expr(node):
    if node[0] == "leaf":
        return "full"
    _, d, ws, kids = node
    args = []
    for w, k in zip(ws, kids):
        if k[0] == "leaf":
            args.append(f"{w:g}")
        else:
            e = _tree_expr(k)
            args.append(e if w == 1 else f"{w:g}:{e}")
    return f"{d}({','.join(args)})"


def _tree_leaves(node):
    return [node[1]] if node[0] == "leaf" else [i for k in node[3] for i in _tree_leaves(k)]


def _match_named(items, layouts, tol):
    """窓の並びと同じ形の、名前のついた型があれば (名前, 窓の id をタイルの順に並べたもの)。"""
    for name, expr in layouts.items():
        try:
            rects = [tuple(c / 1000 for c in r) for r in leaf_rects(LayoutParser(expr).parse(), (0, 0, 1000, 1000))]
        except WinError:
            continue
        if len(rects) != len(items):
            continue
        left, order = list(items), []
        for r in rects:
            best = min(left, key=lambda it: sum(abs(a - b) for a, b in zip(r, it[1:5])))
            if any(abs(a - b) > 2 * tol for a, b in zip(r, best[1:5])):
                break
            left.remove(best)
            order.append(best[0])
        else:
            return name, order
    return None


def current_tiles(wc, cfg):
    """いま基準のモニタに出ている窓の並びを、窓の位置から逆算する（win save と @slot が使う）。
    {"onmon", "other", "maxed", "items", "tree", "dropped", "by_id"}。tree は最大化していない窓だけで作る（なければ None）。"""
    ax, ay, aw, ah = work_area(cfg)
    mx, my, mw, mh = monitor_rect()
    by_id = {w["id"]: w for w in normal_windows(wc)}
    onmon, other = [], 0
    for z, (w, (x, y, rw, rh)) in enumerate(visible_windows(wc)):         # 下 → 上
        if mx <= x + rw / 2 < mx + mw and my <= y + rh / 2 < my + mh:
            onmon.append((z, w, (x, y, rw, rh)))
        else:
            other += 1
    maxed = [t for t in onmon if (lambda d: d.get("maximized_horizontally") and d.get("maximized_vertically"))(wc.details(t[1]["id"]))]
    items = []
    for z, w, (x, y, rw, rh) in onmon:
        if any(t[1]["id"] == w["id"] for t in maxed):
            continue
        clamp = lambda v: min(1.0, max(0.0, v))
        items.append((w["id"], clamp((x - ax) / aw), clamp((y - ay) / ah),
                      clamp((x + rw - ax) / aw), clamp((y + rh - ay) / ah), z))
    dropped = []
    tree = _build_tree(items, (0.0, 0.0, 1.0, 1.0), SET_TOL, dropped) if items else None
    return {"onmon": onmon, "other": other, "maxed": maxed, "items": items, "tree": tree, "dropped": dropped, "by_id": by_id}


def tile_order(cur, cfg):
    """逆算した並びのタイル順の窓 ID（名前つきの型と同じ形なら、その型のタイル順）。"""
    kept = set(_tree_leaves(cur["tree"]))
    named = _match_named([it for it in cur["items"] if it[0] in kept], cfg["layouts"], SET_TOL)
    return (named[0], named[1]) if named else (_tree_expr(cur["tree"]), _tree_leaves(cur["tree"]))


def arrangement_lines(wc, state=()):
    """いま表に出ている窓（基準のモニタ上のもの）を、「型＋窓の列」の命令にする。(行のリスト, 注意のリスト, 窓の数)。
    state に "firefox"・"terminal" を指定すると、その窓は、窓がなければ状態つきで開くよう保存する（選んだときだけ）。"""
    cfg = load_config()
    cur = current_tiles(wc, cfg)
    onmon, other, maxed, items, tree, dropped, by_id = (cur[k] for k in ("onmon", "other", "maxed", "items", "tree", "dropped", "by_id"))
    notes = []
    if other:
        notes.append(f"別のモニタにある窓 {other} 枚は含めていません")

    launch_cmds = {}                                          # 状態つきで起動するコマンド {窓の id: コマンド}

    def token(w):
        cls = w.get("wm_class") or ""
        if w["id"] in launch_cmds:
            return shlex.quote(f"{cls}?{launch_cmds[w['id']]}")
        return shlex.quote(cls) + "?" if cls else shlex.quote((w.get("title") or "")[:30])

    tiled = [t for t in onmon if t not in maxed]
    if not tiled:
        if not maxed:
            raise WinError("保存できる窓がありません")
        w = maxed[-1][1]
        if len(maxed) > 1:
            notes.append(f"最大化している窓のうち、いちばん上の 1 枚だけ保存します（{len(maxed) - 1} 枚は含めていません）")
        cls = w.get("wm_class") or str(w["id"])
        return [f"layout full {token(w)}", f"max -w {shlex.quote(cls)}"], notes, 1
    if maxed:
        notes.append(f"最大化している窓 {len(maxed)} 枚は含めていません")
    if dropped:
        names = ", ".join(sorted({by_id[i].get("wm_class") or "?" for i in dropped}))
        notes.append(f"重なっている窓 {len(dropped)} 枚は含めていません（{names}）。各タイルで、いちばん上の窓だけ保存します")
    kept = set(_tree_leaves(tree))
    kept_items = [it for it in items if it[0] in kept]
    kept_windows = [by_id[i] for i in kept]
    for kind, cls, fn in (("firefox", "firefox", firefox_state), ("terminal", "org.gnome.Ptyxis", terminal_state)):
        if kind in state:
            targets = [w for w in kept_windows if (w.get("wm_class") or "") == cls]
            if not targets:
                notes.append(f"{'Firefox' if kind == 'firefox' else '端末'} の窓がないため、状態は保存しません")
                continue
            got, more = fn(targets)
            launch_cmds.update(got)
            notes += more
    area = sum((it[3] - it[1]) * (it[4] - it[2]) for it in kept_items)
    if area < 0.6:
        notes.append("画面の一部しか使っていない並びです。呼ぶと、窓は画面いっぱいに広がります")
    expr, order = tile_order(cur, cfg)
    return [f"layout {expr} " + " ".join(token(by_id[i]) for i in order)], notes, len(order)


def save_arrangement(wc, name, overwrite=False, state=()):
    """いまの窓の並びを、型と窓の列の命令（セット）として name で保存する。(保存した窓の数, 注意のリスト) を返す。"""
    name = name.strip()
    if not name:
        raise WinError("名前が空です")
    sets = load_sets()
    if name in sets and not overwrite:
        raise WinError(f"「{name}」はすでにあります（上書きするには --force）")
    lines, notes, count = arrangement_lines(wc, state)
    sets[name] = {"type": "win", "run": "\n".join(lines)}
    save_sets(sets)
    return count, notes


def run_arrangement(wc, entry):
    """保存した並びを再現する。窓が足りなければ起動コマンドで新規起動する。注意の一覧を返す。"""
    ax, ay, aw, ah = work_area(load_config())
    try:
        ws = focused(wc).get("workspace", 0)
    except WinError:
        ws = 0
    pool = list(reversed(normal_windows(wc)))                 # 前面が先
    used, notes = set(), []
    for e in entry.get("windows", []):                        # 保存順（下 → 上）に、重なり順も再現する
        cls = e.get("cls", "")
        found = [w for w in pool if (w.get("wm_class") or "") == cls and w["id"] not in used]
        found.sort(key=lambda w: (w.get("title") or "")[:60] != e.get("title"))   # 同じクラスなら題名が一致する窓を優先
        w = found[0] if found else None
        if w is None and e.get("launch"):
            try:
                w = launch(wc, e["launch"], 12)
            except WinError as err:
                notes.append(f"{cls}: 起動できませんでした（{err}）")
        if w is None:
            if not e.get("launch"):
                notes.append(f"{cls}: 窓が見つかりません（起動コマンドも不明）")
            continue
        used.add(w["id"])
        if e.get("maximized"):
            msg = bring_here(wc, w, (0, 0, 0, 0), True, ws)
        else:
            x, y, rw, rh = e["rect"]
            msg = bring_here(wc, w, (ax + round(x * aw), ay + round(y * ah), round(rw * aw), round(rh * ah)), False, ws)
        if msg:
            notes.append(f"{cls}: {msg}")
    return notes


def cmd_save(args):
    wc = WindowCalls()
    state = ("firefox", "terminal") if "all" in (args.state or []) else tuple(args.state or [])
    n, notes = save_arrangement(wc, args.name, args.force, state)
    for note in notes:
        print(f"注意: {note}", file=sys.stderr)
    print(f"保存しました: 「{args.name}」（窓 {n} 枚）。呼び出すには: win set {shlex.quote(args.name)}")
    saved = load_sets()[args.name]
    print("  " + (set_summary(saved) if state else saved["run"]).replace("\n", "\n  "))     # 状態（URL など）は表示しない
    if any(parse_window_spec(t)[2] for t in shlex.split(saved["run"].replace("\n", " ")) if not t.startswith("!")):
        print(f"  ※ 状態（タブの URL・作業ディレクトリ）は {SETS} に平文で保存されました")
    return 0


# ---------------------------------------------------------------- セット（保存した窓の並び）

def is_set(c):
    """commands.toml に置かれていた頃のセットの印（移し替えにだけ使う）。"""
    return c.get("type") == "arrange" or c.get("kind") == "set"


def _layout_line(c):
    """セットの最初の layout 行を (型, [窓の指定…]) に分けて返す。なければ None。"""
    for line in win_lines(c.get("run", "")):
        try:
            argv = shlex.split(line)
        except ValueError:
            continue
        argv = argv[1:] if argv and argv[0] == "win" else argv
        if not argv or argv[0] != "layout":
            continue
        pos, skip = [], False
        for t in argv[1:]:
            if skip:
                skip = False
            elif t in ("--gap", "-m", "--monitor"):
                skip = True
            elif t.startswith("-") and t not in ("-", "_"):
                continue
            else:
                pos.append(t)
        return (pos[0], pos[1:]) if pos else None
    return None


def _spec_label(sel):
    if sel in ("-", "_", "...", "…"):
        return ""
    base = parse_window_spec(sel.lstrip("!"))[0] if not sel.startswith("!") else sel[1:].split()[0] if sel[1:].split() else ""
    return _short_cls(base)


def set_summary(c):
    """一覧に出す 1 行の説明（起動コマンドに含まれる URL などは出さない）。"""
    if c.get("type") == "arrange":
        return f"窓 {len(c.get('windows', []))} 枚（旧形式）"
    parsed = _layout_line(c)
    if not parsed:
        return describe_command(c)
    expr, sels = parsed
    with_state = any(parse_window_spec(x)[2] for x in sels if not x.startswith("!"))
    return f"{expr}{'  ＋状態' if with_state else ''}  " + " ・ ".join(_spec_label(x) or "（空）" for x in sels)      # 印は、長い行で省略されない先頭側に置く


def _short_cls(s):
    return s.rsplit(".", 1)[-1] if s else ""


def set_preview(c, cfg):
    """セットのプレビュー用のタイル [{x, y, w, h, label}]（作業領域を 0〜1 にした割合）。作れなければ空。"""
    tiles = []
    if c.get("type") == "arrange":
        for e in c.get("windows", []):
            x, y, w, h = (0, 0, 1, 1) if e.get("maximized") else e.get("rect", (0, 0, 1, 1))
            tiles.append({"x": x, "y": y, "w": w, "h": h, "label": _short_cls(e.get("cls", ""))})
        return tiles
    parsed = _layout_line(c)
    if not parsed:
        return []
    try:
        rects = compute_rects(resolve_layout(cfg, parsed[0]), (0, 0, 1000, 1000), 0)
    except WinError:
        return []
    sels = parsed[1]
    for i, (x, y, w, h) in enumerate(rects):
        tiles.append({"x": x / 1000, "y": y / 1000, "w": w / 1000, "h": h / 1000,
                      "label": _spec_label(sels[i]) if i < len(sels) else ""})
    return tiles


def monitors_for_preview(cfg):
    """プレビューに描く各モニタ {"name", "rect", "work"} と、基準モニタの添字。取れなければ ([], 0)。"""
    try:
        monitors, logical = display_state()
    except WinError:
        return [], 0
    base = tuple(monitor_rect())
    out, cur = [], 0
    for lm in logical:
        x, y, w, h = rect = logical_rect(lm, monitors)
        i = dict(cfg["insets"])
        if not lm[4]:
            i["top"] = 0                                   # work_area と同じ。上部バーの余白は主モニタだけ
        if rect == base:
            cur = len(out)
        out.append({"name": lm[5][0][0], "rect": list(rect),
                    "work": [x + i["left"], y + i["top"], w - i["left"] - i["right"], h - i["top"] - i["bottom"]]})
    return out, cur


def pick_set(wc, cfg, sets):
    """名前で絞り込みながら、プレビューを見て選ぶ小窓。(選ばれたセットの名前, 選ばれたモニタの接続名)。取消は (None, None)。
    モニタが 1 枚なら接続名は None（基準のモニタのまま）。"""
    ax, ay, aw, ah = work_area(cfg)
    mons, cur = monitors_for_preview(cfg)
    spec = {"sets": [{"name": n, "summary": set_summary(c)[:90], "tiles": set_preview(c, cfg)} for n, c in sets.items()],
            "ratio": aw / ah, "monitors": mons, "current": cur}
    proc = subprocess.Popen([sys.executable, WIN_BIN, "_setpick"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    proc.stdin.write(json.dumps(spec))
    proc.stdin.close()
    center_and_focus(wc, proc, SETPICK_APP_ID)
    out = proc.stdout.read()
    proc.wait()
    for line in reversed(out.strip().splitlines()):
        try:
            res = json.loads(line)
        except ValueError:
            continue
        if res.get("act") == "set":
            return res.get("name"), res.get("monitor")
        return None, None
    return None, None


def run_setpick():
    """セットを選ぶ小窓。上に名前の入力欄（入力で絞り込み）、下に一覧、横にプレビュー。結果は 1 行の JSON で標準出力へ。"""
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    spec = json.load(sys.stdin)
    sets, ratio = spec["sets"], spec.get("ratio") or 1.6
    mons = spec.get("monitors") or [{"name": None, "rect": [0, 0, ratio * 1000, 1000], "work": [0, 0, ratio * 1000, 1000]}]
    bx, by = min(m["rect"][0] for m in mons), min(m["rect"][1] for m in mons)         # 全モニタを囲む枠
    bw, bh = max(m["rect"][0] + m["rect"][2] for m in mons) - bx, max(m["rect"][1] + m["rect"][3] for m in mons) - by
    k = min(340 / bw, 200 / bh)                         # 縦横比を保って 340x200 に収める
    PW, PH = max(120, round(bw * k)), max(60, round(bh * k))
    st = {"set": None, "mon": min(max(spec.get("current") or 0, 0), len(mons) - 1)}

    class App(Adw.Application):
        def __init__(self):
            super().__init__(application_id=SETPICK_APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)

        def finish(self, act):
            print(json.dumps(act), flush=True)
            self.quit()

        def do_activate(self):
            css = Gtk.CssProvider()
            css.load_from_string(".tile-box { border: 1px solid alpha(currentColor, .4); border-radius: 4px; "
                                 "background: alpha(@accent_bg_color, .18); font-size: 9pt; } "
                                 ".preview-frame { background: alpha(currentColor, .06); border-radius: 6px; } "
                                 ".screen-box { background: alpha(currentColor, .05); border: 1px solid alpha(currentColor, .18); "
                                 "border-radius: 3px; } "
                                 ".screen-box.cur { background: alpha(currentColor, .09); border: 2px solid alpha(@accent_bg_color, .9); }")
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            entry = Gtk.Entry(hexpand=True, placeholder_text="セットの名前で絞り込み…")
            listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.BROWSE, can_focus=False, activate_on_single_click=True)
            listbox.add_css_class("boxed-list")
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=listbox, vexpand=True, hexpand=True,
                                        min_content_height=260)
            scroll.set_size_request(330, -1)
            preview = Gtk.Fixed()
            preview.set_size_request(PW, PH)
            frame = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.START, margin_top=2)
            frame.add_css_class("preview-frame")
            frame.append(preview)
            caption = Gtk.Label(wrap=True, xalign=0, max_width_chars=44, margin_top=8)
            caption.add_css_class("dim-label")
            side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.START, hexpand=False)
            side.append(frame)
            side.append(caption)
            shown = []                                    # 表示中の行 → sets の添字

            def draw(i=-1):
                if i != -1:
                    st["set"] = i
                i = st["set"]
                while (c := preview.get_first_child()) is not None:
                    preview.remove(c)
                for n, m in enumerate(mons):                   # 画面全体を薄く描き、適用先のモニタだけ強調する
                    mx, my, mw, mh = m["rect"]
                    box = Gtk.Box()
                    box.add_css_class("screen-box")
                    if n == st["mon"]:
                        box.add_css_class("cur")
                    box.set_size_request(max(4, round(mw * k)), max(4, round(mh * k)))
                    preview.put(box, round((mx - bx) * k), round((my - by) * k))
                if i is None:
                    caption.set_label("")
                    return
                wx, wy, ww, wh = mons[st["mon"]]["work"]      # タイルの座標は作業領域に対する割合
                tiles = sets[i]["tiles"]
                for t in tiles:
                    lab = Gtk.Label(label=t["label"], ellipsize=3, max_width_chars=10)
                    lab.add_css_class("tile-box")
                    lab.set_size_request(max(8, round(t["w"] * ww * k) - 2), max(8, round(t["h"] * wh * k) - 2))
                    preview.put(lab, round((wx + t["x"] * ww - bx) * k) + 1, round((wy + t["y"] * wh - by) * k) + 1)
                where = f"適用先: {mons[st['mon']]['name']}\n" if len(mons) > 1 else ""
                caption.set_label(where + (sets[i]["summary"] if tiles else "プレビューを作れません: " + sets[i]["summary"]))

            def move_mon(d):
                """いまのモニタから見て、左（d=-1）・右（d=1）にいちばん近いモニタへ。なければそのまま（並び順ではなく実際の位置）。"""
                def center(m):
                    return m["rect"][0] + m["rect"][2] / 2, m["rect"][1] + m["rect"][3] / 2
                cx, cy = center(mons[st["mon"]])
                side = [(abs(center(m)[0] - cx) + abs(center(m)[1] - cy) / 4, n) for n, m in enumerate(mons)
                        if n != st["mon"] and (center(m)[0] - cx) * d > 0]
                if side:
                    st["mon"] = min(side)[1]
                    draw()

            def refresh(*_):
                while (r := listbox.get_row_at_index(0)) is not None:
                    listbox.remove(r)
                words = entry.get_text().lower().split()
                shown[:] = [i for i, st in enumerate(sets) if all(w in (st["name"] + " " + st["summary"]).lower() for w in words)]
                for i in shown:
                    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)
                    name = Gtk.Label(label=sets[i]["name"], xalign=0)
                    name.add_css_class("heading")
                    sub = Gtk.Label(label=sets[i]["summary"], xalign=0, ellipsize=3, max_width_chars=40)
                    sub.add_css_class("dim-label")
                    sub.add_css_class("caption")
                    box.append(name)
                    box.append(sub)
                    listbox.append(Gtk.ListBoxRow(child=box))
                if shown:
                    listbox.select_row(listbox.get_row_at_index(0))
                else:
                    draw(None)
                    caption.set_label("一致するセットがありません")

            def move(d):
                if shown:
                    sel = listbox.get_selected_row()
                    row = listbox.get_row_at_index(max(0, min(len(shown) - 1, (sel.get_index() if sel else 0) + d)))
                    listbox.select_row(row)
                    row.grab_focus()
                    entry.grab_focus_without_selecting()

            def decide():
                sel = listbox.get_selected_row()
                if sel is not None:
                    self.finish({"act": "set", "name": sets[shown[sel.get_index()]]["name"],
                                 "monitor": mons[st["mon"]]["name"] if len(mons) > 1 else None})

            listbox.connect("row-selected", lambda _l, r: draw(shown[r.get_index()]) if r is not None else None)
            listbox.connect("row-activated", lambda _l, _r: decide())
            entry.connect("changed", refresh)
            entry.connect("activate", lambda _e: decide())

            def on_key(_c, keyval, _kc, state):
                name = Gdk.keyval_name(keyval)
                ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
                if name == "Escape":
                    self.finish({"act": "cancel"})
                elif name in ("Down", "Tab") or (ctrl and name in ("n", "j")):
                    move(1)
                elif name in ("Up", "ISO_Left_Tab") or (ctrl and name in ("p", "k")):
                    move(-1)
                elif name in ("Left", "Right") and len(mons) > 1 and not (state & ~Gdk.ModifierType.LOCK_MASK):
                    move_mon(1 if name == "Right" else -1)
                else:
                    return False
                return True

            body = Gtk.Box(spacing=14, margin_start=12, margin_end=12)
            body.append(scroll)
            body.append(side)
            top = Gtk.Box(margin_top=10, margin_start=12, margin_end=12, margin_bottom=8)
            top.append(entry)
            hint = Gtk.Label(label="入力で絞り込み ・ ↑↓ で選ぶ" + (" ・ ←→ でモニタを選ぶ" if len(mons) > 1 else "")
                             + " ・ Enter で適用 ・ Esc で閉じる", margin_top=8, margin_bottom=10)
            hint.add_css_class("dim-label")
            hint.add_css_class("caption")
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            for w in (top, body, hint):
                outer.append(w)
            header = Adw.HeaderBar(title_widget=Gtk.Label(label="セットを選ぶ"), show_end_title_buttons=False)
            view = Adw.ToolbarView(content=outer)
            view.add_top_bar(header)
            win = Adw.ApplicationWindow(application=self, title="win-setpick", default_width=780, content=view)
            ctrl = Gtk.EventControllerKey()
            ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            ctrl.connect("key-pressed", on_key)
            win.add_controller(ctrl)
            win.connect("close-request", lambda _w: (self.finish({"act": "cancel"}), True)[1])
            refresh()
            win.present()
            entry.grab_focus_without_selecting()

    App().run([])


def cmd_set(args):
    wc = WindowCalls()
    sets = load_sets()
    name = args.name
    if name is None:
        if not sets:
            raise WinError("セットがありません（win save 名前 で、いまの窓の並びを保存できます）")
        name, monitor = pick_set(wc, load_config(), sets)
        if name is None:
            return 1
        if monitor:
            resolve_monitor(monitor)                      # 小窓で選んだモニタを基準にして適用する（行に -m があればそちらが優先）
    elif name not in sets:
        if name in load_commands():
            raise WinError(f"「{name}」はセットではありません（win run {shlex.quote(name)} で実行できます）")
        raise WinError(f"セットが見つかりません: {name}（一覧は win set）")
    return run_entry(sets[name])


def cmd_run(args):
    cmds = load_commands()
    if not args.name:
        if not cmds:
            print("登録されたコマンドはありません（win config で作れます。窓の並びは win save でセットに）")
        for n, c in cmds.items():
            print(f"{n:<18} {c.get('type', 'win'):<8} {describe_command(c)}")
        return 0
    c = cmds.get(args.name)
    if c is None:
        c = load_sets().get(args.name)                        # 以前は run でセットも呼べたので、その呼び方も残す
    if c is None:
        raise WinError(f"コマンドが見つかりません: {args.name}（一覧は win run、セットは win set）")
    return run_entry(c)


def run_entry(c):
    """登録したコマンドかセットを 1 つ実行する。"""
    t = c.get("type", "win")
    if t == "win":
        err = check_win_line(c.get("run", ""))
        if err:
            raise WinError(err)
        for line in win_lines(c["run"]):                  # 上から順に。失敗したらそこで止める
            argv = shlex.split(line)
            rc = main(argv[1:] if argv[0] == "win" else argv)
            if rc:
                return rc
        return 0
    if t == "shell":
        subprocess.Popen(["sh", "-c", c.get("run", "")], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return 0
    if t == "arrange":
        for note in run_arrangement(WindowCalls(), c):
            print(note, file=sys.stderr)
        return 0
    raise WinError(f"知らない種類です: {t}")


# ---------------------------------------------------------------- 設定の窓（win config）

CONFIG_APP_ID = "local.win.config"


def read_layout_file():
    """layouts.toml の、自作の型・作業領域の余白・タイル間の隙間。"""
    try:
        with open(CONFIG, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        data = {}
    return dict(data.get("layouts", {})), {**DEFAULT_INSETS, **data.get("workarea", {})}, int(data.get("gap", 0))


def write_layout_file(layouts, insets, gap):
    data = {"gap": gap}
    if layouts:
        data["layouts"] = layouts
    data["workarea"] = dict(insets)
    write_toml(CONFIG, data)


def run_config(page="shortcuts"):
    """win の設定の窓。ショートカット・コマンド・セット・型の 4 ページ。"""
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk, Pango

    MODIFIER_KEYS = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Super_L", "Super_R",
                     "Meta_L", "Meta_R", "Hyper_L", "Hyper_R", "ISO_Level3_Shift", "ISO_Level5_Shift",
                     "Caps_Lock", "Num_Lock"}

    def clear(box):
        while (c := box.get_first_child()) is not None:
            box.remove(c)

    def plain(cls, **kw):
        """題名・説明を、マークアップではなく文字としてそのまま表示する行を作る（名前に < や & があっても壊れない）。"""
        kw.setdefault("use_markup", False)
        return cls(**kw)

    class ConfigWindow(Adw.ApplicationWindow):
        def __init__(self, app):
            super().__init__(application=app, title="win の設定", default_width=1040, default_height=880)
            self.used = {}
            css = Gtk.CssProvider()
            css.load_from_string(".tile-box { border: 1px solid alpha(currentColor, .4); border-radius: 4px; "
                                 "background: alpha(@accent_bg_color, .18); font-size: 9pt; } "
                                 ".cand-list row:selected { background: alpha(@accent_bg_color, .3); }")
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.toasts = Adw.ToastOverlay()
            self.stack = Adw.ViewStack()
            self.pages = {}
            for key, title, icon in (("shortcuts", "ショートカット", "input-keyboard-symbolic"),
                                     ("commands", "コマンド", "utilities-terminal-symbolic"),
                                     ("sets", "セット", "view-dual-symbolic"),
                                     ("layouts", "型", "view-grid-symbolic")):
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=18, margin_bottom=24,
                              margin_start=18, margin_end=18)
                clamp = Adw.Clamp(maximum_size=820, child=box)
                scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, child=clamp)
                self.pages[key] = box
                self.stack.add_titled_with_icon(scroll, key, title, icon)
            header = Adw.HeaderBar(title_widget=Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE))
            view = Adw.ToolbarView(content=self.stack)
            view.add_top_bar(header)
            self.toasts.set_child(view)
            self.set_content(self.toasts)
            self.refresh()

        # ------------------------------------------------------------ 共通
        def toast(self, text):
            self.toasts.add_toast(Adw.Toast.new(text))

        def refresh(self):
            reload_extensions()
            self.used = scan_accelerators()
            self.build_shortcuts()
            self.build_commands()
            self.build_sets()
            self.build_layouts()

        def suffix_box(self, *widgets):
            box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
            for w in widgets:
                box.append(w)
            return box

        def button(self, label, cb, css=None, tip=None):
            b = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
            if css:
                b.add_css_class(css)
            if tip:
                b.set_tooltip_text(tip)
            b.connect("clicked", lambda _b: cb())
            return b

        def icon_button(self, icon, cb, tip):
            b = Gtk.Button(icon_name=icon, valign=Gtk.Align.CENTER, tooltip_text=tip)
            b.add_css_class("flat")
            b.connect("clicked", lambda _b: cb())
            return b

        def dialog(self, title, child, width=520, height=0):
            dlg = Adw.Dialog(title=title, content_width=width)
            if height:
                dlg.set_content_height(height)
            dlg.set_child(child)
            dlg.present(self)
            return dlg

        def confirm(self, heading, body, label, cb, destructive=True):
            d = Adw.AlertDialog(heading=heading, body=body)
            d.add_response("cancel", "キャンセル")
            d.add_response("ok", label)
            if destructive:
                d.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
            d.set_default_response("cancel")
            d.connect("response", lambda _d, r: cb() if r == "ok" else None)
            d.present(self)

        # ------------------------------------------------------------ キーを押して設定する
        def capture_key(self, title, current, slug, on_set):
            """キーを実際に押して選ぶ（文字での入力も可）。衝突と、Mozc オンで届かない形を知らせる。"""
            state = {"accel": current or "", "syncing": False}
            shown = Gtk.Label(label=accel_label(current), focusable=True)       # 開いたときのフォーカス先（文字入力ではない）
            shown.add_css_class("title-1")
            hint = Gtk.Label(label="割り当てたいキーを、実際に押してください（変換＋キーにするなら、変換を押しながら。Esc で取消）", wrap=True)
            hint.add_css_class("dim-label")
            status = Gtk.Label(wrap=True, xalign=0, max_width_chars=60)
            entry = plain(Adw.EntryRow, title="キーを文字で入力（例: <Super><Alt>m）")
            entry.set_text(current or "")
            group = Adw.PreferencesGroup()
            group.add(entry)
            # 変換・無変換などは GNOME が先に処理して押しても届かないことがあるので、一覧からも選べるようにする
            special = plain(Adw.ComboRow, title="日本語キーから選ぶ")
            special.set_model(Gtk.StringList.new(["（選ばない）"] + list(JP_KEYS.values())))
            group.add(special)
            allow = Gtk.CheckButton(label="ほかと競合していても設定する")
            ok = self.button("設定する", lambda: finish(state["accel"]), "suggested-action")
            clear_b = self.button("解除する", lambda: finish(""))
            cancel = self.button("キャンセル", lambda: dlg.close())
            inhibit = self.button("使用中のキーも押して調べる…", lambda: do_inhibit(),
                                  tip="GNOME の確認（ショートカットの無効化の許可）が出ます。許可すると、すでに使われているキーも押して確かめられます")
            buttons = Gtk.Box(spacing=8, halign=Gtk.Align.END)
            for b in (clear_b, cancel, ok):
                buttons.append(b)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                          margin_start=18, margin_end=18)
            for w in (shown, hint, group, status, allow, inhibit, buttons):
                box.append(w)

            def update(accel, sync=True):
                state["accel"] = accel
                shown.set_label(accel_label(accel))
                if sync:                                            # 手で打っている最中は、欄を書き換えない
                    state["syncing"] = True
                    if entry.get_text() != accel:
                        entry.set_text(accel)
                    state["syncing"] = False
                conflicts = accel_conflicts(self.used, accel, slug) if accel else []
                note = accel_note(accel) if accel else ""
                lines = []
                if conflicts:
                    lines.append("すでに使われています: " + " ／ ".join(conflicts))
                if note:
                    lines.append(note)
                status.set_label("\n".join(lines))
                for c in ("error", "warning"):
                    status.remove_css_class(c)
                status.add_css_class("error" if conflicts else "warning")
                allow.set_visible(bool(conflicts))
                ok.set_sensitive(bool(accel) and (not conflicts or allow.get_active()))

            def finish(accel):
                dlg.close()
                on_set(accel)

            def on_key(_c, keyval, _kc, mask):
                focus = self.get_focus()
                if focus is not None and (focus is entry or focus.is_ancestor(entry)):
                    return False                                   # 文字入力の欄に打っているときは、そのまま
                name = Gdk.keyval_name(keyval) or ""
                if name in MODIFIER_KEYS:
                    return True
                mods = mask & Gtk.accelerator_get_default_mod_mask()
                if not mods and name == "Escape":
                    dlg.close()
                    return True
                if not mods and name in ("Tab", "ISO_Left_Tab"):
                    return False
                if not mods and name in ("Return", "KP_Enter") and ok.get_sensitive():
                    finish(state["accel"])
                    return True
                update(Gtk.accelerator_name(Gdk.keyval_to_lower(keyval), mods))
                return True

            def on_entry(_e):
                if state["syncing"]:
                    return
                text = entry.get_text().strip()
                if text and accel_parse(text):
                    update(accel_norm(text), sync=False)
                else:
                    update("", sync=False)
                    if text:
                        status.set_label("キーの形式が読めません（例: <Super><Alt>m）")
                        for c in ("error", "warning"):
                            status.remove_css_class(c)
                        status.add_css_class("warning")

            def do_inhibit():
                surf = self.get_native().get_surface()
                surf.inhibit_system_shortcuts(None)
                inhibit.set_sensitive(False)

            ctrl = Gtk.EventControllerKey()
            ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            ctrl.connect("key-pressed", on_key)
            entry.connect("changed", on_entry)

            def on_special(_r, _p):
                i = special.get_selected()
                if i > 0:
                    update(list(JP_KEYS)[i - 1])

            special.connect("notify::selected", on_special)
            allow.connect("toggled", lambda _c: update(state["accel"]))
            dlg = self.dialog(title, box)
            # ダイアログを開いている間、窓のフォーカスは空になり、内側の部品にはキーが届かない。窓全体で受け取る
            self.add_controller(ctrl)
            # 手入力の欄に英字（Super など）を打つので、開いている間だけ Mozc を直接入力にする
            prev = ibus_engine()
            switched = prev.startswith("mozc") and prev != "mozc-off"
            if switched:
                ibus_engine("mozc-off")

            def on_closed(_d):
                self.remove_controller(ctrl)
                self.get_native().get_surface().restore_system_shortcuts()
                if switched:
                    ibus_engine(prev)

            dlg.connect("closed", on_closed)
            update(current or "")
            GLib.idle_add(lambda: (dlg.set_focus(shown), False)[1])

        # ------------------------------------------------------------ ページ 1: ショートカット
        def key_label(self, accel):
            lab = Gtk.Label(label=accel_label(accel), valign=Gtk.Align.CENTER, margin_end=6)
            lab.add_css_class("monospace")
            if accel:
                lab.add_css_class("accent")
            else:
                lab.add_css_class("dim-label")
            return lab

        def set_binding(self, slug, name, command, accel):
            kb_set(slug, name=name, command=command, binding=accel)
            self.toast("キーを解除しました" if not accel else f"{accel_label(accel)} に設定しました（反映まで数秒かかることがあります）")
            self.refresh()

        def shortcut_row(self, slug, title, subtitle, current, name, command, default=None, deletable=False,
                         editable=False):
            row = plain(Adw.ActionRow, title=title, subtitle=subtitle)
            row.set_subtitle_lines(1)
            btns = [self.key_label(current),
                    self.button("変更", lambda: self.capture_key(title, current, slug,
                                lambda a: self.set_binding(slug, name, command, a)))]
            if current:
                btns.append(self.icon_button("edit-clear-symbolic",
                            lambda: self.set_binding(slug, name, command, ""), "キーを解除"))
            if default and current != default:
                btns.append(self.icon_button("edit-undo-symbolic",
                            lambda: self.set_binding(slug, name, command, default),
                            f"既定（{accel_label(default)}）に戻す"))
            if editable:
                btns.append(self.icon_button("document-edit-symbolic", lambda: self.shortcut_form(slug), "名前とコマンドを編集"))
            if deletable:
                btns.append(self.icon_button("user-trash-symbolic", lambda: self.confirm(
                    "このショートカットを削除しますか？", f"「{title}」を削除します。", "削除",
                    lambda: (kb_remove(slug), self.toast("削除しました"), self.refresh())), "削除"))
            row.add_suffix(self.suffix_box(*btns))
            return row

        def build_shortcuts(self):
            box = self.pages["shortcuts"]
            clear(box)
            intro = Gtk.Label(wrap=True, xalign=0, label=(
                "キーは、ここで一元管理します（GNOME の「カスタムショートカット」と同じ場所に書きます）。"
                "変更はすぐ保存され、反映まで数秒かかることがあります。"))
            intro.add_css_class("dim-label")
            box.append(intro)
            box.append(self.henkan_group())
            kbs = {e["slug"]: e for e in kb_list()}
            g1 = Adw.PreferencesGroup(title="win の操作", description="win の標準の命令です。")
            for slug, label, args, default in WIN_ACTIONS:
                e = kbs.get(slug)
                g1.add(self.shortcut_row(slug, label, f"win {args}", e["binding"] if e else "",
                                         f"win {args}（{label}）", f"{WIN_BIN} {args}", default=default))
            box.append(g1)
            cmds = load_commands()
            g2 = Adw.PreferencesGroup(title="登録したコマンド", description="「コマンド」ページで作ったコマンドに、キーを付けられます。")
            for name, c in cmds.items():
                slug = command_slug(name)
                e = kbs.get(slug)
                g2.add(self.shortcut_row(slug, name, describe_command(c), e["binding"] if e else "",
                                         f"win run: {name}", f"{WIN_BIN} run {shlex.quote(name)}"))
            if not cmds:
                g2.add(plain(Adw.ActionRow, title="（登録したコマンドはありません）"))
            box.append(g2)
            sets = load_sets()
            gs = Adw.PreferencesGroup(title="セット", description="「セット」ページで保存した窓の並びに、キーを付けられます。")
            for name, c in sets.items():
                slug = set_slug(name)
                e = kbs.get(slug)
                gs.add(self.shortcut_row(slug, name, set_summary(c), e["binding"] if e else "",
                                         f"win set: {name}", f"{WIN_BIN} set {shlex.quote(name)}"))
            if not sets:
                gs.add(plain(Adw.ActionRow, title="（保存したセットはありません）"))
            box.append(gs)
            orphans = [e for slug, e in kbs.items() if slug.startswith("win-ext-") and slug not in {ext_slug(n) for n in EXT}]
            if EXT or orphans:
                gx = Adw.PreferencesGroup(title="拡張の命令", description="拡張（Python）の @command に、キーを付けられます。引数は省いた形で呼びます。")
                for name, c in EXT.items():
                    slug = ext_slug(name)
                    e = kbs.get(slug)
                    gx.add(self.shortcut_row(slug, name, c.summary, e["binding"] if e else "",
                                             f"win: {name}", f"{WIN_BIN} {shlex.quote(name)}"))
                for e in orphans:                         # 命令が消えた（名前が変わった）のに、キーだけ残っているもの
                    row = self.shortcut_row(e["slug"], e["name"] or e["slug"], "⚠ この命令は拡張に見つかりません（消すか、拡張を直してください）",
                                            e["binding"], e["name"], e["command"], deletable=True)
                    row.add_css_class("warning")
                    gx.add(row)
                box.append(gx)
            own = {s for s, *_ in WIN_ACTIONS}
            g3 = Adw.PreferencesGroup(title="その他の自作ショートカット", description="win 以外で、自分で登録したものです。")
            g3.set_header_suffix(self.button("＋ 追加", lambda: self.shortcut_form(None)))
            for slug, e in kbs.items():
                if slug in own or slug.startswith(("win-run-", "win-set-", "win-ext-")):
                    continue
                g3.add(self.shortcut_row(slug, e["name"] or slug, e["command"], e["binding"], e["name"], e["command"],
                                         deletable=True, editable=True))
            box.append(g3)

        def henkan_group(self):
            """変換＋キーの一覧（どのキーに何が付いているか・空き）と、keyd を全キー分にする手順。"""
            g = Adw.PreferencesGroup(
                title="変換＋キー",
                description="変換を押しながらキーを押すと、keyd が Super+Alt+キー にして、ここで付けたショートカットを呼びます。"
                            "キーを付けるときは、取り込みの画面で変換を押しながらキーを押してください。")
            g.set_header_suffix(self.button("読み直す", lambda: (self.refresh(), self.toast("keyd の設定を読み直しました"))))
            missing = henkan_layer_missing()
            if missing:
                row = plain(Adw.ActionRow, title=f"変換＋キーにできないキーがあります（{len(missing)} 個）",
                            subtitle="keyd の設定を一度だけ書き換えると、英字・数字・- ; , . / のすべてで作れるようになります（sudo が要ります）")
                row.add_css_class("warning")
                row.add_suffix(self.suffix_box(self.button("手順…", self.keyd_form, "suggested-action")))
                g.add(row)
            hm = henkan_map()
            used_rows, free = [], []
            for k, (gname, disp) in HENKAN_KEYS.items():
                aid = accel_id(f"<Super><Alt>{gname}")
                if aid not in hm:
                    continue
                who = [w.split(": ", 1)[-1] for w, _slug in self.used.get(aid, [])]
                if who:
                    used_rows.append((hm[aid], " ／ ".join(who)))
                else:
                    free.append(hm[aid])
            for disp, who in sorted(used_rows):
                r = plain(Adw.ActionRow, title=f"変換＋{disp}", subtitle=who)
                r.set_subtitle_lines(1)
                g.add(r)
            g.add(plain(Adw.ActionRow, title="空いているキー", subtitle="　".join(sorted(free)) or "（なし）"))
            return g

        def keyd_form(self):
            """keyd の [win] レイヤーを全キー分にした設定を作り、入れるコマンドを見せる（sudo は利用者が打つ）。"""
            text = keyd_full_layer_text()
            os.makedirs(os.path.dirname(KEYD_GENERATED), exist_ok=True)
            with open(KEYD_GENERATED, "w", encoding="utf-8") as f:
                f.write(text)
            stamp = time.strftime("%Y%m%d")
            cmd = (f"sudo cp {KEYD_CONF} {KEYD_CONF}.bak-{stamp} && sudo cp {KEYD_GENERATED} {KEYD_CONF} "
                   f"&& sudo keyd.rvaiya reload")
            info = Gtk.Label(wrap=True, xalign=0, label=(
                f"新しい設定を {KEYD_GENERATED} に作りました。今の {KEYD_CONF} から、[win]（変換を押しながら）の部分だけを、"
                "英字・数字・- ; , . / の全キーが Super+Alt+同じキー を出す形に変えたものです（CapsLock・無変換などはそのまま）。"
                "端末で次のコマンドを打つと、今の設定を .bak に残して入れ替え、keyd に読み直させます。"))
            code = Gtk.Label(label=cmd, wrap=True, xalign=0, selectable=True)
            code.add_css_class("monospace")
            note = Gtk.Label(wrap=True, xalign=0, label=(
                "入れ替えた後、この画面の「読み直す」を押すと、変換＋キーの一覧が全キー分になります。"
                "変換＋S は Super+Alt+S を出すようになるので、いま変換＋S で呼んでいるもの（Super+Alt+E）は付け直しが要ります。"))
            note.add_css_class("dim-label")

            def copy():
                Gdk.Display.get_default().get_clipboard().set(cmd)
                self.toast("コマンドをコピーしました")

            btns = Gtk.Box(spacing=8, halign=Gtk.Align.END)
            btns.append(self.button("閉じる", lambda: dlg.close()))
            btns.append(self.button("コマンドをコピー", copy, "suggested-action"))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                          margin_start=18, margin_end=18)
            for w in (info, code, note, btns):
                box.append(w)
            dlg = self.dialog("変換＋キーを全キー分にする", box, 640)

        def shortcut_form(self, slug):
            """名前とコマンドを入力する（新規なら、続けてキーを押して設定する）。"""
            cur = next((e for e in kb_list() if e["slug"] == slug), None) if slug else None
            name_row = plain(Adw.EntryRow, title="名前")
            cmd_row = plain(Adw.EntryRow, title="コマンド（例: /usr/bin/ibus engine mozc-on）")
            if cur:
                name_row.set_text(cur["name"])
                cmd_row.set_text(cur["command"])
            group = Adw.PreferencesGroup()
            group.add(name_row)
            group.add(cmd_row)
            msg = Gtk.Label(wrap=True, xalign=0)
            msg.add_css_class("error")

            def save():
                n, c = name_row.get_text().strip(), cmd_row.get_text().strip()
                if not n or not c:
                    msg.set_label("名前とコマンドの両方を入力してください")
                    return
                dlg.close()
                if cur:
                    kb_set(slug, name=n, command=c)
                    self.toast("保存しました")
                    self.refresh()
                else:
                    new = "custom-" + hashlib.sha1(f"{n}{time.time()}".encode()).hexdigest()[:8]
                    self.capture_key(n, "", new, lambda a: (kb_set(new, name=n, command=c, binding=a),
                                                            self.toast("追加しました"), self.refresh()))

            btns = Gtk.Box(spacing=8, halign=Gtk.Align.END)
            btns.append(self.button("キャンセル", lambda: dlg.close()))
            btns.append(self.button("保存" if cur else "次へ（キーを設定）", save, "suggested-action"))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                          margin_start=18, margin_end=18)
            for w in (group, msg, btns):
                box.append(w)
            dlg = self.dialog("ショートカットを編集" if cur else "ショートカットを追加", box)

        # ------------------------------------------------------------ ページ 2: コマンド
        def build_commands(self):
            box = self.pages["commands"]
            clear(box)
            intro = Gtk.Label(wrap=True, xalign=0, label=(
                "よく使う操作に名前をつけて登録します。`win run 名前` で呼べて、入力欄（win prompt）の補完にも出ます。"
                "窓の並びは「セット」ページで保存します。キーは「ショートカット」ページで付けます。"))
            intro.add_css_class("dim-label")
            box.append(intro)
            cmds = load_commands()
            g = Adw.PreferencesGroup(title="登録したコマンド")
            g.set_header_suffix(self.button("＋ 新しいコマンド", lambda: self.command_form(None), "suggested-action"))
            kinds = {"win": "win の命令", "shell": "シェルコマンド"}
            for name, c in cmds.items():
                row = plain(Adw.ActionRow, title=name, subtitle=f"{kinds.get(c.get('type', 'win'), '?')}　{describe_command(c)}")
                row.set_subtitle_lines(1)
                row.add_suffix(self.suffix_box(
                    self.button("実行", lambda n=name: self.run_command(n), tip="いま実行する"),
                    self.icon_button("document-edit-symbolic", lambda n=name: self.command_form(n), "編集"),
                    self.icon_button("user-trash-symbolic", lambda n=name: self.confirm(
                        "コマンドを削除しますか？", f"「{n}」と、それに付けたキーを削除します。", "削除",
                        lambda: self.delete_command(n)), "削除")))
                g.add(row)
            if not cmds:
                g.add(plain(Adw.ActionRow, title="（まだありません。右上のボタンから作れます）"))
            box.append(g)
            ge = Adw.PreferencesGroup(
                title="拡張（Python）",
                description=f"{EXT_DIR} に .py を置き、関数に @command を付けると win の命令になります（win 名前 で呼べて、"
                            "入力欄の補完・登録したコマンド・ショートカットでも使えます）。書き方は同じ場所の winapi.pyi と、win help にあります。")
            ge.set_header_suffix(self.suffix_box(
                self.button("フォルダを開く", self.open_ext_dir),
                self.button("再読み込み", lambda: (self.refresh(), self.toast("拡張を読み直しました"))),
                self.button("＋ 新しい拡張", self.new_ext_form, "suggested-action")))
            for name, c in EXT.items():
                row = plain(Adw.ActionRow, title=name, subtitle=f"{c.summary}　{c.usage()}")
                row.set_subtitle_lines(1)
                row.add_suffix(self.suffix_box(
                    self.button("実行", lambda n=name: self.run_ext_command(n), tip="引数を省いて、いま実行する"),
                    self.icon_button("document-edit-symbolic", lambda c=c: self.open_ext_source(c.file, c.line),
                                     "定義を開く（端末の nvim）")))
                ge.add(row)
            for path, msg in EXT_ERRORS:
                row = plain(Adw.ActionRow, title=f"読み込めませんでした: {os.path.basename(path)}", subtitle=msg)
                row.add_css_class("error")
                row.add_suffix(self.suffix_box(self.icon_button("document-edit-symbolic",
                                                                lambda p=path, m=msg: self.open_ext_source(p, _error_line(m)), "開く")))
                ge.add(row)
            if not EXT and not EXT_ERRORS:
                ge.add(plain(Adw.ActionRow, title="（拡張はまだありません）"))
            box.append(ge)

        def new_ext_form(self):
            """名前を聞いて、ひな形の拡張を作り、端末の nvim で開く。"""
            name_row = plain(Adw.EntryRow, title="命令の名前（英字・数字・_。例: swap）")
            group = Adw.PreferencesGroup(
                description=f"{EXT_DIR}/名前.py を作り、端末の nvim で開きます。保存した後、この画面の「再読み込み」で一覧に出ます。")
            group.add(name_row)
            msg = Gtk.Label(wrap=True, xalign=0)
            msg.add_css_class("error")

            def create():
                n = name_row.get_text().strip()
                if not n.isidentifier():
                    msg.set_label("英字・数字・_ で、数字以外から始まる名前にしてください")
                    return
                if n in builtin_commands():
                    msg.set_label(f"「{n}」は win の組み込みの命令と同じ名前です")
                    return
                if n in EXT:
                    msg.set_label(f"「{n}」はすでにあります（{EXT[n].file}）")
                    return
                path = os.path.join(EXT_DIR, f"{n}.py")
                if os.path.exists(path):
                    msg.set_label(f"{path} はすでにあります")
                    return
                os.makedirs(EXT_DIR, exist_ok=True)
                write_ext_support()
                with open(path, "w", encoding="utf-8") as f:
                    f.write(EXT_TEMPLATE.format(name=n))
                dlg.close()
                self.open_ext_source(path, EXT_TEMPLATE.splitlines().index("@command") + 2)
                self.toast(f"{path} を作りました。保存したら「再読み込み」を押してください")

            name_row.connect("entry-activated", lambda _r: create())
            btns = Gtk.Box(spacing=8, halign=Gtk.Align.END)
            btns.append(self.button("キャンセル", lambda: dlg.close()))
            btns.append(self.button("作って開く", create, "suggested-action"))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                          margin_start=18, margin_end=18)
            for w in (group, msg, btns):
                box.append(w)
            dlg = self.dialog("新しい拡張", box, 560)

        def open_ext_dir(self):
            os.makedirs(EXT_DIR, exist_ok=True)
            write_ext_support()
            Gio.AppInfo.launch_default_for_uri(GLib.filename_to_uri(EXT_DIR), None)

        def open_ext_source(self, path, line):
            if not path:
                return
            subprocess.Popen(["ptyxis", "--new-window", "-d", os.path.dirname(path), "--", "nvim", f"+{line or 1}", path],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

        def run_ext_command(self, name):
            subprocess.Popen([sys.executable, WIN_BIN, name], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            self.toast(f"「{name}」を実行しました")

        # ------------------------------------------------------------ ページ 3: セット
        def build_sets(self):
            box = self.pages["sets"]
            clear(box)
            intro = Gtk.Label(wrap=True, xalign=0, label=(
                "窓の並びに名前をつけて保存したものです。`win set 名前`、または `win set`（絞り込みの小窓）で呼べます。"
                f"保存先は {SETS} です。キーは「ショートカット」ページで付けます。"))
            intro.add_css_class("dim-label")
            box.append(intro)
            sets = load_sets()
            g = Adw.PreferencesGroup(title="保存したセット")
            g.set_header_suffix(self.suffix_box(
                self.button("＋ 手で書く", lambda: self.command_form(None, is_set=True)),
                self.button("今の窓の並びを保存…", self.save_arrangement_form, "suggested-action")))
            for name, c in sets.items():
                row = plain(Adw.ActionRow, title=name, subtitle=set_summary(c))
                row.set_subtitle_lines(1)
                row.add_suffix(self.suffix_box(
                    self.button("適用", lambda n=name: self.run_set(n), tip="いま適用する"),
                    self.icon_button("document-edit-symbolic", lambda n=name: self.command_form(n, is_set=True), "編集"),
                    self.icon_button("user-trash-symbolic", lambda n=name: self.confirm(
                        "セットを削除しますか？", f"「{n}」と、それに付けたキーを削除します。", "削除",
                        lambda: self.delete_set(n)), "削除")))
                g.add(row)
            if not sets:
                g.add(plain(Adw.ActionRow, title="（まだありません。右上の「今の窓の並びを保存…」から作れます）"))
            box.append(g)

        def run_set(self, name):
            subprocess.Popen([sys.executable, WIN_BIN, "set", name], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            self.toast(f"「{name}」を適用しました")

        def delete_set(self, name):
            sets = load_sets()
            sets.pop(name, None)
            save_sets(sets)
            kb_remove(set_slug(name))
            self.toast("削除しました")
            self.refresh()

        def run_command(self, name):
            subprocess.Popen([sys.executable, WIN_BIN, "run", name], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            self.toast(f"「{name}」を実行しました")

        def delete_command(self, name):
            cmds = load_commands()
            cmds.pop(name, None)
            save_commands(cmds)
            kb_remove(command_slug(name))
            self.toast("削除しました")
            self.refresh()

        def command_form(self, name, is_set=False):
            """コマンド（is_set なら セット）を作る・直すダイアログ。セットは win の命令だけを持つ。"""
            cmds = load_sets() if is_set else load_commands()
            c = cmds.get(name, {"type": "win", "run": ""}) if name else {"type": "win", "run": ""}
            arrange = c.get("type") == "arrange"
            name_row = plain(Adw.EntryRow, title="名前")
            name_row.set_text(name or "")
            type_row = plain(Adw.ComboRow, title="種類", model=Gtk.StringList.new(["win の命令（複数行可）", "シェルコマンド（複数行可）"]))
            type_row.set_selected(1 if c.get("type") == "shell" else 0)
            run_buf = Gtk.TextBuffer()
            run_buf.set_text(c.get("run", ""))
            run_view = Gtk.TextView(buffer=run_buf, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR, accepts_tab=False,
                                    top_margin=8, bottom_margin=8, left_margin=10, right_margin=10)
            run_scroll = Gtk.ScrolledWindow(child=run_view, min_content_height=260, vexpand=True, has_frame=True)

            def run_text():
                return run_buf.get_text(run_buf.get_start_iter(), run_buf.get_end_iter(), False)

            group = Adw.PreferencesGroup()
            group.add(name_row)
            if not arrange and not is_set:
                group.add(type_row)
            sig_label = Gtk.Label(wrap=True, xalign=0, use_markup=True, selectable=False, margin_start=4, margin_end=4)
            sig_label.add_css_class("dim-label")
            spec = {"layouts": load_config()["layouts"], "commands": load_commands(), **ext_spec(), "windows": [
                {"sel": selector_for(w, ws), "cls": w.get("wm_class") or "", "title": (w.get("title") or "")[:60]}
                for ws in [normal_windows(WindowCalls())] for w in reversed(ws)]}
            cand = {"shown": [], "token": "", "quiet": False}         # 候補 [(挿入する語, 説明)]、置き換える語、自動の書き換え中か
            cand_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.BROWSE, can_focus=False)
            cand_scroll = Gtk.ScrolledWindow(child=cand_list, hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                             max_content_height=230, min_content_width=460)
            popup = Gtk.Popover(autohide=False, has_arrow=False, can_focus=False, focusable=False, child=cand_scroll,
                                position=Gtk.PositionType.BOTTOM)
            popup.add_css_class("menu")
            cand_list.add_css_class("cand-list")                          # 選択中の行を目立たせる（CSS は設定窓の定義）
            cand_scroll.set_size_request(520, -1)
            popup.set_halign(Gtk.Align.START)                          # 左端をカーソルに合わせる（中央寄せだと左にはみ出す）
            popup.set_parent(run_view)

            def line_before_cursor():
                it = run_buf.get_iter_at_mark(run_buf.get_insert())
                start = it.copy()
                start.set_line_offset(0)
                return run_buf.get_text(start, it, False)

            def completion_text(before):
                """候補を出す対象の文字列（win の命令の部分）。出さない行は None。"""
                if type_row.get_selected() == 1:                     # シェル: win … で始まる行だけ
                    return before[4:] if before.startswith("win ") else None
                return before[4:] if before.startswith("win ") else before

            def hide_popup():
                if popup.is_visible():
                    popup.popdown()

            def refresh_candidates(force=False):
                before = line_before_cursor()
                text = completion_text(before)
                if text is None or (not text and not force) or (cand["quiet"] and not force):
                    hide_popup()
                    return
                items = suggest(text, spec)
                if type_row.get_selected() == 0:                     # win の命令の中では run / config は使えない
                    items = [(i, d) for i, d in items if i.strip() not in ("run", "config")]
                items = items[:8]
                cand["shown"], cand["token"] = items, text.split(" ")[-1]
                while (r := cand_list.get_row_at_index(0)) is not None:
                    cand_list.remove(r)
                if not items:
                    hide_popup()
                    return
                for ins, desc in items:
                    row_box = Gtk.Box(spacing=12, margin_top=4, margin_bottom=4, margin_start=10, margin_end=10)
                    first = Gtk.Label(label=ins.strip(), xalign=0, width_chars=14)
                    second = Gtk.Label(label=desc, xalign=0, hexpand=True, ellipsize=3, max_width_chars=48)
                    second.add_css_class("dim-label")
                    row_box.append(first)
                    row_box.append(second)
                    cand_list.append(Gtk.ListBoxRow(can_focus=False, child=row_box))
                cand_list.select_row(cand_list.get_row_at_index(0))
                rect = run_view.get_iter_location(run_buf.get_iter_at_mark(run_buf.get_insert()))
                x, y = run_view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, rect.x, rect.y)
                area = Gdk.Rectangle()
                area.x, area.y, area.width, area.height = x, y, 1, rect.height
                popup.set_pointing_to(area)
                if not popup.is_visible():
                    popup.popup()

            def accept_candidate():
                sel = cand_list.get_selected_row()
                if sel is None or not cand["shown"]:
                    return
                ins = cand["shown"][sel.get_index()][0]
                end = run_buf.get_iter_at_mark(run_buf.get_insert())
                start = end.copy()
                start.backward_chars(len(cand["token"]))
                run_buf.delete(start, end)
                cand["quiet"] = True
                run_buf.insert_at_cursor(ins)
                cand["quiet"] = False
                refresh_candidates()                                  # 続けて次の語の候補を出す
                update_signature()

            def update_signature(*_):
                before = line_before_cursor()
                text = completion_text(before) if before.strip() else None
                markup = signature_markup(text) if text else None
                if type_row.get_selected() == 1 and text is None:
                    markup = None
                sig_label.set_markup(markup or "命令を打つと候補が出ます（Tab で確定、↑↓で選択、Esc で閉じる、Ctrl+Space で候補を出す）。")

            def on_changed(_b):
                refresh_candidates()
                update_signature()

            def on_cursor(*_):
                update_signature()
                if popup.is_visible():                                # 動かしたら、その位置での候補に合わせる（なければ閉じる）
                    refresh_candidates(force=True)

            def on_run_key(_c, keyval, _kc, state):
                name = Gdk.keyval_name(keyval)
                ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
                if ctrl and name == "space":
                    refresh_candidates(force=True)
                    return True
                if not popup.is_visible():
                    return False
                if name in ("Tab", "ISO_Left_Tab"):
                    accept_candidate()
                    return True
                if name in ("Down", "Up"):
                    sel = cand_list.get_selected_row()
                    n = len(cand["shown"])
                    cand_list.select_row(cand_list.get_row_at_index(((sel.get_index() if sel else 0) + (1 if name == "Down" else -1)) % n))
                    return True
                if name == "Escape":
                    hide_popup()
                    return True
                return False

            key_ctrl = Gtk.EventControllerKey()
            key_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            key_ctrl.connect("key-pressed", on_run_key)
            run_view.add_controller(key_ctrl)
            run_buf.connect("changed", on_changed)
            run_buf.connect("notify::cursor-position", on_cursor)
            update_signature()
            help_l = Gtk.Label(wrap=True, xalign=0)
            help_l.add_css_class("dim-label")
            msg = Gtk.Label(wrap=True, xalign=0)
            msg.add_css_class("error")

            def update_help(*_):
                if arrange:
                    help_l.set_label(f"窓の並び {len(c.get('windows', []))} 枚を保存しています（作り直すには「今の窓の並びを保存」を、同じ名前で）。")
                elif type_row.get_selected() == 0:
                    help_l.set_label("win の命令を、1 行に 1 つ書きます。上から順に実行し、失敗したらそこで止まります。# で始まる行は無視されます。"
                                     + ("ふつうは最初の layout 行が並びで、一覧のプレビューにもその行が使われます。" if is_set else ""))
                else:
                    help_l.set_label("シェルで実行されます（複数行はそのまま 1 つのスクリプトになります）。win の命令を呼ぶときは頭に win を付けます。")

            def validate():
                n = name_row.get_text().strip()
                if not n:
                    return "名前を入力してください"
                if n != name and n in cmds:
                    return f"「{n}」はすでにあります"
                if not arrange:
                    text = run_text().strip()
                    if not text:
                        return "内容を入力してください"
                    if type_row.get_selected() == 0:
                        return check_win_line(text)
                return None

            def save():
                err = validate()
                if err:
                    msg.set_label(err)
                    return
                n = name_row.get_text().strip()
                new = dict(c)
                if not arrange:
                    new["type"] = "shell" if type_row.get_selected() == 1 else "win"
                    new["run"] = run_text().strip()
                if name and n != name:                        # 名前の変更: 並びを保ち、キーも付け替える
                    cmds.pop(name)
                    slug, verb = (set_slug, "set") if is_set else (command_slug, "run")
                    old = next((e for e in kb_list() if e["slug"] == slug(name)), None)
                    if old:
                        kb_remove(slug(name))
                        kb_set(slug(n), name=f"win {verb}: {n}", command=f"{WIN_BIN} {verb} {shlex.quote(n)}",
                               binding=old["binding"])
                cmds[n] = new
                (save_sets if is_set else save_commands)(cmds)
                dlg.close()
                self.toast("保存しました")
                self.refresh()

            def try_it():
                err = validate()
                if err:
                    msg.set_label(err)
                    return
                msg.set_label("")
                tmp = dict(c)
                if not arrange:
                    tmp["type"] = "shell" if type_row.get_selected() == 1 else "win"
                    tmp["run"] = run_text().strip()
                if arrange:
                    self.toast("保存済みの並びは、保存後に「実行」で試せます")
                    return
                if tmp["type"] == "shell":
                    subprocess.Popen(["sh", "-c", tmp["run"]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
                else:
                    def seq():                                   # 上から順に。失敗したら止める
                        for line in win_lines(tmp["run"]):
                            argv = shlex.split(line)
                            argv = argv[1:] if argv[0] == "win" else argv
                            r = subprocess.run([sys.executable, WIN_BIN] + argv, stdin=subprocess.DEVNULL,
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            if r.returncode:
                                break
                    threading.Thread(target=seq, daemon=True).start()
                self.toast("実行しました")

            type_row.connect("notify::selected", update_help)
            update_help()
            btns = Gtk.Box(spacing=8, halign=Gtk.Align.END)
            if not arrange:
                btns.append(self.button("試す", try_it, tip="保存せずに、いま実行します"))
            btns.append(self.button("キャンセル", lambda: dlg.close()))
            btns.append(self.button("保存", save, "suggested-action"))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                          margin_start=18, margin_end=18)
            if arrange:
                widgets = (group, help_l, msg, btns)
            else:
                label = Gtk.Label(label="内容", xalign=0)
                label.add_css_class("heading")
                widgets = (group, label, run_scroll, sig_label, help_l, msg, btns)
            for w in widgets:
                box.append(w)
            what = "セット" if is_set else "コマンド"
            dlg = self.dialog(f"{what}を編集" if name else f"新しい{what}", box, 780, 0 if arrange else 800)
            if not arrange:
                dlg.connect("closed", lambda _d: popup.unparent())

        def save_arrangement_form(self):
            name_row = plain(Adw.EntryRow, title="名前（例: 作業用）")
            group = Adw.PreferencesGroup(
                description="いま表に出ている窓（この画面にあるもの）を、型と窓の列（例: layout v(1,2,1) firefox? ...）として保存します。"
                            "ピクセルは保存しないので、画面の大きさが変わっても使えます。窓がなければ起動します。`win set 名前` で呼べます。")
            group.add(name_row)
            fx_row = plain(Adw.SwitchRow, title="Firefox のタブも保存する",
                           subtitle="開いているタブの URL を保存し、窓がなければそのタブで開き直します。URL は平文で保存されます")
            tm_row = plain(Adw.SwitchRow, title="端末の作業ディレクトリも保存する",
                           subtitle="タブごとの作業ディレクトリを保存し、窓がなければそこで開き直します")
            state_group = Adw.PreferencesGroup(
                title="状態も保存する（必要なときだけ）",
                description="特定の作業を繰り返すときのための設定です。汎用の並びでは、オフのままにしてください（開く場所が固定されます）。")
            state_group.add(fx_row)
            state_group.add(tm_row)
            msg = Gtk.Label(wrap=True, xalign=0)
            msg.add_css_class("error")

            def state():
                return tuple(k for k, r in (("firefox", fx_row), ("terminal", tm_row)) if r.get_active())

            def do_save(overwrite=False):
                n = name_row.get_text().strip()
                if not n:
                    msg.set_label("名前を入力してください")
                    return
                try:
                    count, notes = save_arrangement(WindowCalls(), n, overwrite, state())
                except WinError as e:
                    if "すでにあります" in str(e):
                        self.confirm("上書きしますか？", f"「{n}」はすでにあります。", "上書き",
                                     lambda: (dlg.close(), do_save_force(n)), destructive=False)
                    else:
                        msg.set_label(str(e))
                    return
                dlg.close()
                self.toast(f"「{n}」を保存しました（窓 {count} 枚）" + ("　注意: " + " ／ ".join(notes) if notes else ""))
                self.refresh()

            def do_save_force(n):
                try:
                    count, notes = save_arrangement(WindowCalls(), n, True, state())
                    self.toast(f"「{n}」を上書きしました（窓 {count} 枚）" + ("　注意: " + " ／ ".join(notes) if notes else ""))
                except WinError as e:
                    self.toast(str(e))
                self.refresh()

            btns = Gtk.Box(spacing=8, halign=Gtk.Align.END)
            btns.append(self.button("キャンセル", lambda: dlg.close()))
            btns.append(self.button("保存", lambda: do_save(), "suggested-action"))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                          margin_start=18, margin_end=18)
            for w in (group, state_group, msg, btns):
                box.append(w)
            dlg = self.dialog("今の窓の並びを保存", box, 560)

        # ------------------------------------------------------------ ページ 4: 型
        def layout_preview(self, fixed, expr, w=380, h=230):
            clear(fixed)
            try:
                rects = compute_rects(expr, (0, 0, 1000, 1000), 0)
            except WinError as e:
                return str(e)
            for i, (x, y, rw, rh) in enumerate(rects):
                lab = Gtk.Label(label=str(i + 1))
                lab.add_css_class("tile-box")
                lab.set_size_request(max(8, int(rw * w / 1000) - 2), max(8, int(rh * h / 1000) - 2))
                fixed.put(lab, int(x * w / 1000) + 1, int(y * h / 1000) + 1)
            return ""

        def build_layouts(self):
            box = self.pages["layouts"]
            clear(box)
            user, insets, gap = read_layout_file()
            allay = dict(BUILTIN_LAYOUTS)
            allay.update(user)
            intro = Gtk.Label(wrap=True, xalign=0, label=(
                "窓を並べる「型」です。`v(…)` は左右に、`h(…)` は上下に分けます。数は割合で、`2:v(1,1)` のように、"
                "割合つきで中をさらに分けられます。略記もあり、`,` で左右、`/` で上下、`( )` でまとめ、`2:` で割合です"
                "（例: `1,2:1/1/1,1` = v(1,2:h(1,1,1),1)。引用符は要りません）。組み込みの型は、複製して編集できます。"))
            intro.add_css_class("dim-label")
            box.append(intro)

            names = list(allay)
            current = {"name": names[0] if names else "", "new": False}
            lst = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
            lst.add_css_class("boxed-list")
            for n in names:
                r = plain(Adw.ActionRow, title=n, subtitle=allay[n])
                r.set_subtitle_lines(1)
                tag = "自作" if n in user else "組み込み"
                badge = Gtk.Label(label=tag + ("（上書き）" if n in user and n in BUILTIN_LAYOUTS else ""), valign=Gtk.Align.CENTER)
                badge.add_css_class("dim-label")
                r.add_suffix(badge)
                lst.append(r)
            lst_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=lst, hexpand=False)
            lst_scroll.set_size_request(290, 300)

            preview = Gtk.Fixed(halign=Gtk.Align.CENTER, margin_top=6, margin_bottom=6)
            preview.set_size_request(380, 230)
            name_row = plain(Adw.EntryRow, title="名前")
            expr_row = plain(Adw.EntryRow, title="式（例: h(1,2:v(1,1),1)　略記: 1,2:1/1/1,1）")
            eg = Adw.PreferencesGroup()
            eg.add(name_row)
            eg.add(expr_row)
            status = Gtk.Label(wrap=True, xalign=0)
            ed = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            save_b = self.button("保存", lambda: save_layout(), "suggested-action")
            del_b = self.button("削除", lambda: del_layout())
            dup_b = self.button("複製して編集", lambda: dup_layout())
            new_b = self.button("＋ 新しい型", lambda: new_layout())
            row_btns = Gtk.Box(spacing=8, halign=Gtk.Align.END)
            for b in (new_b, dup_b, del_b, save_b):
                row_btns.append(b)
            for w in (preview, eg, status, row_btns):
                ed.append(w)
            body = Gtk.Box(spacing=18)
            body.append(lst_scroll)
            ed.set_hexpand(True)
            body.append(ed)
            g = Adw.PreferencesGroup(title="型の一覧と編集")
            g.add(body)
            box.append(g)

            def load(name):
                current["name"], current["new"] = name, False
                builtin_only = name in BUILTIN_LAYOUTS and name not in user
                name_row.set_text(name)
                expr_row.set_text(allay[name])
                name_row.set_editable(not builtin_only)
                expr_row.set_editable(not builtin_only)
                save_b.set_sensitive(not builtin_only)
                del_b.set_sensitive(name in user)
                dup_b.set_sensitive(True)
                check()

            def check(*_):
                err = self.layout_preview(preview, expr_row.get_text().strip())
                nm = name_row.get_text().strip()
                if not err and not nm:
                    err = "名前を入力してください"
                if not err and (current["new"] or nm != current["name"]) and nm in allay:
                    err = f"「{nm}」はすでにあります"
                if err:
                    status.set_label(err)
                    status.remove_css_class("success")
                    status.add_css_class("error")
                else:
                    n = len(compute_rects(expr_row.get_text().strip(), (0, 0, 1, 1), 0))
                    status.set_label(f"タイル {n} 枚")
                    status.remove_css_class("error")
                    status.add_css_class("dim-label")
                editable = name_row.get_editable()
                save_b.set_sensitive(editable and not err)

            def save_layout():
                nm, ex = name_row.get_text().strip(), expr_row.get_text().strip()
                u = dict(user)
                if not current["new"] and current["name"] != nm:
                    u.pop(current["name"], None)
                u[nm] = ex
                write_layout_file(u, insets, gap)
                self.layout_to_select = nm
                self.toast(f"型「{nm}」を保存しました")
                self.refresh()

            def del_layout():
                u = dict(user)
                u.pop(current["name"], None)
                write_layout_file(u, insets, gap)
                self.toast(f"型「{current['name']}」を削除しました")
                self.refresh()

            def dup_layout():
                base = expr_row.get_text().strip() or "full"
                nm = name_row.get_text().strip() or "my-layout"
                k = 2
                while f"{nm}-{k}" in allay:
                    k += 1
                current["new"] = True
                name_row.set_editable(True)
                expr_row.set_editable(True)
                name_row.set_text(f"{nm}-{k}")
                expr_row.set_text(base)
                del_b.set_sensitive(False)
                check()

            def new_layout():
                dup_layout()
                name_row.set_text("my-layout" if "my-layout" not in allay else "my-layout-2")
                expr_row.set_text("v(1,1)")

            lst.connect("row-selected", lambda _l, r: load(names[r.get_index()]) if r is not None else None)
            name_row.connect("changed", check)
            expr_row.connect("changed", check)
            want = getattr(self, "layout_to_select", None)               # 保存した型を選び直す（なければ先頭）
            self.layout_to_select = None
            pos = names.index(want) if want in names else 0
            lst.select_row(lst.get_row_at_index(pos))
            if pos:
                GLib.idle_add(lambda: (lst.get_row_at_index(pos).grab_focus(), False)[1])   # 一覧をそこまでスクロールする

            # 配置の設定（隙間・作業領域の余白）
            g2 = Adw.PreferencesGroup(title="配置の設定",
                                      description="タイルどうしの隙間と、作業領域の余白（画面の端から窓を置かない幅）。単位は px。")
            spins = {}
            for key, label, val in (("gap", "タイルどうしの隙間", gap), ("top", "上の余白（上部バーの高さ。主モニタだけに適用）", insets["top"]),
                                    ("bottom", "下の余白", insets["bottom"]), ("left", "左の余白", insets["left"]),
                                    ("right", "右の余白", insets["right"])):
                sp = plain(Adw.SpinRow, title=label, adjustment=Gtk.Adjustment(value=val, lower=0, upper=400, step_increment=1))
                spins[key] = sp
                g2.add(sp)

            def save_settings():
                ins = {k: int(spins[k].get_value()) for k in ("top", "bottom", "left", "right")}
                write_layout_file(user, ins, int(spins["gap"].get_value()))
                self.toast("配置の設定を保存しました")
                self.refresh()

            g2.set_header_suffix(self.button("保存", save_settings, "suggested-action"))
            box.append(g2)

    class ConfigApp(Adw.Application):
        def __init__(self):
            super().__init__(application_id=CONFIG_APP_ID)
            self.win = None

        def do_activate(self):
            if self.win is None:
                self.win = ConfigWindow(self)
            self.win.stack.set_visible_child_name(page)
            self.win.present()

    ConfigApp().run([])


# ---------------------------------------------------------------- いまの窓と同じ形にする（win here）

HERE_HINT = "↑↓ 選択 ・ Enter 決定（この窓と同じ位置・大きさで前面へ） ・ 先頭 ! でアプリ ・ Esc 閉じる"


def window_row_title(w, d):
    """窓の候補の表示名（最小化・別のワークスペースの印つき）。"""
    t = (w.get("title") or "")[:90]
    if d.get("minimized"):
        t += "  （最小化）"
    if not w.get("in_current_workspace"):
        t += f"  [WS {w.get('workspace', 0) + 1}]"
    return t


def bring_here(wc, w, rect, maximized, workspace):
    """w を rect と同じ位置・大きさ（最大化なら最大化）にして、前面に出す。通知する文を返す（無ければ空）。"""
    if not w.get("in_current_workspace"):
        wc.call("MoveToWorkspace", "uu", w["id"], max(0, workspace))
    if wc.details(w["id"]).get("minimized"):
        wc.simple("Unminimize", w["id"])
    notice = ""
    if maximized:
        wc.simple("Maximize", w["id"])
    else:
        got = place_settled(wc, w["id"], rect)
        if got:
            notice = f"希望の大きさにならず {got[2]}x{got[3]} です（最小サイズなど）"
    wc.simple("Activate", w["id"])
    return notice


def cmd_here(args):
    wc = WindowCalls()
    cur = focused(wc)
    d = wc.details(cur["id"])
    rect = (d["x"], d["y"], d["width"], d["height"])
    maximized = bool(d.get("maximized_horizontally") and d.get("maximized_vertically"))
    ws = cur.get("workspace", 0)
    cands = [w for w in reversed(normal_windows(wc)) if w["id"] != cur["id"]]
    if args.selector:
        if args.selector.startswith("!"):
            w = launch(wc, args.selector[1:])
        else:
            found = find_windows(wc, args.selector, cands)
            if not found:
                raise WinError(f"窓が見つかりません: {args.selector}")
            w = found[0]
        notice = bring_here(wc, w, rect, maximized, ws)
        if notice:
            print(notice, file=sys.stderr)
        return 0
    return gui_here(wc, cur, rect, maximized, ws, cands)


def gui_here(wc, cur, rect, maximized, workspace, cands):
    """絞り込みの小窓で窓（先頭 ! でアプリ）を選び、いまの窓と同じ形にして前面に出す。"""
    ax, ay, aw, ah = work_area(load_config())
    box = [max(0.0, (rect[0] - ax) / aw), max(0.0, (rect[1] - ay) / ah)]
    norm = [(box[0], box[1], min(1.0 - box[0], rect[2] / aw), min(1.0 - box[1], rect[3] / ah))]
    rows = [{"id": w["id"], "cls": w.get("wm_class") or "", "title": window_row_title(w, wc.details(w["id"])),
             "icon": icon_for_class(w.get("wm_class"))}
            for w in cands]
    by_id = {w["id"]: w for w in cands}
    child = spawn_tilepick()

    def send(msg):
        child.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        child.stdin.flush()

    def tile(notice="", first=False):
        msg = {"cmd": "tile", "index": 0, "n": 1, "layout": "", "title": "ここに持ってくる", "hint": HERE_HINT,
               "rects": norm, "labels": [""], "windows": rows, "notice": notice}
        if first:
            msg["apps"] = list_apps()
        return msg

    chosen, notice = None, ""
    try:
        send(tile(first=True))
        wid = center_and_focus(wc, child, TILEPICK_APP_ID)
        while True:
            line = child.stdout.readline()
            try:
                res = json.loads(line) if line else {"act": "cancel"}
            except ValueError:
                res = {"act": "cancel"}
            act = res.get("act")
            try:
                if act == "win":
                    chosen = by_id.get(res["id"])
                    if chosen is None:
                        raise WinError("その窓はもう閉じられました")
                elif act in ("app", "cmd"):
                    send({"cmd": "busy", "text": "起動しています…"})
                    chosen = launch_app(wc, res["id"], 12)[0] if act == "app" else launch(wc, res["text"], 12)
                else:
                    return 0
            except WinError as e:
                send(tile(str(e)))
                wc.simple("Activate", wid)
                continue
            break
    finally:
        try:
            send({"cmd": "quit"})
        except (OSError, ValueError):
            pass
        try:
            child.wait(3)
        except subprocess.TimeoutExpired:
            child.kill()
    time.sleep(0.2)                          # 小窓が閉じて、フォーカスが戻るのを待ってから動かす
    notice = bring_here(wc, chosen, rect, maximized, workspace)
    if notice:
        print(notice, file=sys.stderr)
    return 0


def cmd_config(args):
    run_config(args.page)
    return 0


def cmd_pick(args):
    wc = WindowCalls()
    pool = list(reversed(normal_windows(wc)))
    if not pool:
        raise WinError("窓がありません")
    res = pick_window(wc, pool, [], "窓を選ぶ")
    if res is None:
        return 1
    if args.id:
        print(res["id"])
        return 0
    if wc.details(res["id"]).get("minimized"):
        wc.simple("Unminimize", res["id"])
    wc.simple("Activate", res["id"])
    return 0


def cmd_move(args):
    wc = WindowCalls()
    for w in targets(wc, args.window):
        wc.call("Move", "uii", w["id"], args.x, args.y)
    return 0


def cmd_size(args):
    wc = WindowCalls()
    for w in targets(wc, args.window):
        wc.call("Resize", "uuu", w["id"], args.w, args.h)
    return 0


def cmd_state(args):
    wc = WindowCalls()
    method = {"max": "Maximize", "unmax": "Unmaximize", "min": "Minimize", "unmin": "Unminimize",
              "above": "MakeAbove", "unabove": "UnmakeAbove"}[args.action]
    for w in targets(wc, args.window):
        wc.simple(method, w["id"])
    return 0


def cmd_close(args):
    wc = WindowCalls()
    for w in targets(wc, args.window):
        wc.simple("Close", w["id"])
    return 0


# ---------------------------------------------------------------- 拡張（~/.config/win/ext/*.py）

EXT_DIR = os.environ.get("WIN_EXT") or os.path.join(os.path.dirname(COMMANDS), "ext")
EXT = {}                # 命令の名前 → ExtCommand（@command を付けた関数）
EXT_ERRORS = []         # [(ファイル, 説明)]。読み込めなかった拡張
_EXT_STATE = {"loaded": False, "mods": []}


class Window:
    """窓 1 枚。位置と大きさは rect（x, y, 幅, 高さ。論理ピクセル）で読み書きする。"""

    def __init__(self, info):
        self._info = info

    @property
    def id(self):
        return self._info["id"]

    @property
    def cls(self):
        return self._info.get("wm_class") or ""

    @property
    def title(self):
        return self._info.get("title") or ""

    @property
    def maximized(self):
        d = _wc().details(self.id)
        return bool(d.get("maximized_horizontally") and d.get("maximized_vertically"))

    @property
    def rect(self):
        return tuple(_wc().rect(self.id))

    @rect.setter
    def rect(self, r):
        wc = _wc()
        if self.maximized:
            wc.simple("Unmaximize", self.id)
        place_settled(wc, self.id, tuple(int(v) for v in r))

    def focus(self):
        wc = _wc()
        if wc.details(self.id).get("minimized"):
            wc.simple("Unminimize", self.id)
        wc.simple("Activate", self.id)

    def max(self):
        _wc().simple("Maximize", self.id)

    def unmax(self):
        _wc().simple("Unmaximize", self.id)

    def min(self):
        _wc().simple("Minimize", self.id)

    def unmin(self):
        _wc().simple("Unminimize", self.id)

    def close(self):
        _wc().simple("Close", self.id)

    @property
    def minimized(self):
        return bool(_wc().details(self.id).get("minimized"))

    def move(self, x, y):
        _, _, w, h = self.rect                            # rect と同じ枠の座標で動かす（Move は影の分ずれる）
        _wc().move_resize(self.id, int(x), int(y), w, h)
        self._settle(lambda r: r[:2] == (int(x), int(y)))

    def resize(self, width, height):
        x, y, _, _ = self.rect
        _wc().move_resize(self.id, x, y, int(width), int(height))
        self._settle(lambda r: r[2:] == (int(width), int(height)))

    def _settle(self, done, timeout=0.6):
        """GNOME が動かし終えるまで（最大 timeout 秒）待つ。直後に rect を読んでも新しい値になるように。"""
        end = time.time() + timeout
        while time.time() < end and not done(tuple(_wc().rect(self.id))):
            time.sleep(0.03)

    def above(self):
        _wc().simple("MakeAbove", self.id)

    def unabove(self):
        _wc().simple("UnmakeAbove", self.id)

    def __eq__(self, other):
        return isinstance(other, Window) and other.id == self.id

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return f"Window({self.id}, {self.cls!r}, {self.title[:30]!r})"


_WC = {"wc": None}


def _wc():
    if _WC["wc"] is None:
        _WC["wc"] = WindowCalls()
    return _WC["wc"]


def api_at(sel):
    """窓の指定（クラス・題名の一部、ID、@left などの位置・状態）に当たる窓 1 枚。なければ WinError。"""
    return Window(target(_wc(), sel))


def api_find(sel):
    """窓の指定に当たる窓すべて（前面に近い順）。なければ空のリスト。"""
    wc = _wc()
    return [Window(w) for w in find_windows(wc, sel, normal_windows(wc)[::-1])]


def api_windows():
    """今のワークスペースで最小化されていない窓（前面に近い順）。"""
    return [Window(w) for w in usable_windows(_wc())]


def api_focused():
    """前面の窓。"""
    return Window(focused(_wc()))


def api_area():
    """窓を置ける領域 (x, y, 幅, 高さ)。基準のモニタから、上下左右の余白を除いたもの。"""
    return tuple(work_area(load_config()))


def _run_argv(argv):
    """win の命令（引数のリスト）をこのプロセスで実行する。失敗したら WinError。"""
    rc, so, se = run_inline([str(a) for a in argv])
    if so:
        print(so, end="")
    if rc:
        raise WinError(se.strip().removeprefix("win: ") or f"失敗しました: {' '.join(map(str, argv))}")


def api_run(line):
    """win の命令を 1 行（複数行なら上から順に）実行する。失敗したら WinError。"""
    for l in win_lines(line):
        argv = shlex.split(l)
        _run_argv(argv[1:] if argv and argv[0] == "win" else argv)


def _sel_text(w):
    return str(w.id) if isinstance(w, Window) else str(w)


def api_layout(expr, *windows, gap=None):
    """型 expr のタイルに、windows を順に並べる。"""
    _run_argv(["layout", expr, *map(_sel_text, windows)] + (["--gap", gap] if gap is not None else []))


def api_apply_set(name):
    """保存したセットを適用する。"""
    sets = load_sets()
    if name not in sets:
        raise WinError(f"セットが見つかりません: {name}（一覧は win help sets）")
    if run_entry(sets[name]):
        raise WinError(f"セット「{name}」を適用できませんでした")


def api_run_command(name):
    """登録したコマンドを実行する。"""
    cmds = load_commands()
    if name not in cmds:
        raise WinError(f"コマンドが見つかりません: {name}（一覧は win help commands）")
    if run_entry(cmds[name]):
        raise WinError(f"コマンド「{name}」が失敗しました")


def api_nav(direction):
    """前面の窓から見て、その向きの窓へフォーカスを移す。"""
    _run_argv(["nav", direction])


def api_launch(cmdline, timeout=20):
    """コマンドを起動し、新しく出た窓を返す。"""
    return Window(launch(_wc(), cmdline, timeout))


def api_layouts():
    """型の一覧 {名前: 式}。"""
    return dict(load_config()["layouts"])


def api_browse(*urls):
    """Firefox を新しい窓で開き、URL をタブとして並べる。"""
    _run_argv(["browse", *urls])


def api_term(*dirs):
    """端末を、作業ディレクトリごとのタブつきで新しく開く。"""
    _run_argv(["term", *dirs])


class _Sel:
    """命令の引数の既定値にする窓の指定（呼ばれたときに窓にする）。"""

    def __init__(self, spec):
        self.spec = spec

    def __repr__(self):
        return self.spec


def api_sel(spec):
    """引数の既定値に書く窓の指定（例 a: Window = sel("@left")）。型の上では Window として扱われる。"""
    return _Sel(spec)


def api_tiles(expr, rect=None):
    """rect（省くと作業領域）を型 expr で分けた、各タイルの (x, y, 幅, 高さ)。タイルの間には設定の隙間を取る。"""
    cfg = load_config()
    return [tuple(r) for r in compute_rects(resolve_layout(cfg, expr), tuple(rect) if rect else work_area(cfg), cfg["gap"])]


def api_slots():
    """いまの並び（窓の位置から逆算）の窓を、番号順に。"""
    wc, cfg = _wc(), load_config()
    cur = current_tiles(wc, cfg)
    if cur["tree"] is None:
        return []
    return [Window(cur["by_id"][i]) for i in tile_order(cur, cfg)[1]]


def api_resolve(spec):
    """layout の窓の列と同じ書き方を窓にする: - は None（空ける）、!コマンド は起動した窓、クラス名? はなければ起動、ほかは at()。"""
    if spec in ("-", "_"):
        return None
    wc = _wc()
    if spec.startswith("!"):
        return Window(launch(wc, spec[1:]))
    base, optional, fallback = parse_window_spec(spec)
    found = find_windows(wc, base, normal_windows(wc)[::-1])
    if found:
        return Window(found[0])
    if optional:
        cmdline = fallback or launch_for_class(base)
        if not cmdline:
            raise WinError(f"窓が見つからず、起動コマンドも分かりません: {base}")
        return Window(launch(wc, cmdline))
    raise WinError(f"窓が見つかりません: {spec}")


def api_pick(title="窓を選ぶ", slot=None, launch=True, exclude=(), rect=None):
    """layout -i と同じ小窓で、窓を 1 枚その場で選ぶ（先頭 ! でアプリを起動して、その窓）。取り消したら WinError。"""
    wc, rects, labels, index = _wc(), None, None, 0
    if rect is not None:                                  # まだ窓のない場所: いまの並びの地図に、その場所を足して強調する
        rects, labels = slot_map(wc)
        rects, labels = list(rects or []), list(labels or [])
        ax, ay, aw, ah = work_area(load_config())
        x, y, w_, h_ = rect
        rects.append(((x - ax) / aw, (y - ay) / ah, w_ / aw, h_ / ah))
        labels.append("ここ")
        index = len(rects) - 1
    if slot == 0:                                         # 0 は前面の窓: そのタイルを強調する（並びの外なら強調なし）
        slot = api_slot_of(api_focused())
    if slot is not None and rect is None:
        rects, labels = slot_map(wc)
        if rects is None or not 1 <= slot <= len(rects):
            raise WinError(f"タイル {slot} がありません（いまの並びのタイルは {len(rects or [])} 枚）")
        index = slot - 1
    w = pick_interactive(wc, title, rects, index, labels, allow_launch=launch, exclude={x.id for x in exclude})
    if w is None:
        raise WinError("選ぶのを取り消しました")
    return Window(w)


def api_slot_of(w):
    """いまの並びで、w が何番目のタイルにあるか（1 から）。並びの中になければ None。"""
    cfg = load_config()
    cur = current_tiles(_wc(), cfg)
    if cur["tree"] is None:
        return None
    order = tile_order(cur, cfg)[1]
    return order.index(w.id) + 1 if w.id in order else None


def api_notify(text, title="win"):
    """デスクトップの通知を出す。"""
    subprocess.run(["notify-send", "-a", "win", title, str(text)], timeout=5)


class ExtCommand:
    """@command を付けた関数。引数は関数の宣言から読む。"""

    def __init__(self, fn, name):
        self.fn, self.name = fn, name
        try:
            self.sig = inspect.signature(fn, eval_str=True)
        except Exception:                                 # 注釈が評価できなければ、文字列のまま
            self.sig = inspect.signature(fn)
        doc = inspect.getdoc(fn) or ""
        lines = doc.splitlines()
        self.summary = lines[0] if lines else ""
        self.doc = doc
        self.param_docs = {}                              # 説明文の「名前: 説明」の行
        for l in lines[1:]:
            m = re.match(r"\s*(\*{0,2}\w+)\s*[:：]\s*(.+)", l)
            if m and m.group(1).lstrip("*") in self.sig.parameters:
                self.param_docs[m.group(1).lstrip("*")] = m.group(2).strip()
        try:
            self.file, self.line = inspect.getsourcefile(fn), inspect.getsourcelines(fn)[1]
        except (OSError, TypeError):
            self.file, self.line = None, 0

    def parts(self):
        """入力欄の書式表示（SIGNATURES と同じ形）の部品。"""
        out = []
        for p in self.sig.parameters.values():
            desc = _param_desc(p, self.param_docs.get(p.name))
            if p.kind == p.VAR_POSITIONAL:
                out.append(("rep", p.name, desc, True))
            elif p.kind == p.KEYWORD_ONLY or p.annotation is bool:
                if p.annotation is bool:
                    out.append(("flag", "--" + p.name.replace("_", "-"), desc))
                else:
                    out.append(("opt", "--" + p.name.replace("_", "-"), p.name, desc))
            elif p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
                out.append(("pos", p.name, desc, p.default is not p.empty))
        return out

    def py_signature(self, code=False):
        """関数の宣言の形（例 swap(a: Window = "@left", b: Window = "@right")）。code なら既定値もコードどおり（sel("@left")）。"""
        bits = []
        for p in self.sig.parameters.values():
            t = "*" * (p.kind == p.VAR_POSITIONAL) + "**" * (p.kind == p.VAR_KEYWORD) + p.name
            if p.annotation is not p.empty:
                t += f": {_type_name(p.annotation)}"
            if p.default is not p.empty:
                t += f" = {_default_text(p.default, code)}"
            bits.append(t)
        return f"{self.name}({', '.join(bits)})"

    def usage(self):
        bits = []
        for part in self.parts():
            if part[0] == "pos":
                bits.append(f"[{part[1]}]" if part[3] else part[1])
            elif part[0] == "rep":
                bits.append(f"[{part[1]} …]")
            elif part[0] == "opt":
                bits.append(f"[{part[1]} {part[2]}]")
            else:
                bits.append(f"[{part[1]}]")
        return " ".join([f"win {self.name}"] + bits)

    def call(self, tokens):
        args, kwargs = self.bind(tokens)
        return self.fn(*args, **kwargs)

    def bind(self, tokens):
        """入力の語を、関数の引数に変換して割り当てる。"""
        params = self.sig.parameters
        named, positional, i = {}, [], 0
        while i < len(tokens):
            t = tokens[i]
            if t.startswith("--") and len(t) > 2:
                pname = t[2:].replace("-", "_")
                p = params.get(pname)
                if p is None or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                    raise WinError(f"{self.name}: 知らないオプションです: {t}（書式: {self.usage()}）")
                if p.annotation is bool:
                    named[pname] = True
                else:
                    i += 1
                    if i >= len(tokens):
                        raise WinError(f"{self.name}: {t} の値がありません")
                    named[pname] = _convert(p, tokens[i], self.name)
            else:
                positional.append(t)
            i += 1
        args = []
        for p in params.values():
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.name not in named:
                if positional:
                    args.append(_convert(p, positional.pop(0), self.name))
                elif p.default is not p.empty:
                    args.append(_default(p, self.name))
                else:
                    raise WinError(f"{self.name}: {p.name} がありません（書式: {self.usage()}）")
            elif p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
                args.append(named.pop(p.name))
            elif p.kind == p.VAR_POSITIONAL:
                args += [_convert(p, t, self.name) for t in positional]
                positional = []
            elif p.kind == p.KEYWORD_ONLY and p.name not in named:
                if p.default is p.empty:
                    raise WinError(f"{self.name}: --{p.name} がありません（書式: {self.usage()}）")
                named[p.name] = _default(p, self.name)
        if positional:
            raise WinError(f"{self.name}: 引数が多すぎます: {' '.join(positional)}（書式: {self.usage()}）")
        return args, named


_TYPE_LABELS = {Window: "窓", int: "整数", float: "数", str: "文字列", bool: "オン/オフ"}


def is_window_ann(ann):
    """引数の注釈が窓か（Window、または Window | None）。"""
    return ann is Window or (typing.get_origin(ann) in (typing.Union, types.UnionType) and Window in typing.get_args(ann))


def _type_name(ann):
    if typing.get_origin(ann) in (typing.Union, types.UnionType):
        return " | ".join("None" if a is type(None) else _type_name(a) for a in typing.get_args(ann))
    return ann if isinstance(ann, str) else getattr(ann, "__name__", None) or str(ann)


def _default_text(v, code=False):
    if isinstance(v, _Sel):
        spec = json.dumps(v.spec, ensure_ascii=False)
        return f"sel({spec})" if code else spec
    return repr(v)


def _param_desc(p, doc):
    """引数の説明: 宣言の形（名前: 型 = 既定値）と、説明文に書いた説明。"""
    t = p.name + (f": {_type_name(p.annotation)}" if p.annotation is not p.empty else "")
    if p.default is not p.empty:
        t += f" = {_default_text(p.default)}"
    return f"{t}　{doc}" if doc else t


def _convert(p, text, cmd):
    ann = p.annotation
    try:
        if is_window_ann(ann) and int in typing.get_args(ann) and text.isdigit():
            return int(text)                              # int | Window: 数字なら整数（タイルの番号など）、ほかは窓
        if is_window_ann(ann):
            return api_at(text)
        if ann is int:
            return int(text)
        if ann is float:
            return float(text)
        if ann is bool:
            return text.lower() in ("1", "true", "yes", "on")
    except ValueError:
        raise WinError(f"{cmd}: {p.name} は{_TYPE_LABELS.get(ann, '値')}で書いてください: {text}")
    return text


def _default(p, cmd):
    if is_window_ann(p.annotation) and isinstance(p.default, (str, _Sel)):     # 既定値が窓の指定（sel("@left") など）なら、呼ぶときに窓にする
        return api_at(p.default.spec if isinstance(p.default, _Sel) else p.default)
    return p.default


def api_command(fn=None, *, name=None):
    """関数を win の命令として登録する印（@command、または @command(name="別名")）。"""
    def register(f):
        n = name or f.__name__
        if n in builtin_commands():
            EXT_ERRORS.append((inspect.getsourcefile(f) or "?", f"「{n}」は win の組み込みの命令と同じ名前なので、使えません"))
        else:
            EXT[n] = ExtCommand(f, n)
        return f
    return register(fn) if fn is not None else register


def make_winapi():
    m = types.ModuleType("winapi", "win の拡張用の関数群。")
    for k, v in {"command": api_command, "at": api_at, "find": api_find, "windows": api_windows, "focused": api_focused,
                 "area": api_area, "run": api_run, "notify": api_notify, "sel": api_sel,
                 "layout": api_layout, "apply_set": api_apply_set, "run_command": api_run_command, "nav": api_nav,
                 "launch": api_launch, "layouts": api_layouts, "browse": api_browse, "term": api_term, "pick": api_pick, "slot_of": api_slot_of,
                 "tiles": api_tiles, "slots": api_slots, "resolve": api_resolve, "Window": Window, "WinError": WinError}.items():
        setattr(m, k, v)
    return m


WINAPI_STUB = '''\"\"\"win の拡張用の関数群（型の定義）。win が書き出すファイルなので、編集しても上書きされます。

拡張は、このディレクトリに .py を置いて書きます。@command を付けた関数が win の命令になり、
win prompt・`win 名前`・ショートカット・登録したコマンドから呼べます。
\"\"\"
from typing import Callable, TypeVar, overload

_F = TypeVar("_F", bound=Callable[..., object])


class WinError(Exception):
    \"\"\"win の失敗。raise WinError("説明") で命令を止めると、説明が入力欄や通知に出る。\"\"\"


class Window:
    \"\"\"窓 1 枚。at()・find()・windows()・focused() などで手に入る。\"\"\"
    @property
    def id(self) -> int:
        \"\"\"窓の ID（窓の指定の文字列としても使える）。\"\"\"
    @property
    def cls(self) -> str:
        \"\"\"クラス名（例 firefox、org.gnome.Ptyxis）。\"\"\"
    @property
    def title(self) -> str:
        \"\"\"題名。\"\"\"
    @property
    def rect(self) -> tuple[int, int, int, int]:
        \"\"\"位置と大きさ (x, y, 幅, 高さ)。代入すると窓が動く（最大化は解く）。例 w.rect = (0, 32, 960, 1048)\"\"\"
    @rect.setter
    def rect(self, r: tuple[int, int, int, int]) -> None: ...
    @property
    def maximized(self) -> bool:
        \"\"\"最大化しているか。\"\"\"
    @property
    def minimized(self) -> bool:
        \"\"\"最小化しているか。\"\"\"
    def move(self, x: int, y: int) -> None:
        \"\"\"左上を (x, y) に動かす（大きさはそのまま）。\"\"\"
    def resize(self, width: int, height: int) -> None:
        \"\"\"大きさを変える（左上はそのまま）。\"\"\"
    def focus(self) -> None:
        \"\"\"前面に出す（最小化していれば戻す）。\"\"\"
    def max(self) -> None:
        \"\"\"最大化する。\"\"\"
    def unmax(self) -> None:
        \"\"\"最大化を戻す。\"\"\"
    def min(self) -> None:
        \"\"\"最小化する。\"\"\"
    def unmin(self) -> None:
        \"\"\"最小化を戻す。\"\"\"
    def above(self) -> None:
        \"\"\"常に手前にする。\"\"\"
    def unabove(self) -> None:
        \"\"\"常に手前をやめる。\"\"\"
    def close(self) -> None:
        \"\"\"閉じる。\"\"\"


@overload
def command(fn: _F) -> _F: ...
@overload
def command(*, name: str | None = None) -> Callable[[_F], _F]: ...
def command(fn=None, *, name=None):
    \"\"\"関数を win の命令にする印。引数の型の注釈（Window・int・float・str・bool）で、打った語を変換する。

    Window の引数には、クラス・題名の一部、ID、@left・@prev などを打てる。既定値に sel("@left") と
    書くと、省いたときにその窓になる。bool の引数は --名前 で True。
    int | Window にすると、数字は整数（例 タイルの番号 → at(f"@slot:{n}")）、ほかは窓として受け取る。
    説明文の 1 行目が一覧に出る説明、「引数名: 説明」の行が引数の説明になる。
    \"\"\"
def sel(spec: str) -> Window:
    \"\"\"命令の引数の既定値に書く窓の指定（例 def swap(a: Window = sel("@left")): …）。呼ばれたときに窓にする。\"\"\"

def at(sel: str) -> Window:
    \"\"\"窓の指定（クラス・題名の一部、ID、@left・@prev・@largest・@slot:1・@monitor:primary など）に当たる窓 1 枚。なければ WinError。
    タイルの番号 n なら at(f"@slot:{n}")（0 は前面の窓）。\"\"\"
def find(sel: str) -> list[Window]:
    \"\"\"窓の指定に当たる窓すべて（前面に近い順）。@visible・@others・@all・@class:firefox は複数の窓に当たる。なければ空。\"\"\"
def focused() -> Window:
    \"\"\"前面の窓。\"\"\"
def windows() -> list[Window]:
    \"\"\"今のワークスペースで最小化されていない窓（前面に近い順）。\"\"\"
def slot_of(w: Window) -> int | None:
    \"\"\"いまの並び（窓の位置から逆算）で、w が何番目のタイルにあるか（1 から。@slot:n の n）。並びの中になければ None。
    （@slot:0 は前面の窓を指すが、slot_of は 0 を返さない）\"\"\"
def slots() -> list[Window]:
    \"\"\"いまの並び（窓の位置から逆算）の窓を、番号順に（slots()[0] が @slot:1）。\"\"\"
def resolve(spec: str) -> Window | None:
    \"\"\"layout の窓の列と同じ書き方を窓にする。- は None（空ける）、!コマンド は起動した窓、
    クラス名? はその窓（なければ起動）、ほかは at() と同じ。\"\"\"
def pick(title: str = "窓を選ぶ", slot: int | None = None, launch: bool = True, exclude: list[Window] = [],
         rect: tuple[int, int, int, int] | None = None) -> Window:
    \"\"\"layout -i と同じ小窓で、窓をその場で選ぶ（先頭 ! でアプリを起動して、その窓）。取り消したら WinError。
    小窓の地図にはいまの並びが出る。slot=n なら n 番目のタイルを強調する。launch=False なら起動はさせない。
    exclude の窓は一覧に出さない（2 つめを選ぶときに 1 つめを除く、など）。rect を渡すと、
    まだ窓のない場所（分けたばかりのタイルなど）を地図に足して強調する。引数を省いたら選ばせる例:
    def place(n: int, w: Window | None = None): w = w or pick(f"タイル {n} に置く窓", slot=n)\"\"\"

def layout(expr: str, *windows: Window | str, gap: int | None = None) -> None:
    \"\"\"型 expr（名前か式。例 "lr"・"v(1,2)"・"1,2:1/1"）のタイルに、windows を順に並べる。窓の指定の文字列も書ける。
    例 layout("v(1,1)", focused(), at("@prev"))\"\"\"
def tiles(expr: str, rect: tuple[int, int, int, int] | None = None) -> list[tuple[int, int, int, int]]:
    \"\"\"rect（省くと area()）を型 expr で分けた、各タイルの (x, y, 幅, 高さ)。タイルの間には設定の隙間を取る。
    例 tiles("1/1", w.rect) は w の場所を上下に分けた 2 つ\"\"\"
def layouts() -> dict[str, str]:
    \"\"\"型の一覧 {名前: 式}。\"\"\"
def area() -> tuple[int, int, int, int]:
    \"\"\"窓を置ける領域 (x, y, 幅, 高さ)。基準のモニタ（前面の窓があるモニタ）から余白を除いたもの。\"\"\"
def nav(direction: str) -> None:
    \"\"\""next"・"prev"（いまの並びの番号順）か "left"・"right"・"up"・"down" の向きの窓へフォーカスを移す。\"\"\"

def apply_set(name: str) -> None:
    \"\"\"保存したセットを適用する（win set 名前 と同じ）。\"\"\"
def run_command(name: str) -> None:
    \"\"\"登録したコマンドを実行する（win run 名前 と同じ）。拡張の命令は、Python の関数として import して呼ぶ。\"\"\"
def run(line: str) -> None:
    \"\"\"win の命令を文字列で実行する（例 run("max -w @prev")）。複数行なら上から順に。失敗したら WinError。\"\"\"

def launch(cmdline: str, timeout: float = 20) -> Window:
    \"\"\"コマンドを起動し、新しく出た窓を返す（例 launch("gnome-text-editor")）。出なければ WinError。\"\"\"
def browse(*urls: str) -> None:
    \"\"\"Firefox を新しい窓で開き、URL をタブとして並べる。\"\"\"
def term(*dirs: str) -> None:
    \"\"\"端末（Ptyxis）を、作業ディレクトリごとのタブつきで新しく開く。\"\"\"
def notify(text: str, title: str = "win") -> None:
    \"\"\"デスクトップの通知を出す。\"\"\"
'''

EXT_TEMPLATE = '''# win の拡張。@command を付けた関数が win の命令になる（win 名前・入力欄の補完・ショートカットで呼べる）。
#   使える関数の一覧:   win help api   （宣言と説明の全文は同じフォルダの winapi.pyi）
#   引数の型:           Window・int・float・str・bool（打った語をこの型に変換する。bool は --名前 で True）
#   窓の引数の既定値:   sel("@focused")・sel("@left")・sel("@prev") など
#   説明文:             1 行目が一覧に出る説明。「引数名: 説明」の行が引数の説明になる
#   nvim では:          \\wh 書き方と関数の一覧・K カーソル位置の名前の説明・:WinHelp 名前
#   保存した後、設定画面の「再読み込み」で一覧に出る。端末なら win help ですぐ確かめられる。
from winapi import Window, command, sel


@command
def {name}(w: Window = sel("@focused")):
    """（ここに 1 行の説明。入力欄の候補と win help に出ます）
    w: 対象の窓（省くと前面の窓）
    """
    ...
'''

PYRIGHT_CONFIG = '{\n  "reportMissingModuleSource": false,\n  "reportCallInDefaultInitializer": false\n}\n'


def write_ext_support():
    """拡張のディレクトリに、型の定義（winapi.pyi）と basedpyright の設定を置く（中身が違うときだけ書く）。"""
    for fname, text in (("winapi.pyi", WINAPI_STUB), ("pyrightconfig.json", PYRIGHT_CONFIG)):
        path = os.path.join(EXT_DIR, fname)
        try:
            with open(path, encoding="utf-8") as f:
                if f.read() == text:
                    continue
        except FileNotFoundError:
            pass
        except OSError:
            continue
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass


def load_extensions():
    """拡張を 1 回だけ読み込む。読めないファイルは飛ばして EXT_ERRORS に記録する（win 本体は動かし続ける）。"""
    if _EXT_STATE["loaded"]:
        return
    _EXT_STATE["loaded"] = True
    sys.modules["winapi"] = make_winapi()
    if not os.path.isdir(EXT_DIR):
        return
    write_ext_support()
    if EXT_DIR not in sys.path:
        sys.path.append(EXT_DIR)                          # 標準の部品を先に探す（同じ名前のファイルで win 本体が壊れないように）
    sys.dont_write_bytecode = True                        # 拡張のディレクトリに __pycache__ を作らない
    for path in sorted(glob.glob(os.path.join(EXT_DIR, "*.py"))):
        stem = os.path.splitext(os.path.basename(path))[0]
        try:
            mod = importlib.import_module(stem)
            _EXT_STATE["mods"].append(stem)
            if os.path.abspath(getattr(mod, "__file__", "") or "") != os.path.abspath(path):
                EXT_ERRORS.append((path, f"「{stem}」は Python の標準などの部品と同じ名前なので、読み込めません（名前を変えてください）"))
        except Exception as e:
            EXT_ERRORS.append((path, ext_error_text(e)))


def reload_extensions():
    """拡張を読み直す（開いたままの設定窓で、ファイルを書き換えた後に使う）。"""
    for stem in _EXT_STATE["mods"]:
        sys.modules.pop(stem, None)
    for n in EXT:
        SIGNATURES.pop(n, None)
    EXT.clear()
    EXT_ERRORS.clear()
    _EXT_STATE.update(loaded=False, mods=[])
    load_extensions()
    SIGNATURES.update(ext_signatures())


def ext_error_text(e):
    """例外を、拡張のどの行で起きたかが分かる短い説明にする。"""
    if isinstance(e, SyntaxError):
        return f"{os.path.basename(e.filename or '')}:{e.lineno}: 文法エラー: {e.msg}"
    frames = [f for f in traceback.extract_tb(e.__traceback__) if f.filename.startswith(EXT_DIR)]
    where = f"{os.path.basename(frames[-1].filename)}:{frames[-1].lineno}: " if frames else ""
    return f"{where}{type(e).__name__}: {e}"


def _error_line(msg):
    m = re.match(r"[^:]+:(\d+):", msg)
    return int(m.group(1)) if m else 1


def run_ext(name, tokens):
    """拡張の命令を実行する。関数の中の失敗は、どの行かを添えた WinError にする。"""
    cmd = EXT[name]
    try:
        cmd.call(tokens)
    except WinError:
        raise
    except Exception as e:
        raise WinError(f"{name}: {ext_error_text(e)}")
    return 0


@functools.cache
def builtin_commands():
    return set(build_parser()[1].choices)


def ext_spec():
    """入力欄（別プロセス）に渡す、拡張の命令の情報。"""
    load_extensions()
    info = {}
    for n, c in EXT.items():
        ps = list(c.sig.parameters.values())
        info[n] = {"summary": c.py_signature(),
                   "win": [is_window_ann(p.annotation) for p in ps if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)],
                   "rep": any(p.kind == p.VAR_POSITIONAL and is_window_ann(p.annotation) for p in ps)}
    return {"ext": info, "ext_sig": ext_signatures(), "ext_errors": [f"{os.path.basename(f)}: {m}" for f, m in EXT_ERRORS]}


def ext_signatures():
    """拡張の命令の書式（SIGNATURES と同じ形）。"""
    return {n: (c.parts(), c.py_signature() + (f"　{c.summary}" if c.summary else "")) for n, c in EXT.items()}


def api_entries():
    """winapi.pyi の宣言から {名前: (宣言の 1 行, 説明文の全文)}。Window の属性は "rect" と "Window.rect" の両方で引ける。"""
    import ast
    out = {}
    for node in ast.parse(WINAPI_STUB).body:
        if isinstance(node, ast.FunctionDef) and not any(isinstance(d, ast.Name) and d.id == "overload" for d in node.decorator_list):
            ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
            out[node.name] = (f"{node.name}({ast.unparse(node.args)}){ret}", ast.get_docstring(node) or "")
        elif isinstance(node, ast.ClassDef):
            out[node.name] = (f"class {node.name}", ast.get_docstring(node) or "")
            for m in node.body:
                if isinstance(m, ast.FunctionDef) and not any(ast.unparse(d).endswith(".setter") for d in m.decorator_list):
                    prop = any(ast.unparse(d) == "property" for d in m.decorator_list)
                    head = f"{node.name}.{m.name}: {ast.unparse(m.returns)}" if prop else \
                        f"{node.name}.{m.name}({ast.unparse(m.args)}) -> {ast.unparse(m.returns)}".replace("(self)", "()").replace("(self, ", "(")
                    entry = (head, ast.get_docstring(m) or "")
                    out[f"{node.name}.{m.name}"] = entry
                    out.setdefault(m.name, entry)
    out["command"] = ('@command　または　@command(name="別名")', out.get("command", ("", ""))[1])
    return out


def help_names(py=False):
    """win help に渡せる名前すべて（エディタの補完用）。py なら拡張を書くときの名前（winapi・拡張の命令・@ の指定）だけ。"""
    load_extensions()
    if py:
        return list(dict.fromkeys(list(api_entries()) + list(EXT) + [s for s, _ in AT_SELECTORS]))
    names = ["api", "commands", "sets", "layouts"] + list(SIGNATURES) + list(EXT) + list(api_entries())
    names += [s for s, _ in AT_SELECTORS] + list(load_commands()) + list(load_sets())
    return list(dict.fromkeys(names))


API_SECTIONS = [
    ("命令を作る", ["command", "sel", "WinError"]),
    ("窓を探す・選ぶ（Window を返す）", ["at", "find", "focused", "windows", "slots", "slot_of", "resolve", "pick"]),
    ("窓 1 枚の情報と操作（w は at() などで得た Window）", ["Window.*"]),
    ("並べる・フォーカスを移す", ["layout", "layouts", "tiles", "area", "nav"]),
    ("登録したもの・win の命令を呼ぶ", ["apply_set", "run_command", "run"]),
    ("起動・通知", ["launch", "browse", "term", "notify"]),
]

API_EXAMPLE = '''from winapi import Window, command, sel, layout, focused, find


@command
def pair(other: Window = sel("@prev")):
    """前面の窓と other を左右に並べる
    other: 右に置く窓（省くと直前の窓）
    """
    layout("lr", focused(), other)


@command
def minall():
    """前面以外の窓をすべて最小化する"""
    for w in find("@others"):
        w.min()'''


def print_api():
    """拡張を書くための一覧（winapi.pyi の宣言と説明文から作る）。"""
    api = api_entries()
    print(f"win の拡張（Python）で使えるもの。from winapi import 名前 で使う。定義の全文: {os.path.join(EXT_DIR, 'winapi.pyi')}")
    print("  ・@command を付けた関数が win の命令になる（win 名前・入力欄・ショートカット・登録したコマンドで呼べる）")
    print("  ・引数の型の注釈（Window・int・float・str・bool）で、打った語を変換する。窓の既定値は sel(\"@left\") のように書く")
    print("  ・int | Window にすると、数字は整数（タイルの番号など）、ほかは窓として受け取る")
    print("  ・省いたらその場で選ばせるには、既定値を sel(\"@pick\") にするか、Window | None にして pick() を呼ぶ")
    print("  ・説明文の 1 行目が一覧に出る説明。「引数名: 説明」の行が引数の説明")
    print("  ・ほかの拡張の関数は、ふつうに import して呼べる（例 from swap import exchange）")
    for title, names in API_SECTIONS:
        print(f"\n■ {title}")
        if names == ["Window.*"]:
            names = [k for k in api if k.startswith("Window.")]
        for n in names:
            head, doc = api[n]
            print(f"  {head.replace('Window.', 'w.') if n.startswith('Window.') else head}")
            for l in doc.splitlines()[:2]:
                if l.strip():
                    print(f"      {l.strip()}")
    print("\n■ 窓の指定（at・find・sel・layout に書く文字列）")
    print("  クラス・題名の一部（例 \"firefox\"）、ID、または:")
    for sname, d in AT_SELECTORS:
        print(f"  {sname:<10} {d}")
    print("\n■ 例")
    print("\n".join("  " + l for l in API_EXAMPLE.splitlines()))
    return 0


def cmd_help(args):
    load_extensions()
    if args.names:
        print("\n".join(help_names(args.py)))
        return 0
    if args.py and args.name:                             # 拡張を書いているとき: Python の名前を先に引く
        api = api_entries()
        if args.name in api:
            head, doc = api[args.name]
            print(head)
            print("\n".join("  " + l for l in doc.splitlines()) or "  （説明なし）")
            return 0
        if args.name in EXT:
            c = EXT[args.name]
            print(f"def {c.py_signature(code=True)}　（拡張の命令。{c.file}:{c.line}）")
            print("\n".join("  " + l for l in (c.doc or "（説明なし）").splitlines()))
            print(f"  ほかの拡張からは from {os.path.splitext(os.path.basename(c.file or 'x'))[0]} import {c.fn.__name__} で呼べる")
            return 0
    if args.py and not args.name:
        return print_api()
    if args.name:
        n = args.name
        if n == "api":
            return print_api()
        api = api_entries()
        if n in api and n not in EXT and n not in SIGNATURES:
            head, doc = api[n]
            print(f"winapi: {head}")
            print("\n".join("  " + l for l in doc.splitlines()) or "  （説明なし）")
            print(f"（一覧は win help api、定義は {os.path.join(EXT_DIR, 'winapi.pyi')}）")
            return 0
        cmds, sets, layouts = load_commands(), load_sets(), load_config()["layouts"]
        if n == "commands":
            print(f"登録したコマンド（{COMMANDS}。win run 名前 で実行、中身は win help 名前）")
            for k, c in cmds.items():
                print(f"  {k:<14} {c.get('type', 'win'):<6} {describe_command(c)}")
            if not cmds:
                print("  （まだありません）")
            return 0
        if n == "sets":
            print(f"セット（{SETS}。win set 名前 で適用、中身は win help 名前）")
            for k, c in sets.items():
                print(f"  {k:<14} {set_summary(c)}")
            if not sets:
                print("  （まだありません）")
            return 0
        if n == "layouts":
            print(f"型（{CONFIG} と組み込み。layout 名前 で使う。式を直接書いてもよい）")
            for k, e in layouts.items():
                print(f"  {k:<10} {e}")
            return 0
        if n in cmds or n in sets:
            for kind, pool, how in (("コマンド", cmds, "win run"), ("セット", sets, "win set")):
                if n in pool:
                    c = pool[n]
                    print(f"{kind}「{n}」（{how} {shlex.quote(n)}）")
                    body = c.get("run", "") if c.get("type") != "arrange" else set_summary(c)
                    print("\n".join("  " + l for l in body.splitlines()))
            return 0
        if n in EXT:
            c = EXT[n]
            print(c.usage())
            print(f"def {c.py_signature()}")
            print(c.doc or "（説明なし）")
            for part in c.parts():
                print(f"  {part[-1] if part[0] != 'pos' else part[2]}")
            if c.file:
                print(f"定義: {c.file}:{c.line}")
            return 0
        if n in SIGNATURES:
            parts, summary = SIGNATURES[n]
            print(f"win {n}　{summary}")
            for part in parts:
                print(f"  {part[1]}　{part[3] if part[0] == 'opt' else part[2]}")
            return 0
        if n.startswith("@"):
            for s, d in AT_SELECTORS:
                if n.startswith(s.rstrip(":")):
                    print(f"{s}　{d}")
            return 0
        raise WinError(f"知らない命令・名前です: {n}（一覧は win help）")
    print("組み込みの命令（詳しくは win help 名前）")
    for n, (_p, summary) in SIGNATURES.items():
        print(f"  {n:<10} {summary}")
    if EXT:
        print(f"\n拡張の命令（{EXT_DIR}。詳しくは win help 名前、拡張で使える関数は win help api）")
        for n, c in EXT.items():
            print(f"  {c.py_signature()}　{c.summary}")
    print("\nほかの一覧: win help api（拡張で使える関数）・commands（登録したコマンド）・sets（セット）・layouts（型）")
    print("\n位置・状態での窓の指定（窓を書ける所ならどこでも。【複数】は当たる窓すべてにかかる）")
    for s, d in AT_SELECTORS:
        print(f"  {s:<10} {d}")
    for path, msg in EXT_ERRORS:
        print(f"\n読み込めなかった拡張: {path}\n  {msg}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------- エディタ向けの補完・説明（win lsp）

class WinLsp:
    """win の命令（1 行に 1 つ、# はコメント）を書く文書に、補完・引数の書式・説明・誤りの印を出す LSP。標準入出力で話す。"""

    def __init__(self):
        self.docs = {}                                    # uri → 本文
        self.utf16 = True                                 # 位置の数え方（utf-32 を使えるなら Python の添字と同じ）
        self.cfg = load_config()
        self.spec = {"layouts": self.cfg["layouts"], "commands": load_commands(), "sets": load_sets(), "windows": [],
                     **ext_spec()}
        SIGNATURES.update(ext_signatures())

    # 送受信 ---------------------------------------------------------------
    def read(self):
        length = None
        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                break
            k, _, v = line.decode("ascii").partition(":")
            if k.lower() == "content-length":
                length = int(v.strip())
        return json.loads(sys.stdin.buffer.read(length).decode("utf-8")) if length else {}

    def send(self, msg):
        body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
        sys.stdout.buffer.flush()

    def serve(self):
        while True:
            msg = self.read()
            if msg is None:
                return 0
            method, mid = msg.get("method"), msg.get("id")
            try:
                result = self.handle(method, msg.get("params") or {})
            except Exception as e:                        # 1 つの要求の失敗で止まらない
                if mid is not None:
                    self.send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"}})
                continue
            if method == "exit":
                return 0
            if mid is not None and method is not None:
                self.send({"jsonrpc": "2.0", "id": mid, "result": result})

    # 位置 ------------------------------------------------------------------
    def to_index(self, text, ch):
        """LSP の文字位置 → Python の添字。"""
        if not self.utf16:
            return ch
        i = n = 0
        while i < len(text) and n < ch:
            n += 2 if ord(text[i]) > 0xFFFF else 1
            i += 1
        return i

    def to_lsp(self, text, i):
        return i if not self.utf16 else sum(2 if ord(c) > 0xFFFF else 1 for c in text[:i])

    def line_at(self, params):
        text = self.docs.get(params["textDocument"]["uri"], "")
        lines = text.split("\n")
        ln = params["position"]["line"]
        line = lines[ln] if ln < len(lines) else ""
        return ln, line, self.to_index(line, params["position"]["character"])

    @staticmethod
    def strip_win(prefix):
        return prefix[4:] if prefix.startswith("win ") else prefix

    # 要求 ------------------------------------------------------------------
    def handle(self, method, p):
        if method == "initialize":
            encs = (p.get("capabilities", {}).get("general", {}) or {}).get("positionEncodings") or []
            self.utf16 = "utf-32" not in encs
            return {"capabilities": {
                        "positionEncoding": "utf-16" if self.utf16 else "utf-32",
                        "textDocumentSync": 1,
                        "completionProvider": {"triggerCharacters": [" ", "@", "-"]},
                        "signatureHelpProvider": {"triggerCharacters": [" "], "retriggerCharacters": [" "]},
                        "hoverProvider": True},
                    "serverInfo": {"name": "win"}}
        if method in ("textDocument/didOpen", "textDocument/didChange"):
            uri = p["textDocument"]["uri"]
            self.docs[uri] = p["textDocument"]["text"] if method.endswith("didOpen") else p["contentChanges"][-1]["text"]
            self.publish(uri)
            return None
        if method == "textDocument/didClose":
            self.docs.pop(p["textDocument"]["uri"], None)
            return None
        if method == "textDocument/completion":
            return self.completion(p)
        if method == "textDocument/signatureHelp":
            return self.signature(p)
        if method == "textDocument/hover":
            return self.hover(p)
        if method == "shutdown":
            return None
        return None

    def refresh_windows(self):
        try:
            wc = WindowCalls()
            ws = normal_windows(wc)
            self.spec["windows"] = [{"sel": selector_for(w, ws), "cls": w.get("wm_class") or "",
                                     "title": (w.get("title") or "")[:60]} for w in reversed(ws)]
        except WinError:
            self.spec["windows"] = []

    def completion(self, p):
        ln, line, i = self.line_at(p)
        prefix = line[:i]
        if prefix.lstrip().startswith("#"):
            return []
        body = self.strip_win(prefix.lstrip())
        self.refresh_windows()
        cands = suggest(body, self.spec)
        start = i - len(prefix.split(" ")[-1])
        rng = {"start": {"line": ln, "character": self.to_lsp(line, start)},
               "end": {"line": ln, "character": self.to_lsp(line, i)}}
        first = len(body.split(" ")) == 1
        items = []
        for k, (ins, desc) in enumerate(cands):
            word = ins.rstrip(" ")
            try:
                label = shlex.split(word)[0] if word.startswith(("'", '"')) else word      # 表示は引用符なし、挿入は引用符つき
            except (ValueError, IndexError):
                label = word
            items.append({"label": label, "detail": desc, "kind": 3 if first else 12, "sortText": f"{k:04d}",
                          "filterText": label, "textEdit": {"range": rng, "newText": word}})
        return {"isIncomplete": True, "items": items}

    def signature(self, p):
        _ln, line, i = self.line_at(p)
        sp = signature_parts(self.strip_win(line[:i].lstrip()))
        if sp is None:
            return None
        label = f"win {sp['cmd']} " + " ".join(t for t, _l, _d in sp["items"])
        params = [{"label": t, "documentation": d} for t, _l, d in sp["items"]]
        active = next((k for k, (_t, l, _d) in enumerate(sp["items"]) if l == sp["active"]), None)
        sig = {"label": label, "documentation": sp["summary"], "parameters": params}
        if active is not None:
            sig["activeParameter"] = active
        return {"signatures": [sig], "activeSignature": 0, **({"activeParameter": active} if active is not None else {})}

    def hover(self, p):
        _ln, line, i = self.line_at(p)
        if line.lstrip().startswith("#"):
            return None
        a = line.rfind(" ", 0, i) + 1
        b = line.find(" ", i)
        word = line[a:] if b < 0 else line[a:b]
        tokens = self.strip_win(line.lstrip()).split(" ")
        if not word:
            return None
        text = None
        if word == tokens[0] and word in EXT:
            c = EXT[word]
            text = f"```\n{c.usage()}\n```\n{c.doc or '（説明なし）'}\n\n" + "\n".join(
                f"- `{part[1]}` {part[-1] if part[0] != 'pos' else part[2]}" for part in c.parts()) + \
                (f"\n\n定義: `{c.file}:{c.line}`" if c.file else "")
        elif word == tokens[0] and word in SIGNATURES:
            parts, summary = SIGNATURES[word]
            sp = signature_parts(f"{word} ") or {"items": []}
            text = f"```\nwin {word} {' '.join(t for t, _l, _d in sp['items'])}\n```\n{summary}\n\n" + \
                   "\n".join(f"- `{t}` {d}" for t, _l, d in sp["items"])
        elif word.startswith("@"):
            text = "\n".join(f"`{s}` {d}" for s, d in AT_SELECTORS if word.lower().startswith(s.rstrip(":")) or s.startswith(word.lower()))
        elif word in self.spec["layouts"]:
            text = f"型 `{word}` = `{self.spec['layouts'][word]}`"
        else:
            self.refresh_windows()
            hits = [w for w in self.spec["windows"] if word.lower() in (w["cls"] + " " + w["title"]).lower()]
            if hits:
                text = "当たる窓:\n" + "\n".join(f"- `{w['cls']}` {w['title']}" for w in hits[:8])
        return {"contents": {"kind": "markdown", "value": text}} if text else None

    def publish(self, uri):
        diags = []
        known = {c for c, _ in SUBCOMMANDS} | set(EXT) | {"prompt"}
        for ln, line in enumerate(self.docs.get(uri, "").split("\n")):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            try:
                argv = shlex.split(s)
            except ValueError as e:
                msg = f"引用符が閉じていません: {e}"
            else:
                argv = argv[1:] if argv and argv[0] == "win" else argv
                msg = f"知らない命令です: {argv[0]}（一覧は win help）" if argv and argv[0] not in known else None
            if msg:
                diags.append({"range": {"start": {"line": ln, "character": 0},
                                        "end": {"line": ln, "character": self.to_lsp(line, len(line))}},
                              "severity": 1, "source": "win", "message": msg})
        self.send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                   "params": {"uri": uri, "diagnostics": diags}})


def cmd_lsp(args):
    return WinLsp().serve()


def main(argv=None):
    if len(sys.argv) >= 2 and sys.argv[1] == "_pick":
        run_pick()
        return 0
    if len(sys.argv) >= 2 and sys.argv[1] == "_tilepick":
        run_tilepick()
        return 0
    if len(sys.argv) >= 2 and sys.argv[1] == "_setpick":
        run_setpick()
        return 0
    if len(sys.argv) >= 2 and sys.argv[1] == "_prompt":
        run_prompt()
        return 0
    if len(sys.argv) >= 6 and sys.argv[1] == "_nvprompt":
        run_nvprompt(*sys.argv[2:6])
        return 0
    if len(sys.argv) >= 4 and sys.argv[1] == "_tile":
        run_tile(int(sys.argv[2]), int(sys.argv[3]))
        return 0
    ap, sub = build_parser()
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and not argv[0].startswith("-") and argv[0] not in sub.choices:
        load_extensions()                                 # 組み込みにない名前は、拡張の命令として探す
        if argv[0] in EXT:
            try:
                return run_ext(argv[0], argv[1:])
            except WinError as e:
                return report_error(e)
    args = ap.parse_args(argv)
    try:
        if args.cmd in ("layout", "here", "pick", "prompt", "save", "run", "set"):
            resolve_monitor(getattr(args, "monitor", None))      # 基準のモニタを、最初に 1 回決める
        return args.fn(args)
    except WinError as e:
        return report_error(e)


def report_error(e):
    print(f"win: {e}", file=sys.stderr)
    if sys.stderr is sys.__stderr__ and not sys.stderr.isatty():     # ショートカットなど、端末のない呼び出しでは通知で知らせる
        try:
            subprocess.run(["notify-send", "-a", "win", "-i", "dialog-warning-symbolic", "win", str(e)], timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass
    return 1


def build_parser():
    """(引数の解析器, 命令の表)。"""
    ap = argparse.ArgumentParser(prog="win", description="GNOME の窓をコマンドで操作する",
                                 epilog="窓の指定: クラス・題名の一部（大文字小文字は区別しない）か、5 桁以上の ID、"
                                        "または @left・@prev などの位置・状態（一覧は win help）。"
                                        "省略したときの対象は前面の窓（ターミナルから実行すると、そのターミナル）。"
                                        f"拡張の命令（{EXT_DIR} の @command）も win 名前 で呼べる。")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="窓の一覧")
    p.add_argument("-a", "--all", action="store_true", help="通常の窓以外も表示")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("layouts", help="登録済みの型の一覧")
    p.set_defaults(fn=cmd_layouts)

    p = sub.add_parser("focus", help="窓を前面に出す")
    p.add_argument("selector")
    p.set_defaults(fn=cmd_focus)

    p = sub.add_parser("nav", help="フォーカスを移す（next・prev はいまの並びの番号順、left など は上下左右）")
    p.add_argument("direction", choices=["next", "prev", "left", "right", "up", "down"])
    p.set_defaults(fn=cmd_nav)

    p = sub.add_parser("prompt", help="コマンドを 1 行打って窓を操作する小窓（Tab 補完つき）")
    p.add_argument("-m", "--monitor", metavar="画面", help=MONITOR_HELP)
    p.add_argument("--nvim", action="store_true", help="1 行の入力欄でなく、nvim の入力欄を使う（試作）")
    p.add_argument("--gtk", action="store_true", help=argparse.SUPPRESS)      # 既定と同じ（一時期 nvim が既定だったときの指定）
    p.set_defaults(fn=cmd_prompt)

    p = sub.add_parser("config", help="設定の窓（ショートカット・コマンド・型）を開く")
    p.add_argument("page", nargs="?", default="shortcuts", choices=["shortcuts", "commands", "sets", "layouts"],
                   help="開くページ")
    p.set_defaults(fn=cmd_config)

    p = sub.add_parser("run", help="登録したコマンド・保存した並びを実行する（名前なしで一覧）")
    p.add_argument("name", nargs="?")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("set", help="保存した窓の並び（セット）を適用する（名前なしで、絞り込みの小窓から選ぶ）")
    p.add_argument("name", nargs="?", help="セットの名前。省くと、一覧の小窓が開く")
    p.add_argument("-m", "--monitor", metavar="画面", help=MONITOR_HELP)
    p.set_defaults(fn=cmd_set)

    p = sub.add_parser("save", help="いま表に出ている窓の並びを、型と窓の列の命令（セット）として名前をつけて保存する")
    p.add_argument("name")
    p.add_argument("-f", "--force", action="store_true", help="同じ名前があれば上書きする")
    p.add_argument("-s", "--state", action="append", choices=["firefox", "terminal", "all"],
                   help="窓の状態も保存する（Firefox のタブの URL、端末の作業ディレクトリ）。選んだときだけ。URL は平文で保存される")
    p.add_argument("-m", "--monitor", metavar="画面", help=MONITOR_HELP)
    p.set_defaults(fn=cmd_save)

    p = sub.add_parser("browse", help="Firefox を新しい窓で開き、URL をタブとして並べる")
    p.add_argument("urls", nargs="+", metavar="URL", help="開く URL（最初の 1 つで窓を開き、残りはタブ）")
    p.set_defaults(fn=cmd_browse)

    p = sub.add_parser("term", help="端末（Ptyxis）を、作業ディレクトリごとのタブつきで新しく開く")
    p.add_argument("dirs", nargs="*", metavar="作業ディレクトリ", help="タブごとの作業ディレクトリ。省くと今のディレクトリ")
    p.set_defaults(fn=cmd_term)

    p = sub.add_parser("here", help="選んだ窓（先頭 ! でアプリ）を、いまの窓と同じ位置・大きさにして前面に出す")
    p.add_argument("-m", "--monitor", metavar="画面", help=MONITOR_HELP)
    p.add_argument("selector", nargs="?", help="窓の指定（クラス・題名の一部）か !コマンド。省くと小窓で選ぶ")
    p.set_defaults(fn=cmd_here)

    p = sub.add_parser("pick", help="窓の一覧を小さく出して選び、前面に出す（j/k・矢印・Enter）")
    p.add_argument("--id", action="store_true", help="前面に出さず、選んだ窓の ID だけを表示")
    p.add_argument("-m", "--monitor", metavar="画面", help=MONITOR_HELP)
    p.set_defaults(fn=cmd_pick)

    p = sub.add_parser("layout", help="窓を分割配置する")
    p.add_argument("layout", nargs="?", help="型の名前（win layouts）か式（例: 'v(1,h(1,1))'。略記は , ＝左右・/＝上下・( )・重み:式、例 1,2:1/1/1,1）。省くと小窓で型を選ぶ")
    p.add_argument("windows", nargs="*", metavar="窓", help="タイル順の窓。- は空け、!コマンド は新しく起動")
    p.add_argument("-i", "--interactive", action="store_true", help="タイルごとに窓を絞り込んで選ぶ・起動する（! でアプリ、Tab で残りを自動）")
    p.add_argument("-n", "--dry-run", action="store_true", help="動かさず、割り当てだけ表示")
    p.add_argument("--gap", type=int, help="タイル間の隙間（px）")
    p.add_argument("-t", "--text", action="store_true", help="対話モードを端末の文字入力で行う（既定は絞り込みの小窓）")
    p.add_argument("--preview", action="store_true", help="対話モードで、各タイルの位置に番号つきの目印の窓を出す")
    p.add_argument("--pick", action="store_true", help="対話モードで、タイルごとに窓の一覧を自動で出す")
    p.add_argument("--no-preview", action="store_true", help="（--text 用）画面上の番号表示を出さない")
    p.add_argument("-m", "--monitor", metavar="画面", help=MONITOR_HELP)
    p.set_defaults(fn=cmd_layout)

    p = sub.add_parser("move", help="窓を移動する")
    p.add_argument("x", type=int); p.add_argument("y", type=int)
    p.add_argument("-w", "--window"); p.set_defaults(fn=cmd_move)

    p = sub.add_parser("size", help="窓の大きさを変える")
    p.add_argument("w", type=int); p.add_argument("h", type=int)
    p.add_argument("-w", "--window"); p.set_defaults(fn=cmd_size)

    p = sub.add_parser("state", help="最大化・最小化・常に手前")
    p.add_argument("action", choices=["max", "unmax", "min", "unmin", "above", "unabove"])
    p.add_argument("-w", "--window"); p.set_defaults(fn=cmd_state)

    for name, action, text in (("max", "max", "窓を最大化する"), ("unmax", "unmax", "最大化を戻す"),
                               ("min", "min", "窓を最小化する"), ("unmin", "unmin", "最小化を戻す")):
        p = sub.add_parser(name, help=text)           # state の短縮形
        p.add_argument("-w", "--window")
        p.set_defaults(fn=cmd_state, action=action)

    p = sub.add_parser("close", help="窓を閉じる")
    p.add_argument("-w", "--window"); p.set_defaults(fn=cmd_close)

    p = sub.add_parser("lsp", help="エディタ（nvim など）向けに、win の命令の補完・書式・説明を出す（LSP。標準入出力で話す）")
    p.set_defaults(fn=cmd_lsp)

    p = sub.add_parser("help", help="命令の書式と説明（拡張の命令、@ の指定も）。名前なしで一覧")
    p.add_argument("name", nargs="?", help="命令・拡張の関数・登録したコマンドやセットの名前か、@ の指定。api・commands・sets・layouts で一覧")
    p.add_argument("--names", action="store_true", help="渡せる名前の一覧を出す（エディタの補完用）")
    p.add_argument("--py", action="store_true", help="拡張（Python）を書くときのヘルプ（名前は winapi の関数を先に引く。名前なしで win help api）")
    p.set_defaults(fn=cmd_help)
    return ap, sub


if __name__ == "__main__":
    sys.exit(main())

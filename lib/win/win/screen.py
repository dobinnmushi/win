"""モニタ（Screen）と作業領域、設定の読み込み。"""

import os
import tomllib
from gi.repository import GLib
from gi.repository import Gio

from .common import BUILTIN_LAYOUTS, CONFIG, DEFAULT_INSETS, WinError


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


class Screen:
    """基準にするモニタ（論理領域と、主モニタか）。作り直さない限り変わらない。作業領域はここから求める。"""
    __slots__ = ("rect", "primary", "name")

    def __init__(self, rect, primary, name=None):
        self.rect, self.primary, self.name = tuple(rect), bool(primary), name

    def work_area(self, cfg):
        """タイルを置ける領域（上下左右の余白を除く）。上部バーは主モニタにしか出ないので、その高さの余白は主モニタだけに適用する。"""
        x, y, w, h = self.rect
        i = dict(cfg["insets"])
        if not self.primary:
            i["top"] = 0
        return x + i["left"], y + i["top"], w - i["left"] - i["right"], h - i["top"] - i["bottom"]


def find_screen(choice=None):
    """基準にするモニタ（Screen）を探す。状態は変えない。choice: None・"current"＝いまの窓があるモニタ、"primary"＝主モニタ、
    接続名（例 eDP-1）。"""
    from .dbus import WindowCalls, focused        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
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
    return Screen(chosen[1], chosen[0][4], chosen[0][5][0][0])


_DEFAULT_SCREEN = [None]     # この実行の既定の基準モニタ（コマンド行の -m。最初に 1 回だけ決める）。小窓の中での切り替えは、これを書き換えず Screen を渡す


def use_screen(screen):
    """この実行の既定の基準モニタを、screen にする（コマンド行の -m と同じ働き。セットを別のモニタで実行するときなど）。"""
    _DEFAULT_SCREEN[0] = screen
    return screen


def default_screen():
    """この実行の既定の基準モニタ。まだ決めていなければ、いまの窓があるモニタに決める。"""
    return _DEFAULT_SCREEN[0] or use_screen(find_screen())


def resolve_monitor(choice=None):
    """既定の基準モニタを決めて保持し、その論理領域を返す。choice を省いたときは、すでに決めていればそれを使う
    （小窓が開いてフォーカスが動いても変えない）。"""
    if choice is None and _DEFAULT_SCREEN[0] is not None:
        return _DEFAULT_SCREEN[0].rect
    return use_screen(find_screen(choice)).rect


def monitor_rect():
    """既定の基準のモニタの論理領域 (x, y, w, h)。拡大率と回転を反映する。"""
    return default_screen().rect


def load_config():
    cfg = {"layouts": dict(BUILTIN_LAYOUTS), "insets": dict(DEFAULT_INSETS), "gap": 0}
    if os.path.exists(CONFIG):
        with open(CONFIG, "rb") as f:
            user = tomllib.load(f)
        cfg["layouts"].update(user.get("layouts", {}))
        cfg["insets"].update(user.get("workarea", {}))
        cfg["gap"] = user.get("gap", 0)
    return cfg


def work_area(cfg, screen=None):
    """screen（省くと既定の基準モニタ）の作業領域 (x, y, w, h)。"""
    return (screen or default_screen()).work_area(cfg)

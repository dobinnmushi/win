"""list・focus・move・size・state・close など。"""

from .common import CONFIG, WinError
from .screen import load_config
from .layouts import LayoutParser, leaf_rects
from .dbus import WindowCalls, find_windows, is_multi, normal_windows
from .placement import describe
from .desktop import desktops, switch_desktop, switch_relative


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


def cmd_desktop(args):
    """デスクトップ（ワークスペース）の表示・切り替え。N（1 から）・next・prev・list。切り替えには拡張 win-helper@local が要る。"""
    t = args.target
    if t == "list":                                        # 窓の一覧から数えるので、拡張がなくても動く
        wc = WindowCalls()
        by = {}
        for w in normal_windows(wc):
            by.setdefault(w.get("workspace", 0) + 1, []).append(w)
        here = next((w.get("workspace", 0) + 1 for w in normal_windows(wc) if w.get("in_current_workspace")), None)
        for n in sorted(by):
            names = ", ".join((w.get("wm_class") or "?") for w in by[n])
            print(f"デスクトップ {n}{'（いま）' if n == here else ''}: {len(by[n])} 枚  {names}")
        return 0
    if t in ("next", "prev"):
        switch_relative(1 if t == "next" else -1)
    elif t:
        try:
            n = int(t)
        except ValueError:
            raise WinError(f"デスクトップの番号（1 から）か next・prev・list を指定してください: {t}")
        switch_desktop(n)
    cur, count = desktops()
    print(f"デスクトップ {cur}/{count}")
    return 0

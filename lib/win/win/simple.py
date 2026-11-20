"""list・focus・move・size・state・close など。"""

import time

from .common import CONFIG, WinError
from .screen import load_config
from .layouts import LayoutParser, leaf_rects
from .dbus import WindowCalls, find_windows, is_multi, normal_windows, targets
from .screen import Screen, display_state, logical_rect
from .placement import place_settled
from .undo import begin, entries, undo_last
from .placement import describe, launch, parse_window_spec
from .store import launch_for_class
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
    base, optional, fallback = parse_window_spec(args.selector)       # クラス名?＝アプリへ飛ぶ（窓がなければ起動、あれば巡回）
    found = find_windows(wc, base, normal_windows(wc)[::-1])
    if optional and not args.selector.startswith("@"):
        if not found:
            cmdline = fallback or launch_for_class(base)
            if not cmdline:
                raise WinError(f"窓が見つからず、起動コマンドも分かりません: {base}")
            found = [launch(wc, cmdline)]
        else:
            front = next((w for w in normal_windows(wc) if w.get("focus")), None)
            ordered = sorted(found, key=lambda w: w["id"])             # すでにそのアプリにいるなら、次の窓へ（ID の昇順で一巡）
            if front is not None and front["id"] in {w["id"] for w in ordered} and len(ordered) > 1:
                found = [ordered[([w["id"] for w in ordered].index(front["id"]) + 1) % len(ordered)]]
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


def cmd_stats(args):
    """使用の集計。win stats [日数|on|off|reset|path]。"""
    import os
    from .usage import OFF_FILE, USAGE_FILE, read_usage, summarize
    w = args.what
    if w == "off":
        os.makedirs(os.path.dirname(OFF_FILE), exist_ok=True)
        open(OFF_FILE, "w").close()
        print("記録を止めました（再開は win stats on）")
        return 0
    if w == "on":
        if os.path.exists(OFF_FILE):
            os.remove(OFF_FILE)
        print("記録を再開しました")
        return 0
    if w == "reset":
        if os.path.exists(USAGE_FILE):
            os.remove(USAGE_FILE)
        print("記録を消しました")
        return 0
    if w == "path":
        print(USAGE_FILE)
        return 0
    try:
        days = int(w)
    except ValueError:
        raise WinError(f"日数（整数）か on・off・reset・path を指定してください: {w}")
    rows = read_usage(days)
    state = "止めています" if os.path.exists(OFF_FILE) else "記録中"
    if not rows:
        print(f"直近 {days} 日の記録はありません（{state}。記録の場所: {USAGE_FILE}）")
        return 0
    summary = summarize(rows)
    print(f"直近 {days} 日: {len(rows)} 回（{state}）")
    print(f"  {'コマンド':<14}{'合計':>6}{'キー':>6}{'手入力':>7}{'日数':>6}")
    for c, s in summary:
        print(f"  {c:<14}{s['total']:>6}{s['key']:>6}{s['typed']:>7}{s['days']:>6}")
    return 0


def cmd_send(args):
    """前面の窓（-w で指定した窓）を、別のモニタへ送る。モニタの作業領域に対する位置と大きさの割合を保つ（最大化の窓は、最大化のまま）。"""
    wc = WindowCalls()
    cfg = load_config()
    monitors, logical = display_state()
    screens = [Screen(r, lm[4], lm[5][0][0]) for lm, r in sorted(((lm, logical_rect(lm, monitors)) for lm in logical),
                                                                  key=lambda t: (t[1][0], t[1][1]))]      # 左から右へ
    if len(screens) < 2:
        raise WinError("モニタが 1 枚だけです")
    wins = targets(wc, args.window)
    ent = begin(wc, "send")
    ent.add(wc, wins)                                                  # 動かす前の状態。実際に動かしたときだけ記録する
    moved = False
    for w in wins:
        d = wc.details(w["id"])
        x, y, rw, rh = d["x"], d["y"], d["width"], d["height"]
        cx, cy = x + rw / 2, y + rh / 2
        cur = next((k for k, s in enumerate(screens) if s.rect[0] <= cx < s.rect[0] + s.rect[2] and s.rect[1] <= cy < s.rect[1] + s.rect[3]),
                   min(range(len(screens)), key=lambda k: abs(screens[k].rect[0] + screens[k].rect[2] / 2 - cx)))
        t = args.target
        if t == "next":
            dst = (cur + 1) % len(screens)
        elif t == "prev":
            dst = (cur - 1) % len(screens)
        elif t == "primary":
            dst = next((k for k, s in enumerate(screens) if s.primary), 0)
        else:
            dst = next((k for k, s in enumerate(screens) if s.name == t), None)
            if dst is None:
                raise WinError(f"モニタが見つかりません: {t}（使えるのは next・prev・primary・{'・'.join(s.name for s in screens)}）")
        if dst == cur:
            print(f"すでに {screens[dst].name} にあります")
            continue
        moved = True
        sx, sy, sw, sh = screens[cur].work_area(cfg)
        tx, ty, tw, th = screens[dst].work_area(cfg)
        maximized = bool(d.get("maximized_horizontally") and d.get("maximized_vertically"))
        if maximized:
            wc.simple("Unmaximize", w["id"])
            rect = (tx, ty, tw, th)
        else:
            rel = lambda v, o, size: min(max((v - o) / size, 0.0), 1.0)
            fw, fh = min(rw / sw, 1.0), min(rh / sh, 1.0)
            rx, ry = min(rel(x, sx, sw), 1.0 - fw), min(rel(y, sy, sh), 1.0 - fh)
            rect = (round(tx + rx * tw), round(ty + ry * th), round(fw * tw), round(fh * th))
        place_settled(wc, w["id"], rect)
        if maximized:
            wc.simple("Maximize", w["id"])
        wc.simple("Activate", w["id"])
        print(f"{describe(w)} → {screens[dst].name}")
    if moved:
        ent.commit()
    return 0


def cmd_undo(args):
    """直前の操作（layout・place・here・group・set・send）を元に戻す。win undo list で記録の一覧。"""
    wc = WindowCalls()
    if args.what == "list":
        rows = entries()
        if not rows:
            print("元に戻せる操作はありません")
        for k, e in enumerate(rows):
            print(f"{'→ ' if k == 0 else '  '}{time.strftime('%H:%M:%S', time.localtime(e['t']))}  {e['what']}（{len(e['windows'])} 枚）")
        return 0
    what, n, gone = undo_last(wc)
    print(f"元に戻しました: {what}（{n} 枚" + (f"、閉じていた {gone} 枚は戻せません" if gone else "") + "）")
    return 0

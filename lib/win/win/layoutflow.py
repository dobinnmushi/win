"""win layout の対話: 型を選び、Enter ならタイルごとに窓を選び、Tab なら前面の窓から自動で並べる（Dialog の上）。"""

import re
import shlex
import time

from .common import WinError
from .screen import default_screen, find_screen, load_config
from .layouts import compute_rects, is_shorthand_layout, resolve_layout
from .dbus import focused, normal_windows, selector_for, usable_windows
from .placement import cmd_layout, place_settled, raise_group
from .textui import start_placeholders, stop_placeholders
from .sets import monitors_for_preview, next_monitor
from .prompt import save_history
from .tilepick import fuzzy
from .dialog import Dialog, Item, Map, window_items
from .undo import begin

TILE_PLACEHOLDER = "文字で絞り込み　先頭に ! でアプリを探して新規起動"
TILE_HINT = "↑↓ 選択 ・ Enter 決定 ・ Tab 決定して残りを自動 ・ Ctrl+S 空ける ・ Ctrl+B 戻る ・ Esc 終了"
LAYOUT_PLACEHOLDER = "型の名前で絞り込み（式も打てます: 1,2,2・1/1・v(1,h(1,1)) など）"


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
    mons, mon = monitors_for_preview(cfg)
    many = len(mons) > 1

    def title():
        return "型を選ぶ" + (f"（並べる先: {mons[mon]['name']}）" if many else "")

    def rows(text):
        cands = layout_candidates(text, items)
        return cands, [Item(c["title"], c["sub"], value=c) for c in cands]

    def preview(cand):
        return Map(cand["rects"], None, -1, None, mon) if cand and cand["rects"] else None

    chosen = None                                     # (型の名前, 式, rects, Tab で残りを自動か)
    with Dialog(title(), window_title="窓を並べる", watch=True, filter=False, highlight=True, chip="型",
                keys=("Left", "Right") if many else (), placeholder=LAYOUT_PLACEHOLDER,
                hint="↑↓ 選択（ミニ地図が変わる）" + (" ・ ←→ 並べる先のモニタ" if many else "")
                     + " ・ Enter 決定してタイルごとに選ぶ ・ Tab 決定して前面の窓で自動配置 ・ Esc 閉じる") as d:
        cands, its = rows("")
        d.rows(its)
        d.map(preview(cands[0] if cands else None))
        shown = cands[0] if cands else None
        for ev in d.events():
            if ev.kind == "edit":
                cands, its = rows(ev.text)
                d.rows(its)
                shown = cands[0] if cands else None
                d.map(preview(shown))
            elif ev.kind == "highlight":
                shown = ev.item.value if ev.item else None
                d.map(preview(shown))
            elif ev.kind == "key":
                nxt = next_monitor(mons, mon, 1 if ev.key == "Right" else -1)
                if nxt is not None:
                    mon = nxt
                    d.options(title=title())
                    d.map(preview(shown))
            elif ev.kind == "select" and ev.item is not None:
                name = ev.item.value["act"]["name"]
                try:
                    expr = resolve_layout(cfg, name)
                    if many:                               # 小窓で選んだモニタを基準にして並べる（全体の既定は変えず、args で持ち回る）
                        args.monitor = mons[mon]["name"]
                        area = find_screen(args.monitor).work_area(cfg)
                    rects = compute_rects(expr, area, gap)
                except WinError as e:
                    d.notice(str(e))
                    continue
                args.layout = name
                chosen = (name, expr, rects, ev.via == "tab")
                if not chosen[3]:
                    state = tile_loop(wc, args, d, rects, area, mon)
                break
            elif ev.kind == "cancel":
                return 0
    if chosen is None:
        return 0
    if chosen[3]:                                      # Tab: 前面の窓から自動で並べる
        time.sleep(0.3)                                # 小窓が閉じて、元の窓にフォーカスが戻るのを待つ
        args.interactive, args.windows = False, []
        return cmd_layout(args)
    return finish_layout(wc, args, *state)


def gui_interactive(wc, args, expr, rects, area):
    """型は決まっているとき（win layout 型 -i）: タイルごとに窓を選ぶ小窓。"""
    screen = find_screen(args.monitor) if getattr(args, "monitor", None) else default_screen()
    mon = monitors_for_preview(load_config(), screen)[1]
    with Dialog("", window_title="窓を並べる", screen=screen) as d:
        state = tile_loop(wc, args, d, rects, area, mon)
    return finish_layout(wc, args, *state)


def tile_loop(wc, args, d, rects, area, mon):
    """開いている Dialog で、タイルごとに窓を選ばせて置く。(assigned, auto_from, procs, me, n) を返す（後始末は finish_layout）。"""
    n = len(rects)
    ax, ay, aw, ah = area
    norm = [((x - ax) / aw, (y - ay) / ah, w / aw, h / ah) for x, y, w, h in rects]
    try:
        me = focused(wc)["id"]
    except WinError:
        me = None
    assigned = [None] * n                    # (窓, 再現用の指定) か None
    procs = start_placeholders(wc, rects) if args.preview else []
    d.options(window_title="窓を並べる", watch=False, filter=True, highlight=False, launch=True, chip="開いている窓",
              placeholder=TILE_PLACEHOLDER, hint=TILE_HINT)
    d.keys("Ctrl+s", "Ctrl+b")

    ent = begin(wc, f"layout {args.layout}")                        # 置く窓の、置く前の状態（win undo で戻す）

    def place_checked(w, i):
        ent.add(wc, [w])
        got = place_settled(wc, w["id"], rects[i])
        return (f"タイル {i + 1} の窓は希望の大きさにならず {got[2]}x{got[3]} です（最小サイズなど）" if got else "")

    def show(i, notice=""):
        taken = [a[0]["id"] for a in assigned if a]
        d.options(title=f"タイル {i + 1} / {n}　{args.layout}")
        d.text("")                                   # 入力欄は、タイルごとに空にする
        d.rows(window_items(wc, taken))
        d.map(Map(norm, [(a[0].get("wm_class") or "")[:14] if a else "" for a in assigned], i, None, mon))
        d.notice(notice)

    i, auto_from = 0, None
    show(i)
    for ev in d.events():
        chosen, notice = None, ""
        if ev.kind == "cancel":
            break
        if ev.kind == "select" and ev.item is not None:
            w = next((x for x in normal_windows(wc) if x["id"] == ev.item.value["id"]), None)
            if w is None:
                show(i, "その窓はもう閉じられました")
                continue
            chosen = (w, selector_for(w, normal_windows(wc)))
        elif ev.kind == "launched":
            chosen = (ev.window, "!" + ev.text)
        elif ev.kind == "key" and ev.key == "Ctrl+s":      # 空けておく
            i += 1
        elif ev.kind == "key" and ev.key == "Ctrl+b":      # 前のタイルへ戻る
            i = max(0, i - 1)
            assigned[i] = None
        if chosen:
            notice = place_checked(chosen[0], i)
            assigned[i] = chosen
            i += 1
        if (ev.kind in ("select", "launched")) and ev.via == "tab":      # 決めて、残りは前面の窓から自動
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
        show(i, notice)
    ent.commit()
    return assigned, auto_from, procs, me, n


def finish_layout(wc, args, assigned, auto_from, procs, me, n):
    """小窓を閉じたあとの仕上げ: 目印の窓を片づけ、置いた窓を前面に出し、同じ配置を再現するコマンドを出す。"""
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
        if getattr(args, "monitor", None):
            recipe += " -m " + shlex.quote(args.monitor)
        print("同じ配置を再現するコマンド:\n  win " + recipe)
        save_history(recipe)
    return 0

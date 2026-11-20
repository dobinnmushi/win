"""置き先に窓を重ねる（win place・win here）。"""

import sys
import time

from .common import WinError
from .screen import default_screen, find_screen, load_config, work_area
from .dbus import WindowCalls, find_windows, focused, normal_windows, targets
from .store import icon_for_class, launch_for_class
from .pickers import pick_rows
from .placement import launch, parse_window_spec, place_settled
from .nav import visible_windows
from .sets import monitors_for_preview, next_monitor
from .appstate import current_tiles, cycle_stack, find_stack, tile_order, tile_stacks
from . import groups as grp
from .undo import begin
from .dialog import Dialog, Item, Map, choose
from .configwin import run_config


HERE_HINT = "↑↓ 選択 ・ ←→ 置き先を動かす（空きスペースにも） ・ Enter 決定（置き先と同じ位置・大きさで前面へ） ・ 先頭 ! でアプリ ・ Esc 閉じる"


def window_row_title(w, d):
    """窓の候補の表示名（最小化・別のワークスペースの印つき）。"""
    t = (w.get("title") or "")[:90]
    if d.get("minimized"):
        t += "  （最小化）"
    if not w.get("in_current_workspace"):
        t += f"  [WS {w.get('workspace', 0) + 1}]"
    return t


def bring_here(wc, w, rect, maximized, workspace, activate=True):
    """w を rect と同じ位置・大きさ（最大化なら最大化）にして、前面に出す。通知する文を返す（無ければ空）。
    activate=False なら前面には出さない（複数の窓を並行して置いて、前面化は順序を決めて後でするとき）。"""
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
    if activate:
        wc.simple("Activate", w["id"])
    return notice


FREE_MIN_RATIO = 0.05      # 空きスペースとして数える最小の広さ（作業領域に対する面積の割合）。細すぎるものは辺の長さでも除く


FREE_MAX = 6               # 置き先の候補にする空きの数（広い順）


def free_rects(wc, exclude=(), screen=None):
    """基準モニタの作業領域のうち、窓に覆われていない空きスペース（極大の長方形）を、広い順に [(x, y, 幅, 高さ)]。
    最小化されていない窓の枠で作業領域を区切り、その区切りの上で、窓のない長方形のうち、どの向きにも広げられないものを探す。"""
    screen = screen or default_screen()
    ax, ay, aw, ah = screen.work_area(load_config())
    mx, my, mw, mh = screen.rect
    obst = []
    for w, (x, y, rw, rh) in visible_windows(wc):
        if w["id"] in exclude or not (mx <= x + rw / 2 < mx + mw and my <= y + rh / 2 < my + mh):
            continue
        x0, y0, x1, y1 = max(ax, x), max(ay, y), min(ax + aw, x + rw), min(ay + ah, y + rh)
        if x1 > x0 and y1 > y0:
            obst.append((x0, y0, x1, y1))
    xs = sorted({ax, ax + aw, *(o[0] for o in obst), *(o[2] for o in obst)})
    ys = sorted({ay, ay + ah, *(o[1] for o in obst), *(o[3] for o in obst)})
    nx, ny = len(xs) - 1, len(ys) - 1
    occ = [[any(o[0] <= xs[i] and xs[i + 1] <= o[2] and o[1] <= ys[j] and ys[j + 1] <= o[3] for o in obst)
            for i in range(nx)] for j in range(ny)]
    pre = [[0] * (nx + 1) for _ in range(ny + 1)]                      # 埋まっている区画の数の累積（長方形が空きかを 1 回で調べる）
    for j in range(ny):
        for i in range(nx):
            pre[j + 1][i + 1] = pre[j][i + 1] + pre[j + 1][i] - pre[j][i] + occ[j][i]

    def empty(i0, i1, j0, j1):
        return pre[j1 + 1][i1 + 1] - pre[j0][i1 + 1] - pre[j1 + 1][i0] + pre[j0][i0] == 0

    out = []
    for j0 in range(ny):
        for j1 in range(j0, ny):
            for i0 in range(nx):
                for i1 in range(i0, nx):
                    if not empty(i0, i1, j0, j1):
                        break                                            # i1 を広げても空きにならない
                    if (i0 > 0 and empty(i0 - 1, i1, j0, j1)) or (i1 < nx - 1 and empty(i0, i1 + 1, j0, j1)) \
                            or (j0 > 0 and empty(i0, i1, j0 - 1, j1)) or (j1 < ny - 1 and empty(i0, i1, j0, j1 + 1)):
                        continue                                         # まだ広げられる
                    r = (xs[i0], ys[j0], xs[i1 + 1] - xs[i0], ys[j1 + 1] - ys[j0])
                    if r[2] * r[3] >= FREE_MIN_RATIO * aw * ah and r[2] >= 0.1 * aw and r[3] >= 0.1 * ah:
                        out.append(r)
    out.sort(key=lambda r: -r[2] * r[3])
    return out[:FREE_MAX]


def place_targets(wc, front, add_front, exclude=(), screen=None):
    """置き先の候補（いまの基準モニタ上）: 並びのタイル（番号順）、前面の窓の場所（並びの外のとき）、空きスペース（広い順）。
    [{"id", "norm"（作業領域に対する割合の x, y, 幅, 高さ）, "label", "c"（画面での中心）, "free", "abs"（空きの枠）}] と、前面の窓のタイルの添字
    （なければ None）。タイルも空きもないときは、作業領域全体を「空き」の 1 枚として返す。"""
    cfg = load_config()
    screen = screen or default_screen()
    ax, ay, aw, ah = screen.work_area(cfg)
    cur = current_tiles(wc, cfg, screen)
    targets = []
    if cur["tree"] is not None:
        box = {it[0]: it[1:5] for it in cur["items"]}
        for i in tile_order(cur, cfg)[1]:
            x0, y0, x1, y1 = box[i]
            targets.append({"id": i, "norm": (x0, y0, x1 - x0, y1 - y0), "label": (cur["by_id"][i].get("wm_class") or "")[:14]})
    index = next((n for n, t in enumerate(targets) if t["id"] == front["id"]), None)
    if index is None and add_front:                      # 並びの外（最大化など）: その窓の場所を 1 枚として足す
        d = wc.details(front["id"])
        bx, by = max(0.0, (d["x"] - ax) / aw), max(0.0, (d["y"] - ay) / ah)
        targets.append({"id": front["id"], "norm": (bx, by, min(1.0 - bx, d["width"] / aw), min(1.0 - by, d["height"] / ah)),
                        "label": "ここ"})
        index = len(targets) - 1
    for x, y, w, h in free_rects(wc, exclude, screen):
        targets.append({"id": None, "free": True, "abs": (x, y, w, h), "norm": ((x - ax) / aw, (y - ay) / ah, w / aw, h / ah),
                        "label": "空き"})
    if not targets:
        targets = [{"id": None, "free": True, "abs": (ax, ay, aw, ah), "norm": (0.0, 0.0, 1.0, 1.0), "label": "空き"}]
    for t in targets:
        x, y, w, h = t["norm"]
        t["c"] = (ax + (x + w / 2) * aw, ay + (y + h / 2) * ah)
    return targets, index


def place_move(wc, front, screen, targets, index, d):
    """置き先を、左（d=-1）・右（d=1）の隣の候補へ（実際の位置で決める）。端を越えるときは、その向きの隣のモニタへ
    （そのモニタの Screen で、並びを逆算し直す。全体の既定は書き換えない）。動けなければ None。
    戻り値: (新しい Screen, 新しい候補, 新しい添字)。"""
    cx, cy = targets[index]["c"]
    side = [(abs(t["c"][0] - cx) + abs(t["c"][1] - cy), n) for n, t in enumerate(targets)
            if n != index and (t["c"][0] - cx) * d > 0]
    if side:
        return screen, targets, min(side)[1]
    mons, cur = monitors_for_preview(load_config(), screen)
    nxt = next_monitor(mons, cur, d)
    if nxt is None:
        return None
    screen = find_screen(mons[nxt]["name"])
    ax, ay, aw, ah = screen.work_area(load_config())
    new, _ = place_targets(wc, front, False, screen=screen)
    # 入ってくる側の端に近く、いまの高さに近い候補へ
    key = lambda t: ((t["c"][0] - ax) if d > 0 else (ax + aw - t["c"][0])) + abs(t["c"][1] - cy) / 2
    return screen, new, min(range(len(new)), key=lambda n: key(new[n]))


def place_initial(targets, index, n):
    """n（0＝前面の窓のタイル、1 以上＝その番号のタイル、"free"＝いちばん広い空き）が指す最初の置き先の添字。"""
    tiles = [k for k, t in enumerate(targets) if not t.get("free") and t["label"] != "ここ"]
    if n == "free":
        k = next((k for k, t in enumerate(targets) if t.get("free")), None)         # 空きは広い順に並んでいる
        if k is None:
            raise WinError("空きスペースがありません")
        return k
    if n == 0:
        return index if index is not None else 0
    if not 1 <= n <= len(tiles):
        raise WinError(f"タイル {n} がありません（いまの並びのタイルは {len(tiles)} 枚）")
    return tiles[n - 1]


def place_apply(wc, front, targets, index, chosen, minimize=False):
    """chosen を、置き先と同じ位置・大きさ（最大化なら最大化）にして前面に出す。通知する文を返す。"""
    by_id = {w["id"]: w for w in normal_windows(wc)}
    t = targets[index]
    if t["id"] is None:                      # 空きスペース: その枠に置く
        dest, dmax, dws = t["abs"], False, front.get("workspace", 0)
    else:
        d = wc.details(t["id"])
        dest = (d["x"], d["y"], d["width"], d["height"])
        dmax = bool(d.get("maximized_horizontally") and d.get("maximized_vertically"))
        dws = (by_id.get(t["id"]) or front).get("workspace", 0)
    ent = begin(wc, "place")                  # 動かす窓の、動かす前の状態（win undo で戻す）
    ent.add(wc, [chosen] + ([{"id": t["id"]}] if minimize and t["id"] is not None else []))
    ent.commit()
    notice = bring_here(wc, chosen, dest, dmax, dws)
    if minimize and t["id"] is not None and t["id"] != chosen["id"]:
        wc.simple("Minimize", t["id"])       # 元の窓は後ろに残るが、--min なら最小化する
    return notice


def cmd_place(args):
    """置き先（番号のタイル・前面の窓・空き）に、選んだ窓を重ねる。窓を省くと小窓で選び、左右矢印で置き先を動かせる。"""
    wc = WindowCalls()
    front = focused(wc)
    n = args.n
    if n != "free":
        try:
            n = int(n)
        except ValueError:
            raise WinError(f"置き先は、タイルの番号（0 は前面の窓）か free です: {args.n}")
    screen = default_screen()
    targets, fidx = place_targets(wc, front, True, screen=screen)
    index = place_initial(targets, fidx, n)
    if args.window:
        tid = targets[index]["id"]
        cands = [w for w in reversed(normal_windows(wc)) if w["id"] != tid]
        if args.window.startswith("!"):
            w = launch(wc, args.window[1:])
        else:
            found = find_windows(wc, args.window, cands)
            if not found:
                raise WinError(f"窓が見つかりません: {args.window}")
            w = found[0]
        if n == "free":                       # 置く窓がもともと空きに重なっていたら、その分を除いて空きを取り直す
            targets, _ = place_targets(wc, front, True, exclude=(w["id"],), screen=screen)
            index = place_initial(targets, fidx, "free")
        notice = place_apply(wc, front, targets, index, w, args.min)
        if notice:
            print(notice, file=sys.stderr)
        return 0
    return gui_place(wc, front, screen, targets, index, args.min)


def cmd_stack(args):
    """同じ位置に重なった窓（層）を、次・前へ切り替える。list なら小窓で選ぶ。"""
    wc = WindowCalls()
    words = [x for x in (args.n, args.action) if x is not None]          # win stack next 2 も win stack 2 next も受け付ける
    acts = [x for x in words if x in ("next", "prev", "list")]
    nums = [x for x in words if x not in ("next", "prev", "list")]
    if len(acts) > 1 or len(nums) > 1:
        raise WinError("書式: win stack [next|prev|list] [タイルの番号]（番号は 0 なら前面の窓のいるタイル）")
    action = acts[0] if acts else "next"
    try:
        n = int(nums[0]) if nums else 0
    except ValueError:
        raise WinError(f"タイルの番号か 0（前面の窓のいるタイル）を指定してください: {nums[0]}")
    if action in ("next", "prev"):
        st, w = cycle_stack(wc, n, 1 if action == "next" else -1)
        k = [x["id"] for x in st["layers"]].index(w["id"]) + 1
        print(f"タイル {st['index']}: 層 {k}/{len(st['layers'])}  {describe_window(w)}")
        return 0
    stacks = tile_stacks(wc)
    st = find_stack(wc, n, stacks)
    layers = st["layers"]
    if len(layers) < 2:
        raise WinError(f"タイル {st['index']} に重なりはありません（窓は 1 枚）")
    ids = [w["id"] for w in layers]
    i0 = ids.index(st["top"])
    order = layers[i0:] + layers[:i0]                          # いま手前の層を先頭に、巡回の順に並べる
    ax, ay, aw, ah = work_area(load_config())
    rects = [((s["rect"][0] - ax) / aw, (s["rect"][1] - ay) / ah, s["rect"][2] / aw, s["rect"][3] / ah) for s in stacks]
    m = Map(rects, [f"{len(s['layers'])}枚" if len(s["layers"]) > 1 else "" for s in stacks], stacks.index(st),
            monitor=monitors_for_preview(load_config())[1])
    items = [Item(f"{k}. " + window_row_title(w, wc.details(w["id"])), w.get("wm_class") or "", icon_for_class(w.get("wm_class")), w)
             for k, w in ((ids.index(w["id"]) + 1, w) for w in order)]
    sel = choose(f"タイル {st['index']} の重なり（{len(layers)} 層）", items, preview=lambda _it: m)
    if sel is None:
        return 1
    time.sleep(0.2)                                            # 小窓が閉じて、フォーカスが戻るのを待ってから前面に出す
    wc.simple("Activate", sel.value["id"])
    return 0


GROUP_ACTIONS = ["list", "new", "define", "add", "remove", "delete", "next", "prev", "show", "select", "place", "from-stack"]


def _windows_from(wc, specs):
    """窓の指定（クラス・題名の一部・ID・@left など）のリストを窓にする。省けば前面の窓。"""
    if not specs:
        return [focused(wc)]
    pool, out = list(reversed(normal_windows(wc))), []
    for sel in specs:
        found = find_windows(wc, sel, pool)
        if not found:
            raise WinError(f"窓が見つかりません: {sel}")
        out.append(found[0])
    return out


def resolve_specs(wc, specs, exclude=()):
    """窓の指定（layout の窓の列と同じ書き方。クラス?・クラス?コマンド・!コマンド・@ の指定）を窓にする。同じ窓は 2 度使わない。
    exclude の ID の窓は、当たっても使わない。"""
    pool, taken, out = list(reversed(normal_windows(wc))), set(exclude), []
    for sel in specs:
        if sel.startswith("!"):
            w = launch(wc, sel[1:])
        else:
            base, optional, fallback = parse_window_spec(sel)
            found = [x for x in find_windows(wc, base, pool) if x["id"] not in taken]
            if found:
                w = found[0]
            elif optional:
                cmdline = fallback or launch_for_class(base)
                if not cmdline:
                    raise WinError(f"窓が見つからず、起動コマンドも分かりません: {base}")
                w = launch(wc, cmdline)
            else:
                raise WinError(f"窓が見つかりません: {sel}")
        taken.add(w["id"])
        out.append(w)
    return out


def cmd_group(args):
    """窓のグループ。new・add・remove・delete・next・prev・show・select・place・from-stack・list。"""
    wc = WindowCalls()
    act, a = args.action, list(args.args)

    def need_name():
        if not a:
            raise WinError(f"グループの名前を指定してください（win group {act} 名前）")
        return a[0]

    if act == "list":
        data = grp.load_groups(wc)
        wins = {w["id"]: w for w in normal_windows(wc)}
        if not data:
            print("グループはありません（作るには win group new 名前 [窓…]）")
        for name, g in data.items():
            r = g.get("rect")
            print(f"グループ {name}" + (f"（枠 {r[0]},{r[1]} {r[2]}x{r[3]}）" if r else "") + f"  {len(g['members'])} 枚")
            for k, m in enumerate(g["members"], 1):
                print(f"  {'*' if m['id'] == g['active'] else ' '} {k}. {describe_window(wins[m['id']])}")
        return 0
    if act in ("new", "add"):
        name = need_name()
        wins = _windows_from(wc, a[1:])
        if act == "new":
            grp.create_group(wc, name, wins)
            notes = []
            print(f"グループ {name} を作りました（{len(wins)} 枚）")
        else:
            notes = grp.add_members(wc, name, wins)
            print(f"グループ {name} に {len(wins)} 枚を足しました")
    elif act == "define":
        name = need_name()
        if len(a) < 2:
            raise WinError("窓の指定が要ります（win group define 名前 窓の指定…）")
        others = {m["id"] for n, g in grp.load_groups(wc).items() if n != name for m in g["members"]}      # ほかのグループのメンバーは拾わない
        wins = resolve_specs(wc, a[1:], others)
        grp.define_group(wc, name, wins)
        print(f"グループ {name} を定義しました（{len(wins)} 枚）")
        return 0
    elif act == "remove":
        n = grp.remove_members(wc, _windows_from(wc, a))
        print(f"{n} 枚をグループから外しました")
        return 0
    elif act == "delete":
        grp.delete_group(wc, need_name())
        print(f"グループ {a[0]} を消しました（窓は閉じません）")
        return 0
    elif act in ("next", "prev"):
        name = grp.resolve_name(wc, a[0] if a else None)
        w, k, n = grp.cycle_group(wc, name, 1 if act == "next" else -1)
        print(f"グループ {name}: {k}/{n}  {describe_window(w)}")
        return 0
    elif act == "show":
        notes = grp.show_group(wc, grp.resolve_name(wc, a[0] if a else None))
    elif act == "select":
        name = grp.resolve_name(wc, a[0] if a else None)
        g = grp.get_group(wc, name)
        wins = {w["id"]: w for w in normal_windows(wc)}
        ids = [m["id"] for m in g["members"]]
        i0 = ids.index(g["active"]) if g["active"] in ids else 0
        order = ids[i0:] + ids[:i0]                        # いま手前のメンバーを先頭に、巡回の順に並べる
        sel = choose(f"グループ {name}（{len(ids)} 枚）",
                     [Item(f"{ids.index(i) + 1}. " + window_row_title(wins[i], wc.details(i)), wins[i].get("wm_class") or "",
                           icon_for_class(wins[i].get("wm_class")), wins[i]) for i in order])
        if sel is None:
            return 1
        time.sleep(0.2)                                    # 小窓が閉じて、フォーカスが戻るのを待ってから前面に出す
        note = grp.activate_member(wc, name, sel.value["id"])
        if note:
            print(note, file=sys.stderr)
        return 0
    elif act == "place":
        name = need_name()
        front = focused(wc)
        screen = default_screen()
        n = a[1] if len(a) > 1 else "0"
        targets, fidx = place_targets(wc, front, True, screen=screen)
        index = place_initial(targets, fidx, "free" if n == "free" else int(n))
        t = targets[index]
        rect = t["abs"] if t["id"] is None else (lambda d: (d["x"], d["y"], d["width"], d["height"]))(wc.details(t["id"]))
        notes = grp.place_group(wc, name, rect)
    elif act == "from-stack":
        n = int(a[0]) if a else 0
        name = grp.group_from_stack(wc, n, a[1] if len(a) > 1 else None)
        notes = []
        print(f"重なりからグループ {name} を作りました")
    else:
        raise WinError(f"知らない動作です: {act}")
    for note in notes:
        print(note, file=sys.stderr)
    return 0


def describe_window(w):
    """窓の 1 行の説明（クラスと題名）。"""
    return f"{w.get('wm_class') or ''}「{(w.get('title') or '')[:50]}」"


def cmd_here(args):
    """前面の窓の場所（place 0）に、選んだ窓を重ねる。"""
    args.n, args.window, args.min = "0", args.selector, False
    return cmd_place(args)


def gui_place(wc, front, screen, targets, index, minimize=False):
    """絞り込みの小窓（Dialog）で窓（先頭 ! でアプリ）を選び、置き先と同じ形にして前面に出す。左右矢印で置き先を隣の候補
    （端を越えたら隣のモニタ）へ動かせる。"""
    cfg = load_config()

    def show(d, notice=""):
        """いまの置き先に合わせて、題名・候補の窓（置き先の窓自身は除く）・地図を渡す。"""
        t = targets[index]
        d.title = ("ここに持ってくる" if t["id"] == front["id"] else
                   "空きスペースに持ってくる" if t.get("free") else f"タイル {index + 1}（{t['label']}）に持ってくる")
        d.rows([Item(window_row_title(w, wc.details(w["id"])), w.get("wm_class") or "", icon_for_class(w.get("wm_class")), w)
                for w in reversed(normal_windows(wc)) if w["id"] != t["id"]])
        d.map(Map([t["norm"] for t in targets], [t["label"] if n != index else "" for n, t in enumerate(targets)], index,
                  [bool(t.get("free")) for t in targets], monitors_for_preview(cfg, screen)[1]))
        d.notice(notice)

    chosen, placed = None, False
    with Dialog(hint=HERE_HINT, launch=True, keys=("Left", "Right"), chip="開いている窓", window_title="窓を並べる", placeholder="文字で絞り込み　先頭に！でアプリを探して新規起動",
                screen=screen) as d:
        show(d)
        for ev in d.events():
            if ev.kind == "key":
                moved = place_move(wc, front, screen, targets, index, 1 if ev.key == "Right" else -1)
                if moved:
                    screen, targets, index = moved
                show(d, "" if moved else "その向きに置き先はありません")
            elif ev.kind == "select":
                chosen = ev.item.value
                break
            elif ev.kind == "launched":
                chosen = ev.window
                notice = place_apply(wc, front, targets, index, chosen, minimize)   # 起動した窓は、アプリが決めた位置（別のモニタのことも）に
                if notice:                                                          # 見え続けないよう、小窓を閉じる前にすぐ置く
                    print(notice, file=sys.stderr)
                placed = True
                break
            elif ev.kind == "cancel":
                return 0
    if placed:
        return 0
    if not any(w["id"] == chosen["id"] for w in normal_windows(wc)):
        raise WinError("その窓はもう閉じられました")
    time.sleep(0.2)                          # 小窓が閉じて、フォーカスが戻るのを待ってから動かす
    notice = place_apply(wc, front, targets, index, chosen, minimize)
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
    res = pick_rows(wc, pool, [], "窓を選ぶ")
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
        x, y, _, _ = wc.rect(w["id"])                   # Window Calls の Resize は、窓の影の余白ぶん（CSD の窓で 25px ほど）枠を左上へずらすので、
        wc.move_resize(w["id"], x, y, args.w, args.h)   # 枠の基準の MoveResize で、位置を保って大きさだけ変える
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

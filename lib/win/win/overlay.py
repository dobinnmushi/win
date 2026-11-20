"""置き先に窓を重ねる（win place・win here）。"""

import json
import subprocess
import sys
import time

from .common import TILEPICK_APP_ID, WinError
from .screen import default_screen, find_screen, load_config
from .dbus import WindowCalls, find_windows, focused, normal_windows, targets
from .store import icon_for_class
from .pickwin import center_and_focus, pick_window
from .placement import launch, place_settled
from .nav import visible_windows
from .sets import monitors_for_preview
from .appstate import current_tiles, tile_order
from .tilepick import launch_app, list_apps, spawn_tilepick
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
    mx, my, mw, mh = mons[cur]["rect"]
    nxt = [(abs(m["rect"][0] + m["rect"][2] / 2 - (mx + mw / 2)) + abs(m["rect"][1] + m["rect"][3] / 2 - (my + mh / 2)) / 4, n)
           for n, m in enumerate(mons) if n != cur and (m["rect"][0] + m["rect"][2] / 2 - (mx + mw / 2)) * d > 0]
    if not nxt:
        return None
    screen = find_screen(mons[min(nxt)[1]]["name"])
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


def cmd_here(args):
    """前面の窓の場所（place 0）に、選んだ窓を重ねる。"""
    args.n, args.window, args.min = "0", args.selector, False
    return cmd_place(args)


def gui_place(wc, front, screen, targets, index, minimize=False):
    """絞り込みの小窓で窓（先頭 ! でアプリ）を選び、置き先と同じ形にして前面に出す。左右矢印で置き先を隣の候補
    （端を越えたら隣のモニタ）へ動かせる。"""
    cfg = load_config()
    child = spawn_tilepick()

    def send(msg):
        child.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        child.stdin.flush()

    def candidates():
        tid = targets[index]["id"]
        return [w for w in reversed(normal_windows(wc)) if w["id"] != tid]

    def tile(notice="", first=False):
        mons, mon = monitors_for_preview(cfg, screen)
        t = targets[index]
        title = ("ここに持ってくる" if t["id"] == front["id"] else
                 "空きスペースに持ってくる" if t.get("free") else f"タイル {index + 1}（{t['label']}）に持ってくる")
        msg = {"cmd": "tile", "index": index, "n": len(targets), "layout": "", "title": title, "hint": HERE_HINT,
               "rects": [t["norm"] for t in targets], "labels": [t["label"] if n != index else "" for n, t in enumerate(targets)],
               "free": [bool(t.get("free")) for t in targets],
               "windows": [{"id": w["id"], "cls": w.get("wm_class") or "", "title": window_row_title(w, wc.details(w["id"])),
                            "icon": icon_for_class(w.get("wm_class"))} for w in candidates()],
               "notice": notice, "movable": True, "mon": mon}
        if first:
            msg["apps"] = list_apps()
        return msg

    chosen = None
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
                if act == "target":
                    moved = place_move(wc, front, screen, targets, index, res.get("dir", 0))
                    if moved:
                        screen, targets, index = moved
                    send(tile("" if moved else "その向きに置き先はありません"))
                    wc.simple("Activate", wid)
                    continue
                if act == "win":
                    chosen = next((w for w in candidates() if w["id"] == res["id"]), None)
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

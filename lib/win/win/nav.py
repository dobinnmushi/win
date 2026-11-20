"""上下左右のフォーカス移動（win nav）。"""

from .common import WinError
from .screen import load_config
from .dbus import WindowCalls, focused, normal_windows


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
    from .appstate import current_tiles, tile_order        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
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

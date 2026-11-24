"""Window Calls の D-Bus と、窓の一覧・窓の指定（@ など）。"""

import json
from gi.repository import GLib
from gi.repository import Gio

from .common import NVPROMPT_APP_ID, PROMPT_APP_ID, TILEPICK_APP_ID, TILE_APP_ID, WC_IFACE, WC_NAME, WC_PATH, WinError
from .i18n import tr
from .screen import display_state, load_config, logical_rect


class WindowCalls:
    def __init__(self):
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None,
                WC_NAME, WC_PATH, WC_IFACE, None)
        except GLib.Error as e:
            raise WinError(tr("GNOME Shell に接続できません: {0}").format(e.message))

    def call(self, method, fmt=None, *args):
        params = GLib.Variant(f"({fmt})", args) if fmt else None
        try:
            return self.proxy.call_sync(method, params, Gio.DBusCallFlags.NONE, 5000, None).unpack()
        except GLib.Error as e:
            raise WinError(tr("Window Calls の {0} が失敗しました（拡張が無効かもしれません）: {1}").format(method, e.message))

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
    return w.get("window_type") == 0 and w.get("wm_class") not in (TILE_APP_ID, PROMPT_APP_ID, TILEPICK_APP_ID,
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


def minimized_windows(wc):
    """今のワークスペースにある、最小化されている窓（前面に近い順）。小窓の一覧で、選べるように後ろへ並べる。"""
    return [w for w in reversed(normal_windows(wc)) if w.get("in_current_workspace") and wc.details(w["id"]).get("minimized")]


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
    raise WinError(tr("前面の窓が見つかりません（-w で窓を指定してください）"))


def targets(wc, sel):
    """命令をかける窓のリスト。省けば前面の窓、@visible・@class: などなら当たる窓すべて、ほかは 1 枚。"""
    if sel is not None and is_multi(sel):
        found = find_windows(wc, sel)
        if not found:
            raise WinError(tr("窓が見つかりません: {0}").format(sel))
        return found
    return [target(wc, sel)]


def target(wc, sel):
    if sel is None:
        return focused(wc)
    found = find_windows(wc, sel, normal_windows(wc)[::-1])
    if not found:
        raise WinError(tr("窓が見つかりません: {0}").format(sel))
    return found[0]


# 位置・状態で窓を選ぶ指定（窓の指定を書ける所ならどこでも使える）
AT_SELECTORS = [
    ("@focused", tr("前面の窓")),
    ("@prev", tr("前面の窓の次に手前にある窓（たいてい直前に使っていた窓）")),
    ("@left", tr("前面の窓の左にある窓（nav と同じ判定）")), ("@right", tr("前面の窓の右にある窓")),
    ("@up", tr("前面の窓の上にある窓")), ("@down", tr("前面の窓の下にある窓")),
    ("@largest", tr("見えている窓のうち、いちばん大きい窓")), ("@smallest", tr("見えている窓のうち、いちばん小さい窓")),
    ("@monitor:", tr("そのモニタでいちばん手前の窓（@monitor:primary・@monitor:eDP-1 など。@monitor:other は、前面の窓がいるのとは別のモニタ）")),
    ("@slot:", tr("いまの並び（窓の位置から逆算）の N 番目のタイルの窓（@slot:1 など。番号は layout の窓の列と同じ順。@slot:0 は前面の窓）")),
    ("@visible", tr("【複数】見えている窓すべて（前面に近い順）")),
    ("@others", tr("【複数】前面の窓以外の、見えている窓すべて")),
    ("@all", tr("【複数】このワークスペースの窓すべて（最小化も含む）")),
    ("@class:", tr("【複数】そのクラスの窓すべて（@class:firefox など。大文字小文字は区別しない）")),
    ("@group:", tr("名前のグループの、手前のメンバー（@group:作業 など）。layout の窓の列では、グループ全体を 1 つのタイルに置く")),
    ("@pick", tr("その場で選ぶ（layout -i と同じ小窓。先頭 ! でアプリを起動して、その窓。Esc で命令ごと取り消す）")),
]


MULTI_SELECTORS = ("@visible", "@others", "@all", "@class:")


def is_multi(sel):
    """複数の窓に当たりうる @ の指定か。"""
    return bool(sel) and sel.lower().startswith(MULTI_SELECTORS)


def at_windows(wc, sel):
    """@ で始まる指定に当たる窓のリスト（前面に近い順。1 枚の指定なら 0〜1 枚）。知らない指定は WinError。"""
    from .pickers import pick_window_map        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
    from .nav import visible_windows        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
    from .appstate import current_tiles, tile_order        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
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
        w = pick_window_map(wc)
        if w is None:
            raise WinError(tr("@pick: 選ぶのを取り消しました"))
        return [w]
    if key.startswith("@slot:"):
        try:
            k = int(key.split(":", 1)[1])
        except ValueError:
            raise WinError(tr("@slot: の後は番号です（@slot:1 など）: {0}").format(sel))
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
    from .nav import nav_pick, visible_windows        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
    key = sel.lower()
    if key.startswith(MULTI_SELECTORS) or key.startswith("@slot:") or key == "@pick":
        found = at_windows(wc, sel)
        return found[0] if found else None
    if key.startswith("@group:"):
        from .groups import active_window        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
        return active_window(wc, sel.split(":", 1)[1])
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
        if name == "other":                                   # 前面の窓がいるモニタの、次のモニタ（左から右へ並べた順で一巡）
            order = sorted(rects, key=lambda t: (t[1][0], t[1][1]))
            front = next((w for w in normal_windows(wc) if w.get("focus")), None)
            cur = 0
            if front is not None:
                fx, fy, fw, fh = wc.rect(front["id"])
                cur = next((k for k, (lm, r) in enumerate(order)
                            if r[0] <= fx + fw / 2 < r[0] + r[2] and r[1] <= fy + fh / 2 < r[1] + r[3]), 0)
            hit = order[(cur + 1) % len(order)][1]
        else:
            hit = next((r for lm, r in rects if (name == "primary" and lm[4]) or name in [c[0] for c in lm[5]]), None)
        if hit is None:
            names = [c[0] for lm, _ in rects for c in lm[5]]
            raise WinError(tr("モニタが見つかりません: {0}（使えるのは primary, {1}）").format(name, ', '.join(names)))
        mx, my, mw, mh = hit
        for w in usable_windows(wc):                          # 前面に近い順
            x, y, rw, rh = wc.rect(w["id"])
            if mx <= x + rw / 2 < mx + mw and my <= y + rh / 2 < my + mh:
                return w
        return None
    raise WinError(tr("知らない指定です: {0}（使えるのは {1}）").format(sel, ', '.join(s for s, _ in AT_SELECTORS)))

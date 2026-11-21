"""窓・セットを選ぶ小窓（Dialog の上に作る）。win pick・win set・端末の対話モードの一覧が使う。"""

from .dialog import Dialog, Item, Map
from .i18n import tr
from .dialog import pick_window as pick_window_dialog
from .tilepick import slot_map
from .store import icon_for_class
from .pickwin import row_title
from .sets import monitors_for_preview, next_monitor, set_preview, set_summary


def pick_rows(wc, windows, extras, title=tr("窓を選ぶ")):
    """窓の一覧を出し、選ばれた行の動作 {"act": ...} を返す（取消は None）。extras は [(動作, 表示)] で、窓のあとに足す行。
    入力欄はなく、j/k・↑↓ で動き、Enter か l で決め、1〜9 で直接選び、Esc・q・h で取り消す。"""
    items = [Item(row_title(w, wc.details(w["id"])), w.get("wm_class") or "", icon_for_class(w.get("wm_class")),
                  {"act": "win", "id": w["id"]}) for w in windows]
    items += [Item(label, value={"act": act}) for act, label in extras]
    if not items:
        return None
    with Dialog(window_title=title, hint=tr("j/k ↑↓ 移動 ・ Enter/l 決定 ・ 1–9 直接 ・ Esc/q/h 取消"), entry=False, vim=True,
                numbers=True) as d:
        d.rows(items)
        for ev in d.events():
            if ev.kind == "select":
                return ev.item.value
            if ev.kind == "cancel":
                return None
    return None


def pick_set(wc, cfg, sets):
    """名前で絞り込みながら、プレビューを見て選ぶ小窓。(選ばれたセットの名前, 選ばれたモニタの接続名)。取消は (None, None)。
    左右矢印で適用先のモニタを選べる。モニタが 1 枚なら接続名は None（基準のモニタのまま）。"""
    mons, mon = monitors_for_preview(cfg)
    many = len(mons) > 1
    tiles = {n: set_preview(c, cfg) for n, c in sets.items()}
    items = [Item(n, set_summary(c)[:90], value=n) for n, c in sets.items()]

    def preview(item):
        ts = tiles[item.value] if item is not None else []
        return Map([(t["x"], t["y"], t["w"], t["h"]) for t in ts], [t["label"] for t in ts], -1, None, mon) if ts else None

    def title():
        return tr("適用先: {0}").format(mons[mon]['name']) if many else ""

    shown = items[0] if items else None
    with Dialog(title(), window_title=tr("セットを選ぶ"), highlight=True, keys=("Left", "Right") if many else (),
                placeholder=tr("セットの名前で絞り込み…"),
                hint=tr("入力で絞り込み ・ ↑↓ で選ぶ") + (tr(" ・ ←→ でモニタを選ぶ") if many else "") + tr(" ・ Enter で適用 ・ Esc で閉じる")) as d:
        d.rows(items)
        d.map(preview(shown))
        for ev in d.events():
            if ev.kind == "select":
                return ev.item.value, (mons[mon]["name"] if many else None)
            if ev.kind == "highlight":
                shown = ev.item
                d.map(preview(shown))
            elif ev.kind == "key":
                nxt = next_monitor(mons, mon, 1 if ev.key == "Right" else -1)
                if nxt is not None:
                    mon = nxt
                    d.title = title()
                    d.map(preview(shown))
            elif ev.kind == "cancel":
                return None, None
    return None, None


def pick_window_map(wc, title=tr("窓を選ぶ"), rects=None, index=0, labels=None, allow_launch=True, exclude=()):
    """窓を 1 枚選ぶ（先頭 ! でアプリを起動して、その窓）。選んだ窓、取り消しなら None。
    rects（作業領域を 0〜1 にした (x, y, 幅, 高さ) のリスト）と index を渡すと、小窓の地図でそのタイルを強調する。
    rects を省くと、地図にはいまの並び（どこに何があるか）を出す（強調はしない）。"""
    if rects is None:
        rects, labels = slot_map(wc)
        index = -1
    m = Map(rects or [(0.0, 0.0, 1.0, 1.0)], labels, index)
    return pick_window_dialog(title, launch=allow_launch, exclude=tuple(exclude), map=m)

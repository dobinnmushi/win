"""窓の一覧の行の表示名と、小窓の位置合わせ。"""

import time

from .screen import load_config, work_area


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


def line_from_picker(wc, pool):
    """一覧の選択を、対話モードの入力文字列に直す（取消は None）。"""
    from .pickers import pick_rows        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
    res = pick_rows(wc, pool, [("cmd", "コマンドを入力して新しく起動…"),
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

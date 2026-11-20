"""窓のグループ（名前つき・保存つき）。グループは 1 つの枠（位置・大きさ）を持ち、メンバーを順に、その枠へ置いて前面に出す（タブのように）。

保存先は ~/.local/state/win/groups.json（WIN_GROUPS で差し替え可）。メンバーは窓の ID で持ち、閉じた窓は読み込み時に取り除く。
1 つの窓は、高々 1 つのグループに入る。メンバーの順が、巡回（next・prev）の順。
"""

from concurrent.futures import ThreadPoolExecutor
import json
import os

from .common import WinError
from .dbus import focused, normal_windows
from .placement import place_settled
from .appstate import find_stack

GROUPS_FILE = os.environ.get("WIN_GROUPS") or os.path.join(
    os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "win", "groups.json")
RECT_TOL = 8      # 枠がこれ以内（px）しかずれていなければ、すでにグループの枠にあるとみなす


# ---------------------------------------------------------------- 保存

def _read():
    try:
        with open(GROUPS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data):
    os.makedirs(os.path.dirname(GROUPS_FILE), exist_ok=True)
    tmp = GROUPS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, GROUPS_FILE)                              # 書きかけのファイルを残さない


def load_groups(wc):
    """{名前: {"members": [{"id", "cls"}…], "rect": [x, y, w, h] か None, "active": 窓の ID か None}}。閉じた窓は取り除き、空になったグループは消す。"""
    data = _read()
    alive = {w["id"] for w in normal_windows(wc)}
    changed = False
    for name in list(data):
        g = data[name]
        keep = [m for m in g.get("members", []) if m.get("id") in alive]
        if len(keep) != len(g.get("members", [])):
            changed = True
            g["members"] = keep
        if g.get("active") not in {m["id"] for m in keep}:
            g["active"] = keep[0]["id"] if keep else None
        if not keep:
            del data[name]
            changed = True
    if changed:
        _write(data)
    return data


def group_of(wc, wid, data=None):
    """窓 wid の属するグループの名前。どこにも属さなければ None。"""
    data = load_groups(wc) if data is None else data
    return next((n for n, g in data.items() if any(m["id"] == wid for m in g["members"])), None)


def get_group(wc, name, data=None):
    data = load_groups(wc) if data is None else data
    if name not in data:
        raise WinError(f"グループがありません: {name}（一覧は win group）")
    return data[name]


def resolve_name(wc, name=None, data=None):
    """name を省いたときは、前面の窓の属するグループの名前。"""
    data = load_groups(wc) if data is None else data
    if name:
        get_group(wc, name, data)
        return name
    got = group_of(wc, focused(wc)["id"], data)
    if got is None:
        raise WinError("前面の窓はグループに入っていません（グループの名前を指定してください）")
    return got


# ---------------------------------------------------------------- 窓を枠へ置く

def _frame(wc, wid):
    d = wc.details(wid)
    return (d["x"], d["y"], d["width"], d["height"]), d


def bring(wc, w, rect, workspace, activate=True):
    """窓 w を rect に置く（別のデスクトップなら今のデスクトップへ、最小化・最大化は解く）。activate なら前面に出す。注意の文（なければ ""）を返す。"""
    if not w.get("in_current_workspace"):
        wc.call("MoveToWorkspace", "uu", w["id"], max(0, workspace))
    _, d = _frame(wc, w["id"])
    if d.get("minimized"):
        wc.simple("Unminimize", w["id"])
    if d.get("maximized_horizontally") or d.get("maximized_vertically"):
        wc.simple("Unmaximize", w["id"])
    got = place_settled(wc, w["id"], tuple(rect))
    if activate:
        wc.simple("Activate", w["id"])
    return f"希望の大きさにならず {got[2]}x{got[3]} です（最小サイズなど）" if got else ""


def _desktop(wc):
    try:
        return focused(wc).get("workspace", 0)
    except WinError:
        return 0


def group_rect(wc, g):
    """グループの枠。手前のメンバーがいまいる枠があればそれ（動かしたものに追従する）、なければ保存した枠。"""
    act = g.get("active")
    if act is not None:
        try:
            r, d = _frame(wc, act)
            if not d.get("minimized") and not (d.get("maximized_horizontally") and d.get("maximized_vertically")):
                return list(r)
        except WinError:
            pass
    if g.get("rect"):
        return list(g["rect"])
    raise WinError("グループの枠が分かりません（先にメンバーを置いてください）")


def _by_id(wc):
    return {w["id"]: w for w in normal_windows(wc)}


# ---------------------------------------------------------------- 操作

def create_group(wc, name, windows):
    """窓 windows でグループ name を作る（枠は最初の窓の枠）。すでにあれば WinError。メンバーは、ほかのグループから移る。"""
    data = load_groups(wc)
    if name in data:
        raise WinError(f"グループはすでにあります: {name}（足すなら win group add）")
    if not windows:
        raise WinError("窓がありません")
    _leave(data, [w["id"] for w in windows])
    rect, _ = _frame(wc, windows[0]["id"])
    data[name] = {"members": [{"id": w["id"], "cls": w.get("wm_class") or ""} for w in windows], "rect": list(rect),
                  "active": windows[0]["id"]}
    _write(data)
    return data[name]


def _leave(data, ids):
    """ids の窓を、いまのグループから外す（空になったグループは消す）。"""
    for n in list(data):
        data[n]["members"] = [m for m in data[n]["members"] if m["id"] not in ids]
        if not data[n]["members"]:
            del data[n]


def add_members(wc, name, windows):
    """グループ name に窓を足し、グループの枠へ置いて、最後に足した窓を手前にする。メンバーは、ほかのグループから移る。"""
    data = load_groups(wc)
    g = get_group(wc, name, data)
    rect = group_rect(wc, g)
    ids = [w["id"] for w in windows]
    _leave(data, ids)
    g = data.setdefault(name, g)
    have = {m["id"] for m in g["members"]}
    notes = []
    ws = _desktop(wc)
    for w in windows:
        if w["id"] not in have:
            g["members"].append({"id": w["id"], "cls": w.get("wm_class") or ""})
        notes.append(bring(wc, w, rect, ws, activate=(w is windows[-1])))
    g["active"], g["rect"] = windows[-1]["id"], rect
    _write(data)
    return [n for n in notes if n]


def remove_members(wc, windows):
    """窓をグループから外す。外した窓の数を返す。"""
    data = load_groups(wc)
    ids = [w["id"] for w in windows if group_of(wc, w["id"], data)]
    _leave(data, ids)
    _write(data)
    return len(ids)


def delete_group(wc, name):
    data = load_groups(wc)
    get_group(wc, name, data)
    del data[name]
    _write(data)


def activate_member(wc, name, wid):
    """グループ name のメンバー wid を、グループの枠に置いて前面に出す（グループの枠と、手前のメンバーを更新する）。注意の文を返す。"""
    data = load_groups(wc)
    g = get_group(wc, name, data)
    w = _by_id(wc).get(wid)
    if w is None or all(m["id"] != wid for m in g["members"]):
        raise WinError("その窓は、このグループのメンバーではありません")
    rect = group_rect(wc, g)
    note = bring(wc, w, rect, _desktop(wc))
    g["active"], g["rect"] = wid, list(rect)
    _write(data)
    return note


def cycle_group(wc, name, d=1):
    """グループ name で、いま手前のメンバーから d 個ずれたメンバーを、グループの枠へ置いて前面に出す（一巡する）。(窓, 層の番号 1 から, 数) を返す。"""
    data = load_groups(wc)
    g = get_group(wc, name, data)
    ids = [m["id"] for m in g["members"]]
    if len(ids) < 2:
        raise WinError(f"グループ {name} のメンバーは 1 枚だけです")
    k = (ids.index(g["active"]) + d) % len(ids) if g.get("active") in ids else 0
    activate_member(wc, name, ids[k])
    return _by_id(wc)[ids[k]], k + 1, len(ids)


def show_group(wc, name):
    """グループ name の全メンバーをグループの枠へ置き（別のデスクトップ・最小化も今のデスクトップへ戻す）、手前のメンバーを前面に出す。"""
    data = load_groups(wc)
    g = get_group(wc, name, data)
    rect, ws, wins = group_rect(wc, g), _desktop(wc), _by_id(wc)
    members = [wins[m["id"]] for m in g["members"] if m["id"] in wins]
    with ThreadPoolExecutor(max_workers=max(1, len(members))) as ex:          # 置いたあとの定着待ちは、窓ごとに並行して行う
        notes = list(ex.map(lambda w: bring(wc, w, rect, ws, activate=False), members))
    act = g.get("active") if g.get("active") in wins else members[0]["id"]
    wc.simple("Activate", act)
    g["active"], g["rect"] = act, list(rect)
    _write(data)
    return [n for n in notes if n]


def place_group(wc, name, rect):
    """グループ name の枠を rect に変えて、全メンバーをそこへ置く。"""
    data = load_groups(wc)
    g = get_group(wc, name, data)
    g["rect"] = list(rect)
    g["active"] = g["active"] if g.get("active") is not None else g["members"][0]["id"]
    _write(data)
    wins, ws = _by_id(wc), _desktop(wc)
    members = [wins[m["id"]] for m in g["members"] if m["id"] in wins]
    with ThreadPoolExecutor(max_workers=max(1, len(members))) as ex:
        notes = list(ex.map(lambda w: bring(wc, w, rect, ws, activate=False), members))
    wc.simple("Activate", g["active"])
    return [n for n in notes if n]


def group_from_stack(wc, n=0, name=None):
    """n 番目のタイル（0 は前面の窓のいるタイル）の重なり（層）を、グループにする。名前を省くと「タイル n」。作ったグループの名前を返す。"""
    st = find_stack(wc, n)
    if len(st["layers"]) < 2:
        raise WinError(f"タイル {st['index']} に重なりはありません（窓は 1 枚）")
    name = name or f"タイル{st['index']}"
    create_group(wc, name, st["layers"])
    data = load_groups(wc)
    data[name]["active"] = st["top"]
    _write(data)
    return name

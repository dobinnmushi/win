"""アプリの状態（Firefox のタブ・端末の作業ディレクトリ）と、いまの並びの逆算。"""

from concurrent.futures import ThreadPoolExecutor
import configparser
import functools
import json
import math
import os
import re
import shlex
import subprocess
import sys
import time
import unicodedata

from .common import WinError
from .screen import default_screen, load_config, work_area
from .layouts import LayoutParser, leaf_rects
from .dbus import WindowCalls, focused, normal_windows
from .store import SETS, load_sets, save_sets
from .placement import launch, parse_window_spec, wait_new_window
from .nav import visible_windows
from .sets import set_summary


# 「win save --state …」で選んだときだけ保存する。汎用のセットには入れない（開く場所が固定されてしまうため）。

def mozlz4_loads(data):
    """Firefox の mozlz4（目印＋展開後の大きさ＋ lz4 のブロック）を展開して JSON を読む。"""
    if data[:8] != b"mozLz40\0":
        raise ValueError("mozlz4 ではありません")
    src, out, i = data[12:], bytearray(), 0
    while i < len(src):
        token = src[i]
        i += 1
        n = token >> 4
        if n == 15:
            while True:
                b = src[i]
                i += 1
                n += b
                if b != 255:
                    break
        out += src[i:i + n]
        i += n
        if i >= len(src):
            break
        off = src[i] | (src[i + 1] << 8)
        i += 2
        m = token & 15
        if m == 15:
            while True:
                b = src[i]
                i += 1
                m += b
                if b != 255:
                    break
        start = len(out) - off
        for k in range(m + 4):                              # 重なるコピーは 1 バイトずつ
            out.append(out[start + k])
    return json.loads(out.decode("utf-8"))


def firefox_profile_dir():
    """既定の Firefox プロファイルのディレクトリ（なければ None）。"""
    for base in (os.path.expanduser("~/.config/mozilla/firefox"), os.path.expanduser("~/.mozilla/firefox")):
        paths = []
        cp = configparser.ConfigParser(interpolation=None)
        if cp.read(os.path.join(base, "installs.ini"), encoding="utf-8"):
            paths += [cp.get(sec, "Default") for sec in cp.sections() if cp.has_option(sec, "Default")]
        cp = configparser.ConfigParser(interpolation=None)
        if cp.read(os.path.join(base, "profiles.ini"), encoding="utf-8"):
            paths += [cp.get(sec, "Path") for sec in cp.sections()
                      if cp.has_option(sec, "Path") and cp.get(sec, "Default", fallback="0") == "1"]
        for pth in paths:
            d = pth if os.path.isabs(pth) else os.path.join(base, pth)
            if os.path.isdir(d):
                return d
    return None


def firefox_session_windows(profile=None):
    """Firefox のセッション（窓ごとのタブの一覧）。保存は 15 秒ほど遅れることがある。"""
    d = profile or firefox_profile_dir()
    if not d:
        raise WinError("Firefox のプロファイルが見つかりません")
    for name in ("sessionstore-backups/recovery.jsonlz4", "sessionstore.jsonlz4"):
        path = os.path.join(d, name)
        if os.path.exists(path):
            with open(path, "rb") as f:
                return mozlz4_loads(f.read()).get("windows", [])
    raise WinError("Firefox のセッション情報が見つかりません")


def _norm_title(t):
    t = "".join(c for c in (t or "") if unicodedata.category(c) != "Cf").strip()      # 目に見えない書式文字を除く
    return re.sub(r"\s*[—–-]\s*Mozilla Firefox$", "", t).strip()


def _firefox_tab_entry(tab):
    ents = tab.get("entries") or []
    return ents[min(max(tab.get("index", len(ents)), 1), len(ents)) - 1] if ents else {}


def firefox_window_title(sw):
    tabs = sw.get("tabs") or []
    return _norm_title(_firefox_tab_entry(tabs[min(max(sw.get("selected", 1), 1), len(tabs)) - 1]).get("title")) if tabs else ""


def firefox_tab_urls(sw):
    skip = ("about:blank", "about:newtab", "about:home", "about:privatebrowsing")
    urls = [_firefox_tab_entry(t).get("url", "") for t in sw.get("tabs") or []]
    return [u for u in urls if u and u not in skip and not u.startswith(("moz-extension:", "javascript:"))]


def _url_arg(u):
    """URL を、引用符なしで書ける形にする（空白・引用符・バックスラッシュだけを % 表記にする。URL としては同じ意味）。"""
    return re.sub(r"[\s'\"\\]", lambda m: "%%%02X" % ord(m.group()), u)


def firefox_state(windows, session=None):
    """Firefox の窓ごとに、タブを開き直す起動コマンド。({窓の id: コマンド}, 注意のリスト)。窓との対応は、いま表示中のタブの題名で取る。"""
    try:
        sess = firefox_session_windows() if session is None else session
    except (WinError, OSError, ValueError, KeyError, IndexError) as e:
        return {}, [f"Firefox のタブを読めませんでした（{e}）"]
    out, notes, used = {}, [], set()
    for w in windows:
        title = _norm_title(w.get("title"))
        cands = [k for k, sw in enumerate(sess) if k not in used and firefox_window_title(sw) == title]
        if not cands:
            notes.append(f"Firefox の窓「{title[:24]}」: セッションの窓と対応が取れませんでした（タブの保存は 15 秒ほど遅れます）")
            continue
        used.add(cands[0])
        urls = firefox_tab_urls(sess[cands[0]])
        if not urls:
            notes.append(f"Firefox の窓「{title[:24]}」: 保存できるタブがありません")
            continue
        out[w["id"]] = "win browse " + " ".join(_url_arg(u) for u in urls)
    return out, notes


def ptyxis_tabs():
    """端末（Ptyxis）の各タブの [(pts 番号, シェルの作業ディレクトリ)]。"""
    try:
        pids = subprocess.run(["pgrep", "-x", "ptyxis"], capture_output=True, text=True).stdout.split()
    except OSError:
        return []
    ptys = set()
    for pid in pids:
        fdir = f"/proc/{pid}/fd"
        try:
            for fd in os.listdir(fdir):
                if os.readlink(os.path.join(fdir, fd)) == "/dev/ptmx":
                    with open(f"/proc/{pid}/fdinfo/{fd}") as f:
                        m = re.search(r"^tty-index:\s*(\d+)", f.read(), re.M)
                    if m:
                        ptys.add(int(m.group(1)))
        except OSError:
            continue
    tabs = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/stat") as f:
                rest = f.read().rsplit(")", 1)[1].split()
            session, tty_nr = int(rest[3]), int(rest[4])
            if session == int(pid) and (tty_nr >> 8) == 136 and (tty_nr & 0xFF) in ptys:     # pts のセッションリーダー（シェル）
                tabs[tty_nr & 0xFF] = os.readlink(f"/proc/{pid}/cwd")
        except (OSError, IndexError, ValueError):
            continue
    return sorted(tabs.items())


def terminal_state(windows, tabs=None):
    """端末の窓ごとに、作業ディレクトリのタブを開き直す起動コマンド。({窓の id: コマンド}, 注意のリスト)。
    窓とタブの対応は、窓が 1 つのときと、題名（… ~/dir）から 1 対 1 に決まるときだけ取れる。"""
    tabs = ptyxis_tabs() if tabs is None else tabs
    if not tabs:
        return {}, ["端末のタブの作業ディレクトリを読めませんでした"]
    home = os.path.expanduser("~")
    short = lambda d: "~" + d[len(home):] if d == home or d.startswith(home + "/") else d
    if len(windows) == 1:
        return {windows[0]["id"]: "win term " + " ".join(shlex.quote(d) for _, d in tabs)}, []
    out, used = {}, set()
    for w in windows:
        title = (w.get("title") or "").strip()
        cands = [(n, d) for n, d in tabs if n not in used and title.endswith(short(d))]
        if len(cands) != 1:
            return {}, ["端末の窓が複数あり、窓とタブの対応が取れないため、端末の状態は保存しません"]
        used.add(cands[0][0])
        out[w["id"]] = "win term " + shlex.quote(cands[0][1])
    return out, ["端末の窓が複数あるため、各窓の表示中のタブの作業ディレクトリだけ保存します"]


def cmd_browse(args):
    """Firefox を新しい窓で開き、URL をタブとして並べる。
    （起動中の Firefox では、1 回の呼び出しに --new-window と --new-tab を並べると、タブが元の窓に入ってしまう。
    そのため、窓を開いて前面になってから、タブを 1 つずつ足す。）"""
    wc = WindowCalls()
    ff = shlex.split(os.environ.get("WIN_FIREFOX", "firefox"))        # 試験用に、別のプロファイルの Firefox へ差し替えられる
    before = {w["id"] for w in normal_windows(wc)}
    subprocess.Popen(ff + ["--new-window", args.urls[0]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    win = wait_new_window(wc, before, 25, "firefox")
    for u in args.urls[1:]:
        wc.simple("Activate", win["id"])
        time.sleep(0.5)
        subprocess.run(ff + ["--new-tab", u], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)
        time.sleep(0.8)
    return 0


def cmd_term(args):
    """端末（Ptyxis）を、作業ディレクトリごとのタブつきで新しく開く。"""
    wc = WindowCalls()
    dirs = [os.path.expanduser(d) for d in args.dirs] or [os.getcwd()]       # ~ も使えるように（手で書く行では、シェルが展開しないため）
    before = {w["id"] for w in normal_windows(wc)}
    subprocess.Popen(["ptyxis", "--new-window", "-d", dirs[0]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    win = wait_new_window(wc, before, 15, "ptyxis")
    for d in dirs[1:]:
        wc.simple("Activate", win["id"])                  # 「アクティブな窓」に新しいタブを作るので、先に前面にする
        time.sleep(0.4)
        subprocess.run(["ptyxis", "--tab", "-d", d], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10)
        time.sleep(0.5)
    return 0


SET_TOL = 0.03          # 窓の端を同じ線とみなす許容（作業領域に対する割合）。タイルの隙間を吸収する


def _weights_to_ints(ws):
    """幅の比を、小さい整数の比にする（合わなければ小数 1 桁）。"""
    lo = min(ws)
    r = [w / lo for w in ws]
    for m in range(1, 9):
        v = [x * m for x in r]
        if all(round(x) >= 1 and abs(x - round(x)) <= 0.06 * x for x in v):
            ints = [round(x) for x in v]
            g = functools.reduce(math.gcd, ints)
            return [i // g for i in ints]
    return [round(x, 1) for x in r]


def _split_groups(items, axis, tol):
    """どの窓も横切らない線で、axis（0=x, 1=y）方向に分けた窓の群。分けられなければ None。"""
    a0, a1 = (1, 3) if axis == 1 else (0, 2)
    items = sorted(items, key=lambda it: (it[1 + a0], it[1 + a1]))
    groups, end = [[items[0]]], items[0][1 + a1]
    for it in items[1:]:
        if it[1 + a0] >= end - tol:
            groups.append([it])
            end = it[1 + a1]
        else:
            groups[-1].append(it)
            end = max(end, it[1 + a1])
    return groups if len(groups) > 1 else None


def _build_tree(items, box, tol, dropped):
    """items: (id, x0, y0, x1, y1, z)。分割の木 ("leaf", id) / ("split", "v"|"h", 重み, 子) を返す。
    分けられない（重なった）窓は、他にいちばん多く重なるものから外して dropped に入れる。"""
    if len(items) == 1:
        return ("leaf", items[0][0])
    for axis, d in ((0, "v"), (1, "h")):
        groups = _split_groups(items, axis, tol)
        if not groups:
            continue
        a0, a1 = (1, 3) if axis == 1 else (0, 2)
        lo, hi = box[a0], box[a1]
        starts = [min(it[1 + a0] for it in g) for g in groups]
        ends = [max(it[1 + a1] for it in g) for g in groups]
        bounds = [lo] + [(ends[k - 1] + starts[k]) / 2 for k in range(1, len(groups))] + [hi]
        weights = _weights_to_ints([max(bounds[k + 1] - bounds[k], 1e-6) for k in range(len(groups))])
        kids = []
        for k, g in enumerate(groups):
            sub = list(box)
            sub[a0], sub[a1] = bounds[k], bounds[k + 1]
            kids.append(_build_tree(g, tuple(sub), tol, dropped))
        return ("split", d, weights, kids)
    def overlaps(a, b):
        return (min(a[3], b[3]) - max(a[1], b[1]) > tol) and (min(a[4], b[4]) - max(a[2], b[2]) > tol)

    # 分けられない: 他の窓にいちばん多く重なる窓（同数なら下にある窓）を外して、やり直す
    victim = max(items, key=lambda it: (sum(1 for o in items if o is not it and overlaps(it, o)), -it[5]))
    dropped.append(victim[0])
    return _build_tree([it for it in items if it is not victim], box, tol, dropped)


def _tree_expr(node):
    if node[0] == "leaf":
        return "full"
    _, d, ws, kids = node
    args = []
    for w, k in zip(ws, kids):
        if k[0] == "leaf":
            args.append(f"{w:g}")
        else:
            e = _tree_expr(k)
            args.append(e if w == 1 else f"{w:g}:{e}")
    return f"{d}({','.join(args)})"


def _tree_leaves(node):
    return [node[1]] if node[0] == "leaf" else [i for k in node[3] for i in _tree_leaves(k)]


def _match_named(items, layouts, tol):
    """窓の並びと同じ形の、名前のついた型があれば (名前, 窓の id をタイルの順に並べたもの)。"""
    for name, expr in layouts.items():
        try:
            rects = [tuple(c / 1000 for c in r) for r in leaf_rects(LayoutParser(expr).parse(), (0, 0, 1000, 1000))]
        except WinError:
            continue
        if len(rects) != len(items):
            continue
        left, order = list(items), []
        for r in rects:
            best = min(left, key=lambda it: sum(abs(a - b) for a, b in zip(r, it[1:5])))
            if any(abs(a - b) > 2 * tol for a, b in zip(r, best[1:5])):
                break
            left.remove(best)
            order.append(best[0])
        else:
            return name, order
    return None


def current_tiles(wc, cfg, screen=None):
    """いま基準のモニタ（screen。省くと既定）に出ている窓の並びを、窓の位置から逆算する（win save と @slot が使う）。
    {"onmon", "other", "maxed", "items", "tree", "dropped", "by_id"}。tree は最大化していない窓だけで作る（なければ None）。"""
    screen = screen or default_screen()
    ax, ay, aw, ah = screen.work_area(cfg)
    mx, my, mw, mh = screen.rect
    by_id = {w["id"]: w for w in normal_windows(wc)}
    onmon, other = [], 0
    for z, (w, (x, y, rw, rh)) in enumerate(visible_windows(wc)):         # 下 → 上
        if mx <= x + rw / 2 < mx + mw and my <= y + rh / 2 < my + mh:
            onmon.append((z, w, (x, y, rw, rh)))
        else:
            other += 1
    maxed = [t for t in onmon if (lambda d: d.get("maximized_horizontally") and d.get("maximized_vertically"))(wc.details(t[1]["id"]))]
    items = []
    for z, w, (x, y, rw, rh) in onmon:
        if any(t[1]["id"] == w["id"] for t in maxed):
            continue
        clamp = lambda v: min(1.0, max(0.0, v))
        items.append((w["id"], clamp((x - ax) / aw), clamp((y - ay) / ah),
                      clamp((x + rw - ax) / aw), clamp((y + rh - ay) / ah), z))
    dropped = []
    tree = _build_tree(items, (0.0, 0.0, 1.0, 1.0), SET_TOL, dropped) if items else None
    return {"onmon": onmon, "other": other, "maxed": maxed, "items": items, "tree": tree, "dropped": dropped, "by_id": by_id}


def tile_order(cur, cfg):
    """逆算した並びのタイル順の窓 ID（名前つきの型と同じ形なら、その型のタイル順）。"""
    kept = set(_tree_leaves(cur["tree"]))
    named = _match_named([it for it in cur["items"] if it[0] in kept], cfg["layouts"], SET_TOL)
    return (named[0], named[1]) if named else (_tree_expr(cur["tree"]), _tree_leaves(cur["tree"]))


def arrangement_lines(wc, state=()):
    """いま表に出ている窓（基準のモニタ上のもの）を、「型＋窓の列」の命令にする。(行のリスト, 注意のリスト, 窓の数)。
    state に "firefox"・"terminal" を指定すると、その窓は、窓がなければ状態つきで開くよう保存する（選んだときだけ）。"""
    cfg = load_config()
    cur = current_tiles(wc, cfg)
    onmon, other, maxed, items, tree, dropped, by_id = (cur[k] for k in ("onmon", "other", "maxed", "items", "tree", "dropped", "by_id"))
    notes = []
    if other:
        notes.append(f"別のモニタにある窓 {other} 枚は含めていません")

    launch_cmds = {}                                          # 状態つきで起動するコマンド {窓の id: コマンド}

    def token(w):
        cls = w.get("wm_class") or ""
        if w["id"] in launch_cmds:
            return shlex.quote(f"{cls}?{launch_cmds[w['id']]}")
        return shlex.quote(cls) + "?" if cls else shlex.quote((w.get("title") or "")[:30])

    tiled = [t for t in onmon if t not in maxed]
    if not tiled:
        if not maxed:
            raise WinError("保存できる窓がありません")
        w = maxed[-1][1]
        if len(maxed) > 1:
            notes.append(f"最大化している窓のうち、いちばん上の 1 枚だけ保存します（{len(maxed) - 1} 枚は含めていません）")
        cls = w.get("wm_class") or str(w["id"])
        return [f"layout full {token(w)}", f"max -w {shlex.quote(cls)}"], notes, 1
    if maxed:
        notes.append(f"最大化している窓 {len(maxed)} 枚は含めていません")
    if dropped:
        names = ", ".join(sorted({by_id[i].get("wm_class") or "?" for i in dropped}))
        notes.append(f"重なっている窓 {len(dropped)} 枚は含めていません（{names}）。各タイルで、いちばん上の窓だけ保存します")
    kept = set(_tree_leaves(tree))
    kept_items = [it for it in items if it[0] in kept]
    kept_windows = [by_id[i] for i in kept]
    for kind, cls, fn in (("firefox", "firefox", firefox_state), ("terminal", "org.gnome.Ptyxis", terminal_state)):
        if kind in state:
            targets = [w for w in kept_windows if (w.get("wm_class") or "") == cls]
            if not targets:
                notes.append(f"{'Firefox' if kind == 'firefox' else '端末'} の窓がないため、状態は保存しません")
                continue
            got, more = fn(targets)
            launch_cmds.update(got)
            notes += more
    area = sum((it[3] - it[1]) * (it[4] - it[2]) for it in kept_items)
    if area < 0.6:
        notes.append("画面の一部しか使っていない並びです。呼ぶと、窓は画面いっぱいに広がります")
    expr, order = tile_order(cur, cfg)
    return [f"layout {expr} " + " ".join(token(by_id[i]) for i in order)], notes, len(order)


def save_arrangement(wc, name, overwrite=False, state=()):
    """いまの窓の並びを、型と窓の列の命令（セット）として name で保存する。(保存した窓の数, 注意のリスト) を返す。"""
    name = name.strip()
    if not name:
        raise WinError("名前が空です")
    sets = load_sets()
    if name in sets and not overwrite:
        raise WinError(f"「{name}」はすでにあります（上書きするには --force）")
    lines, notes, count = arrangement_lines(wc, state)
    sets[name] = {"type": "win", "run": "\n".join(lines)}
    save_sets(sets)
    return count, notes


def run_arrangement(wc, entry):
    """保存した並びを再現する。窓が足りなければ起動コマンドで新規起動する。注意の一覧を返す。"""
    from .overlay import bring_here        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
    ax, ay, aw, ah = work_area(load_config())
    try:
        ws = focused(wc).get("workspace", 0)
    except WinError:
        ws = 0
    pool = list(reversed(normal_windows(wc)))                 # 前面が先
    used = set()
    events = []                                               # 保存順に、("note", 文) か ("job", クラス, 窓, 置く処理)
    with ThreadPoolExecutor(max_workers=max(1, len(entry.get("windows", [])))) as ex:      # 置いたあとの定着待ちは、窓ごとに並行して行う
        for e in entry.get("windows", []):                    # 保存順（下 → 上）。起動は 1 つずつ（新しい窓の見分けが混ざらないように）
            cls = e.get("cls", "")
            found = [w for w in pool if (w.get("wm_class") or "") == cls and w["id"] not in used]
            found.sort(key=lambda w: (w.get("title") or "")[:60] != e.get("title"))   # 同じクラスなら題名が一致する窓を優先
            w = found[0] if found else None
            if w is None and e.get("launch"):
                try:
                    w = launch(wc, e["launch"], 12)
                except WinError as err:
                    events.append(("note", f"{cls}: 起動できませんでした（{err}）"))
            if w is None:
                if not e.get("launch"):
                    events.append(("note", f"{cls}: 窓が見つかりません（起動コマンドも不明）"))
                continue
            used.add(w["id"])
            if e.get("maximized"):
                job = ex.submit(bring_here, wc, w, (0, 0, 0, 0), True, ws, False)
            else:
                x, y, rw, rh = e["rect"]
                job = ex.submit(bring_here, wc, w, (ax + round(x * aw), ay + round(y * ah), round(rw * aw), round(rh * ah)),
                                False, ws, False)
            events.append(("job", cls, w, job))
        events = [ev if ev[0] == "note" else ("job", ev[1], ev[2], ev[3].result()) for ev in events]
    notes = []
    for ev in events:                                         # 重なり順は、保存順（下 → 上）に前面へ出して再現する
        if ev[0] == "note":
            notes.append(ev[1])
        else:
            _, cls, w, msg = ev
            wc.simple("Activate", w["id"])
            if msg:
                notes.append(f"{cls}: {msg}")
    return notes


def cmd_save(args):
    wc = WindowCalls()
    state = ("firefox", "terminal") if "all" in (args.state or []) else tuple(args.state or [])
    n, notes = save_arrangement(wc, args.name, args.force, state)
    for note in notes:
        print(f"注意: {note}", file=sys.stderr)
    print(f"保存しました: 「{args.name}」（窓 {n} 枚）。呼び出すには: win set {shlex.quote(args.name)}")
    saved = load_sets()[args.name]
    print("  " + (set_summary(saved) if state else saved["run"]).replace("\n", "\n  "))     # 状態（URL など）は表示しない
    if any(parse_window_spec(t)[2] for t in shlex.split(saved["run"].replace("\n", " ")) if not t.startswith("!")):
        print(f"  ※ 状態（タブの URL・作業ディレクトリ）は {SETS} に平文で保存されました")
    return 0

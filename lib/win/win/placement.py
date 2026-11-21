"""型による配置（win layout）。"""

from concurrent.futures import ThreadPoolExecutor
import itertools
import json
import math
import os
import re
import shlex
import subprocess
import sys
import time

from .common import WinError
from .i18n import tr
from .screen import default_screen, find_screen, load_config
from .layouts import compute_rects, resolve_layout
from .shortcuts import WIN_BIN
from .dbus import WindowCalls, find_windows, focused, is_multi, normal_windows, usable_windows
from .store import launch_for_class, load_apps


def place(wc, wid, rect):
    wc.simple("Unminimize", wid) if wc.details(wid).get("minimized") else None
    wc.move_resize(wid, *rect)


def is_maximized(wc, wid):
    """最大化・全画面か。（要求より大きい窓が最小サイズのせいか、最大化に戻されたのかを見分ける）"""
    try:
        d = wc.details(wid)
    except WinError:
        return False
    return bool(d.get("maximized_horizontally") or d.get("maximized_vertically") or d.get("fullscreen"))


def place_settled(wc, wid, rect, tries=8):
    """窓を rect に置き、起動直後にアプリ自身が動かして元に戻る場合に備えて、定着するまで繰り返す。

    位置が合っていて、大きさが要求以上なら（最小サイズで縮まらないだけなので）それで確定する。
    返り値は None（ぴったり）か、実際の枠 (x, y, w, h)。
    """
    rect, got = tuple(rect), None
    for _ in range(tries):
        place(wc, wid, rect)
        seen_ok, moved = False, False
        for _ in range(6):                       # 0.3 秒待つあいだ、0.05 秒ごとに見る
            time.sleep(0.05)
            got = tuple(wc.rect(wid))
            if got == rect:
                seen_ok = True
            elif seen_ok:                        # いったん合ったのに、アプリ自身に動かされた（保存した大きさの復元など）: すぐ置き直す
                moved = True
                break
        if moved:
            continue
        if got[:2] != rect[:2]:
            # 最小サイズより小さい大きさを求めると、Mutter は大きさだけ直して位置を動かさない。位置だけ別に動かす
            wc.call("Move", "uii", wid, rect[0], rect[1])
            time.sleep(0.2)
            got = tuple(wc.rect(wid))
        if got == rect:
            return None
        if got[:2] == rect[:2] and got[2] >= rect[2] and got[3] >= rect[3] and not is_maximized(wc, wid):
            return got                           # 大きいのは最小サイズのせい（最大化に戻されたのなら、置き直す）
    return got


WATCH_SECONDS = 10.0


def watch_settled(wc, items, limit=WATCH_SECONDS):
    """置いた窓 items=[(窓の ID, 枠)] を limit 秒のあいだ見張り、アプリ自身に動かされたら置き直す（黙って行う）。

    起動直後のアプリは、前回の大きさの復元などで、置いたあとに遅れて大きさを変えることがある（遅れの長さは分からない）。
    見張るのは起動した窓だけ。最小サイズで縮まらないだけの枠（最大化は除く）は、place_settled と同じく確定として扱う。
    """
    end = time.time() + limit
    tried = {wid: 0.0 for wid, r in items}                   # 最後に置き直した時刻（失敗しても、間をあけて試し続ける）
    while time.time() < end:
        for wid, r in items:
            try:
                cur = tuple(wc.rect(wid))
                fine = cur == tuple(r) or (cur[:2] == tuple(r[:2]) and cur[2] >= r[2] and cur[3] >= r[3] and not is_maximized(wc, wid))
                if not fine and time.time() - tried[wid] >= 0.5:
                    place_settled(wc, wid, r, tries=6)
                    tried[wid] = time.time()
            except WinError:                                  # 窓が閉じられた
                continue
        time.sleep(0.1)


def spawn_watch(items):
    """watch_settled を別プロセスで始める（layout はすぐ返り、見張りだけが最大 WATCH_SECONDS 秒続く）。"""
    if not items:
        return
    lib = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = "import sys, json; sys.path.insert(0, sys.argv[1]); from win.placement import watch_settled; from win.dbus import WindowCalls; watch_settled(WindowCalls(), [(w, tuple(r)) for w, r in json.loads(sys.argv[2])])"
    subprocess.Popen([sys.executable, "-c", code, lib, json.dumps([[w, list(r)] for w, r in items])],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def raise_group(wc, windows, prefer=None):
    """配置した窓をすべて前面に出す（それ以前の重なりは無視する）。

    最後にフォーカスを持つのは、prefer（配置した窓の中にあれば）か、先頭のタイルの窓。
    prefer が配置した窓の中に無いときは、前面は配置した窓だけにして、prefer は上に出さない。
    """
    ids = [w["id"] for w in windows]
    if not ids:
        return
    for wid in reversed(ids):               # 先頭のタイルが最後（いちばん上）になる
        wc.simple("Activate", wid)
    if prefer in ids and prefer != ids[0]:
        wc.simple("Activate", prefer)


def verify(wc, wid, rect):
    """配置後の実際の枠を確かめる。最小サイズなどで合わないとき、その旨を返す。"""
    time.sleep(0.2)
    got = wc.rect(wid)
    return None if tuple(got) == tuple(rect) else got


def wait_new_window(wc, before, timeout, what):
    """before に無かった通常の窓が現れるまで待って返す。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        new = [w for w in normal_windows(wc) if w["id"] not in before]
        if new:
            time.sleep(0.08)    # 同時に出た窓があれば拾う程度に待つ。長く待つと、アプリが決めた位置（別のモニタのことも）に窓が見え続ける
            return [w for w in normal_windows(wc) if w["id"] not in before][-1]   # 移した後に大きさや位置を戻すアプリは、place_settled が確かめ直す
        time.sleep(0.03)
    raise WinError(tr("{0} 秒待っても新しい窓が現れませんでした: {1}").format(timeout, what))


# 引数なしで起動すると、起動中のとき新しい窓を作らず既存の窓を前面に出すだけのアプリ（2 回目の起動で窓が増えないのを実機で確認したもの）。
# ここは組み込みの既定。利用者は apps.toml の [app.コマンド名] new_window = ["--new-window"] で足す・上書きできる
NEW_WINDOW_APPS = {"ptyxis": ["--new-window"], "gnome-text-editor": ["--new-window"], "nautilus": ["--new-window"],
                   # Chrome は --new-window だけだと窓が出ない（URL があると出る。chrome://newtab でも出ないのを確認）ので about:blank を開く
                   "google-chrome-stable": ["--new-window", "about:blank"], "google-chrome": ["--new-window", "about:blank"]}


def new_window_args(name):
    """起動コマンド名に、新しい窓を作るために足す引数。apps.toml の指定が、組み込みの既定より優先する。"""
    mine = load_apps().get(name, {}).get("new_window")
    if mine is not None:
        if not isinstance(mine, list) or not all(isinstance(a, str) for a in mine):
            raise WinError(tr("apps.toml の [app.{0}] new_window は、文字列のリストにしてください").format(name))
        return list(mine)
    return list(NEW_WINDOW_APPS.get(name, []))


def launch(wc, cmdline, timeout=20):
    """コマンドを起動し、新しく現れた窓を返す。"""
    argv = shlex.split(cmdline)
    if not argv:
        raise WinError(tr("起動するコマンドが空です"))
    if argv[0] == "win":                                  # PATH に win が無い環境（ショートカットなど）でも動くように
        argv = [sys.executable, WIN_BIN] + argv[1:]
    if len(argv) == 1:                                    # 引数なしは、起動中なら既存の窓を前面にするだけで窓が増えない
        argv += new_window_args(os.path.basename(argv[0]))
    before = {w["id"] for w in normal_windows(wc)}
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        raise WinError(tr("起動できません: {0}: {1}").format(argv[0], e))
    try:
        return wait_new_window(wc, before, timeout, cmdline)
    except WinError as e:
        name = os.path.basename(argv[0])
        running = subprocess.run(["pgrep", "-x", name[:15]], capture_output=True).returncode == 0
        if running:
            raise WinError(tr("{0}\n  {1} はすでに起動中です。起動中のアプリは、新しい窓を作らず既存の窓を前面に出すだけのことがあります（新しい窓を作る引数が要るか確かめてください。例: ptyxis --new-window）").format(e, name))
        raise


def describe(w):
    return f"{w['id']} {w.get('wm_class')} 「{(w.get('title') or '')[:40]}」"


def grouped_ids(wc):
    """いずれかのグループに入っている窓の ID。グループがなければ（保存先がなければ）、保存先を読まずに空。"""
    from .groups import GROUPS_FILE, load_groups        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
    if not os.path.exists(GROUPS_FILE):
        return set()
    return {m["id"] for g in load_groups(wc).values() for m in g["members"]}


def parse_window_spec(sel):
    """窓の指定を (照合する語, 窓がなければ起動するか, 起動コマンド) に分ける。
    `クラス名?` ＝ なければ、アプリ一覧から探したコマンドで起動。`クラス名?コマンド` ＝ なければ、そのコマンドで起動。"""
    m = re.fullmatch(r"([\w.\-]+)\?(.*)", sel, re.S)
    if m:
        return m.group(1), True, m.group(2).strip()
    if sel.endswith("?") and len(sel) > 1:
        return sel[:-1], True, ""
    return sel, False, ""


def expand_multi(wc, sels, n):
    """窓の列の @visible・@class: などを、当たる窓の ID に広げる（ほかの指定のぶんを除いた、残りのタイルの数まで）。"""
    if not any(is_multi(x) for x in sels):
        return sels
    free = n - sum(1 for x in sels if not is_multi(x))
    out, used = [], set()
    pool = usable_windows(wc)
    for x in sels:                                        # 個別に指定した窓は、複数の指定から除く（同じ窓が 2 つのタイルに入らないように）
        if not is_multi(x) and x not in ("-", "_") and not x.startswith("!") and x.lower() != "@pick":
            hit = [w for w in find_windows(wc, parse_window_spec(x)[0], pool) if w["id"] not in used]
            if hit:
                used.add(hit[0]["id"])
    for x in sels:
        if not is_multi(x):
            out.append(x)
            continue
        got = [w for w in find_windows(wc, x) if w["id"] not in used][:max(0, free)]
        if not got:
            raise WinError(tr("窓が見つかりません: {0}").format(x))
        free -= len(got)
        used |= {w["id"] for w in got}
        out += [str(w["id"]) for w in got]
    return out


def cmd_layout(args):
    from .layoutflow import gui_interactive, gui_layout_flow        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
    from .tilepick import interactive
    wc = WindowCalls()
    cfg = load_config()
    gap = cfg["gap"] if args.gap is None else args.gap
    screen = find_screen(args.monitor) if getattr(args, "monitor", None) else default_screen()
    area = screen.work_area(cfg)
    if args.layout is None:
        return gui_layout_flow(wc, args, cfg, area, gap)
    expr = resolve_layout(cfg, args.layout)
    rects = compute_rects(expr, area, gap)
    n = len(rects)
    if args.interactive:
        return (interactive if args.text else gui_interactive)(wc, args, expr, rects, area)

    plan = [None] * n
    if args.windows:
        sels = [a for a in args.windows]
        rest = sels[-1] in ("...", "…")          # 末尾の ... は「残りは前面の窓から順に」
        if rest:
            sels = sels[:-1]
        sels = expand_multi(wc, sels, n)
        if len(sels) > n:
            raise WinError(tr("タイルは {0} 枚ですが、窓の指定が {1} 個あります").format(n, len(sels)))
        pool = usable_windows(wc)
        taken = set()
        seen_groups, grouped = {}, None
        for i, sel in enumerate(sels):                            # グループのメンバーは、ほかのタイルの窓として拾わない（指定の順に関係なく）
            if sel.lower().startswith("@group:"):
                from .groups import get_group        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
                gname = sel.split(":", 1)[1]
                if gname in seen_groups:
                    raise WinError(tr("グループ {0} は、タイル {1} とタイル {2} の両方には置けません").format(gname, seen_groups[gname], (i + 1)))
                seen_groups[gname] = i + 1
                try:
                    taken |= {m["id"] for m in get_group(wc, gname)["members"]}
                except WinError as e:
                    raise WinError(tr("タイル {0}: {1}").format((i + 1), e))
        for i, sel in enumerate(sels):
            if sel in ("-", "_"):
                continue
            if sel.startswith("!"):
                plan[i] = ("run", sel[1:])
                continue
            if sel.lower().startswith("@group:"):                     # グループ全体を、このタイルに置く
                from .groups import get_group        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
                try:
                    get_group(wc, sel.split(":", 1)[1])
                except WinError as e:
                    raise WinError(tr("タイル {0}: {1}").format((i + 1), e))
                plan[i] = ("group", sel.split(":", 1)[1])
                continue
            base, optional, fallback = parse_window_spec(sel)         # クラス名?＝窓がなければ起動、クラス名?コマンド＝そのコマンドで起動
            found = [w for w in find_windows(wc, base, pool) if w["id"] not in taken]
            if optional and found:                                    # 「なければ起動」の指定は、どのグループのメンバーも拾わない（グループは自分の窓を持つ）
                if grouped is None:
                    grouped = grouped_ids(wc)
                found = [w for w in found if w["id"] not in grouped]
            if not found and optional:
                cmdline = fallback or launch_for_class(base)
                if not cmdline:
                    raise WinError(tr("タイル {0}: 窓が見つからず、起動コマンドも分かりません: {1}").format((i + 1), base))
                plan[i] = ("run", cmdline)
                continue
            if not found:
                raise WinError(tr("タイル {0}: 窓が見つかりません: {1}").format((i + 1), sel))
            plan[i] = ("win", found[0])
            taken.add(found[0]["id"])
        # 同じ指定が複数のタイルにあるときは、各窓がいまある位置にいちばん近いタイルへ入れる
        # （前面の順で割り当てると、同じ命令を繰り返すたびに窓が入れ替わる）
        groups = {}
        for i, sel in enumerate(sels):
            if sel not in ("-", "_") and not sel.startswith("!"):
                groups.setdefault(parse_window_spec(sel)[0], []).append(i)
        for idxs in groups.values():
            idxs = [i for i in idxs if plan[i] is not None and plan[i][0] == "win"]
            if not 2 <= len(idxs) <= 6:
                continue
            wins = [plan[i][1] for i in idxs]
            center = lambda r: (r[0] + r[2] / 2, r[1] + r[3] / 2)
            now = {w["id"]: center(tuple(wc.rect(w["id"]))) for w in wins}
            best = min(itertools.permutations(wins),
                       key=lambda perm: sum(math.dist(now[w["id"]], center(rects[i])) for w, i in zip(perm, idxs)))
            for w, i in zip(best, idxs):
                plan[i] = ("win", w)
        if rest:
            others = [w for w in pool if w["id"] not in taken]
            for i in range(len(sels), n):
                if others:
                    plan[i] = ("win", others.pop(0))
    else:
        for i, w in enumerate(usable_windows(wc)[:n]):
            plan[i] = ("win", w)

    for i, (r, p) in enumerate(zip(rects, plan), 1):
        what = tr("（空）") if p is None else (tr("起動: {0}").format(p[1]) if p[0] == "run" else tr("グループ {0}").format(p[1]) if p[0] == "group" else describe(p[1]))
        print(tr("タイル {0}: x={1} y={2} {3}x{4}  ← {5}").format(i, r[0], r[1], r[2], r[3], what))
    if args.dry_run:
        return 0

    try:
        me = focused(wc)["id"]
    except WinError:
        me = None
    from .undo import begin        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
    ent = begin(wc, f"layout {args.layout}")                          # 動かす窓の、動かす前の状態（win undo で戻す）
    for p in plan:
        if p is not None and p[0] == "win":
            ent.add(wc, [p[1]])
        elif p is not None and p[0] == "group":
            from .groups import get_group        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
            ent.add(wc, [m["id"] for m in get_group(wc, p[1])["members"]])
    ent.commit()
    placed, results, settling, group_jobs, started = {}, [], [], [], set()
    with ThreadPoolExecutor(max_workers=max(1, n)) as pool:           # 置いたあとの定着待ち（窓ごとに 0.3 秒以上）は並行して行う
        for i, (r, p) in enumerate(zip(rects, plan), 1):
            if p is None:
                continue
            if p[0] == "group":                                       # グループは全メンバーを枠へ置く（前面に出すのは手前のメンバーだけ）
                from .groups import place_group_members        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
                group_jobs.append((i, r, pool.submit(place_group_members, wc, p[1], r)))
                continue
            w = launch(wc, p[1]) if p[0] == "run" else p[1]           # 起動は 1 つずつ（新しい窓の見分けが混ざらないように）
            if p[0] == "run":
                started.add(w["id"])
            settling.append(pool.submit(place_settled, wc, w["id"], r))
            placed[i] = w
            results.append((w["id"], r, i))
        for f in settling:
            f.result()
        for i, r, job in group_jobs:
            members, active, notes = job.result()
            placed[i] = active
            results.extend((m["id"], r, i) for m in members)
            for note in notes:
                print(tr("  注意: タイル {0}: {1}").format(i, note), file=sys.stderr)
    placed = [placed[i] for i in sorted(placed)]                      # タイルの順
    raise_group(wc, placed, me)
    # 前面に出したあとに、アプリ自身が大きさを戻すことがある（Firefox で 5px 足りなくなった例）。ずれた窓は、もう一度置き直す
    launched = any(p is not None and p[0] == "run" for p in plan)
    got_by = {}
    for delay in ((0.5, 1.5) if launched else (0.5,)):        # 起動した窓は、セッションの復元などで遅れて動くことがあるので、もう 1 回確認する
        time.sleep(delay)
        for wid, r, i in results:
            got_by[wid] = None if tuple(wc.rect(wid)) == tuple(r) else place_settled(wc, wid, r, tries=6)
    # それより遅れて動かすアプリのために、起動した窓だけ、あとで WATCH_SECONDS 秒見張る
    spawn_watch([(wid, r) for wid, r, i in results if wid in started])
    for wid, r, i in results:
        got = got_by.get(wid)
        if got:
            print(tr("  注意: タイル {0} の窓は希望の大きさにならず {1}x{2}@({3},{4}) です（最小サイズなど）").format(i, got[2], got[3], got[0], got[1]), file=sys.stderr)
    return 0


def apply_one(wc, wid, rect, index):
    got = place_settled(wc, wid, rect)
    if got:
        print(tr("  注意: タイル {0} の窓は希望の大きさにならず {1}x{2}@({3},{4}) です（最小サイズなど）").format(index, got[2], got[3], got[0], got[1]), file=sys.stderr)

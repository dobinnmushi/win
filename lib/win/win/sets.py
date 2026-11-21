"""セット（保存した窓の並び）。"""

import shlex
import subprocess
import sys

from .common import WinError
from .i18n import tr
from .screen import Screen, default_screen, display_state, find_screen, load_config, logical_rect, use_screen
from .layouts import compute_rects, resolve_layout
from .dbus import WindowCalls
from .store import check_win_line, describe_command, load_commands, load_sets, win_lines
from .placement import parse_window_spec


def is_set(c):
    """commands.toml に置かれていた頃のセットの印（移し替えにだけ使う）。"""
    return c.get("type") == "arrange" or c.get("kind") == "set"


def _layout_line(c):
    """セットの最初の layout 行を (型, [窓の指定…]) に分けて返す。なければ None。"""
    for line in win_lines(c.get("run", "")):
        try:
            argv = shlex.split(line)
        except ValueError:
            continue
        argv = argv[1:] if argv and argv[0] == "win" else argv
        if not argv or argv[0] != "layout":
            continue
        pos, skip = [], False
        for t in argv[1:]:
            if skip:
                skip = False
            elif t in ("--gap", "-m", "--monitor"):
                skip = True
            elif t.startswith("-") and t not in ("-", "_"):
                continue
            else:
                pos.append(t)
        return (pos[0], pos[1:]) if pos else None
    return None


def _spec_label(sel):
    if sel in ("-", "_", "...", "…"):
        return ""
    base = parse_window_spec(sel.lstrip("!"))[0] if not sel.startswith("!") else sel[1:].split()[0] if sel[1:].split() else ""
    return _short_cls(base)


def set_summary(c):
    """一覧に出す 1 行の説明（起動コマンドに含まれる URL などは出さない）。"""
    if c.get("type") == "arrange":
        return tr("窓 {0} 枚（旧形式）").format(len(c.get('windows', [])))
    parsed = _layout_line(c)
    if not parsed:
        return describe_command(c)
    expr, sels = parsed
    with_state = any(parse_window_spec(x)[2] for x in sels if not x.startswith("!"))
    return f"{expr}{tr('  ＋状態') if with_state else ''}  " + tr(" ・ ").join(_spec_label(x) or tr("（空）") for x in sels)      # 印は、長い行で省略されない先頭側に置く


def _short_cls(s):
    return s.rsplit(".", 1)[-1] if s else ""


def set_preview(c, cfg):
    """セットのプレビュー用のタイル [{x, y, w, h, label}]（作業領域を 0〜1 にした割合）。作れなければ空。"""
    tiles = []
    if c.get("type") == "arrange":
        for e in c.get("windows", []):
            x, y, w, h = (0, 0, 1, 1) if e.get("maximized") else e.get("rect", (0, 0, 1, 1))
            tiles.append({"x": x, "y": y, "w": w, "h": h, "label": _short_cls(e.get("cls", ""))})
        return tiles
    parsed = _layout_line(c)
    if not parsed:
        return []
    try:
        rects = compute_rects(resolve_layout(cfg, parsed[0]), (0, 0, 1000, 1000), 0)
    except WinError:
        return []
    sels = parsed[1]
    for i, (x, y, w, h) in enumerate(rects):
        tiles.append({"x": x / 1000, "y": y / 1000, "w": w / 1000, "h": h / 1000,
                      "label": _spec_label(sels[i]) if i < len(sels) else ""})
    return tiles


def monitors_for_preview(cfg, screen=None):
    """プレビューに描く各モニタ {"name", "rect", "work"} と、基準モニタ（screen。省くと既定）の添字。取れなければ ([], 0)。"""
    try:
        monitors, logical = display_state()
    except WinError:
        return [], 0
    base = (screen or default_screen()).rect
    out, cur = [], 0
    for lm in logical:
        rect = logical_rect(lm, monitors)
        if rect == base:
            cur = len(out)
        out.append({"name": lm[5][0][0], "rect": list(rect), "work": list(Screen(rect, lm[4]).work_area(cfg))})
    return out, cur


def next_monitor(mons, cur, d):
    """monitors_for_preview の一覧で、cur のモニタから見て左（d=-1）・右（d=1）にいちばん近いモニタの添字。なければ None。"""
    mx, my, mw, mh = mons[cur]["rect"]
    cx, cy = mx + mw / 2, my + mh / 2
    near = [(abs(m["rect"][0] + m["rect"][2] / 2 - cx) + abs(m["rect"][1] + m["rect"][3] / 2 - cy) / 4, n)
            for n, m in enumerate(mons) if n != cur and (m["rect"][0] + m["rect"][2] / 2 - cx) * d > 0]
    return min(near)[1] if near else None


def cmd_set(args):
    wc = WindowCalls()
    sets = load_sets()
    name = args.name
    if name is None:
        if not sets:
            raise WinError(tr("セットがありません（win save 名前 で、いまの窓の並びを保存できます）"))
        from .pickers import pick_set          # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
        name, monitor = pick_set(wc, load_config(), sets)
        if name is None:
            return 1
        if monitor:
            use_screen(find_screen(monitor))              # 小窓で選んだモニタを基準にして適用する（行に -m があればそちらが優先）
    elif name not in sets:
        if name in load_commands():
            raise WinError(tr("「{0}」はセットではありません（win run {1} で実行できます）").format(name, shlex.quote(name)))
        raise WinError(tr("セットが見つかりません: {0}（一覧は win set）").format(name))
    return run_entry(sets[name])


def cmd_run(args):
    cmds = load_commands()
    if not args.name:
        if not cmds:
            print(tr("登録されたコマンドはありません（win config で作れます。窓の並びは win save でセットに）"))
        for n, c in cmds.items():
            print(f"{n:<18} {c.get('type', 'win'):<8} {describe_command(c)}")
        return 0
    c = cmds.get(args.name)
    if c is None:
        c = load_sets().get(args.name)                        # 以前は run でセットも呼べたので、その呼び方も残す
    if c is None:
        raise WinError(tr("コマンドが見つかりません: {0}（一覧は win run、セットは win set）").format(args.name))
    return run_entry(c)


def run_entry(c):
    """登録したコマンドかセットを 1 つ実行する。"""
    from .cli import main        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
    from .appstate import run_arrangement        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
    t = c.get("type", "win")
    if t == "win":
        err = check_win_line(c.get("run", ""))
        if err:
            raise WinError(err)
        for line in win_lines(c["run"]):                  # 上から順に。失敗したらそこで止める
            argv = shlex.split(line)
            rc = main(argv[1:] if argv[0] == "win" else argv)
            if rc:
                return rc
        return 0
    if t == "shell":
        subprocess.Popen(["sh", "-c", c.get("run", "")], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return 0
    if t == "arrange":
        for note in run_arrangement(WindowCalls(), c):
            print(note, file=sys.stderr)
        return 0
    raise WinError(tr("知らない種類です: {0}").format(t))

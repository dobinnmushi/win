"""セット（保存した窓の並び）。"""

import gi
import json
import shlex
import subprocess
import sys
from gi.repository import Gio

from .common import SETPICK_APP_ID, WinError
from .screen import Screen, default_screen, display_state, find_screen, load_config, logical_rect, use_screen, work_area
from .layouts import compute_rects, resolve_layout
from .shortcuts import WIN_BIN
from .dbus import WindowCalls
from .store import check_win_line, describe_command, load_commands, load_sets, win_lines
from .pickwin import center_and_focus
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
        return f"窓 {len(c.get('windows', []))} 枚（旧形式）"
    parsed = _layout_line(c)
    if not parsed:
        return describe_command(c)
    expr, sels = parsed
    with_state = any(parse_window_spec(x)[2] for x in sels if not x.startswith("!"))
    return f"{expr}{'  ＋状態' if with_state else ''}  " + " ・ ".join(_spec_label(x) or "（空）" for x in sels)      # 印は、長い行で省略されない先頭側に置く


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


def pick_set(wc, cfg, sets):
    """名前で絞り込みながら、プレビューを見て選ぶ小窓。(選ばれたセットの名前, 選ばれたモニタの接続名)。取消は (None, None)。
    モニタが 1 枚なら接続名は None（基準のモニタのまま）。"""
    ax, ay, aw, ah = work_area(cfg)
    mons, cur = monitors_for_preview(cfg)
    spec = {"sets": [{"name": n, "summary": set_summary(c)[:90], "tiles": set_preview(c, cfg)} for n, c in sets.items()],
            "ratio": aw / ah, "monitors": mons, "current": cur}
    proc = subprocess.Popen([sys.executable, WIN_BIN, "_setpick"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    proc.stdin.write(json.dumps(spec))
    proc.stdin.close()
    center_and_focus(wc, proc, SETPICK_APP_ID)
    out = proc.stdout.read()
    proc.wait()
    for line in reversed(out.strip().splitlines()):
        try:
            res = json.loads(line)
        except ValueError:
            continue
        if res.get("act") == "set":
            return res.get("name"), res.get("monitor")
        return None, None
    return None, None


def run_setpick():
    """セットを選ぶ小窓。上に名前の入力欄（入力で絞り込み）、下に一覧、横にプレビュー。結果は 1 行の JSON で標準出力へ。"""
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    spec = json.load(sys.stdin)
    sets, ratio = spec["sets"], spec.get("ratio") or 1.6
    mons = spec.get("monitors") or [{"name": None, "rect": [0, 0, ratio * 1000, 1000], "work": [0, 0, ratio * 1000, 1000]}]
    bx, by = min(m["rect"][0] for m in mons), min(m["rect"][1] for m in mons)         # 全モニタを囲む枠
    bw, bh = max(m["rect"][0] + m["rect"][2] for m in mons) - bx, max(m["rect"][1] + m["rect"][3] for m in mons) - by
    k = min(340 / bw, 200 / bh)                         # 縦横比を保って 340x200 に収める
    PW, PH = max(120, round(bw * k)), max(60, round(bh * k))
    st = {"set": None, "mon": min(max(spec.get("current") or 0, 0), len(mons) - 1)}

    class App(Adw.Application):
        def __init__(self):
            super().__init__(application_id=SETPICK_APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)

        def finish(self, act):
            print(json.dumps(act), flush=True)
            self.quit()

        def do_activate(self):
            css = Gtk.CssProvider()
            css.load_from_string(".tile-box { border: 1px solid alpha(currentColor, .4); border-radius: 4px; "
                                 "background: alpha(@accent_bg_color, .18); font-size: 9pt; } "
                                 ".preview-frame { background: alpha(currentColor, .06); border-radius: 6px; } "
                                 ".screen-box { background: alpha(currentColor, .05); border: 1px solid alpha(currentColor, .18); "
                                 "border-radius: 3px; } "
                                 ".screen-box.cur { background: alpha(currentColor, .09); border: 2px solid alpha(@accent_bg_color, .9); }")
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            entry = Gtk.Entry(hexpand=True, placeholder_text="セットの名前で絞り込み…")
            listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.BROWSE, can_focus=False, activate_on_single_click=True)
            listbox.add_css_class("boxed-list")
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=listbox, vexpand=True, hexpand=True,
                                        min_content_height=260)
            scroll.set_size_request(330, -1)
            preview = Gtk.Fixed()
            preview.set_size_request(PW, PH)
            frame = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.START, margin_top=2)
            frame.add_css_class("preview-frame")
            frame.append(preview)
            caption = Gtk.Label(wrap=True, xalign=0, max_width_chars=44, margin_top=8)
            caption.add_css_class("dim-label")
            side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.START, hexpand=False)
            side.append(frame)
            side.append(caption)
            shown = []                                    # 表示中の行 → sets の添字

            def draw(i=-1):
                if i != -1:
                    st["set"] = i
                i = st["set"]
                while (c := preview.get_first_child()) is not None:
                    preview.remove(c)
                for n, m in enumerate(mons):                   # 画面全体を薄く描き、適用先のモニタだけ強調する
                    mx, my, mw, mh = m["rect"]
                    box = Gtk.Box()
                    box.add_css_class("screen-box")
                    if n == st["mon"]:
                        box.add_css_class("cur")
                    box.set_size_request(max(4, round(mw * k)), max(4, round(mh * k)))
                    preview.put(box, round((mx - bx) * k), round((my - by) * k))
                if i is None:
                    caption.set_label("")
                    return
                wx, wy, ww, wh = mons[st["mon"]]["work"]      # タイルの座標は作業領域に対する割合
                tiles = sets[i]["tiles"]
                for t in tiles:
                    lab = Gtk.Label(label=t["label"], ellipsize=3, max_width_chars=10)
                    lab.add_css_class("tile-box")
                    lab.set_size_request(max(8, round(t["w"] * ww * k) - 2), max(8, round(t["h"] * wh * k) - 2))
                    preview.put(lab, round((wx + t["x"] * ww - bx) * k) + 1, round((wy + t["y"] * wh - by) * k) + 1)
                where = f"適用先: {mons[st['mon']]['name']}\n" if len(mons) > 1 else ""
                caption.set_label(where + (sets[i]["summary"] if tiles else "プレビューを作れません: " + sets[i]["summary"]))

            def move_mon(d):
                """いまのモニタから見て、左（d=-1）・右（d=1）にいちばん近いモニタへ。なければそのまま（並び順ではなく実際の位置）。"""
                def center(m):
                    return m["rect"][0] + m["rect"][2] / 2, m["rect"][1] + m["rect"][3] / 2
                cx, cy = center(mons[st["mon"]])
                side = [(abs(center(m)[0] - cx) + abs(center(m)[1] - cy) / 4, n) for n, m in enumerate(mons)
                        if n != st["mon"] and (center(m)[0] - cx) * d > 0]
                if side:
                    st["mon"] = min(side)[1]
                    draw()

            def refresh(*_):
                while (r := listbox.get_row_at_index(0)) is not None:
                    listbox.remove(r)
                words = entry.get_text().lower().split()
                shown[:] = [i for i, st in enumerate(sets) if all(w in (st["name"] + " " + st["summary"]).lower() for w in words)]
                for i in shown:
                    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)
                    name = Gtk.Label(label=sets[i]["name"], xalign=0)
                    name.add_css_class("heading")
                    sub = Gtk.Label(label=sets[i]["summary"], xalign=0, ellipsize=3, max_width_chars=40)
                    sub.add_css_class("dim-label")
                    sub.add_css_class("caption")
                    box.append(name)
                    box.append(sub)
                    listbox.append(Gtk.ListBoxRow(child=box))
                if shown:
                    listbox.select_row(listbox.get_row_at_index(0))
                else:
                    draw(None)
                    caption.set_label("一致するセットがありません")

            def move(d):
                if shown:
                    sel = listbox.get_selected_row()
                    row = listbox.get_row_at_index(max(0, min(len(shown) - 1, (sel.get_index() if sel else 0) + d)))
                    listbox.select_row(row)
                    row.grab_focus()
                    entry.grab_focus_without_selecting()

            def decide():
                sel = listbox.get_selected_row()
                if sel is not None:
                    self.finish({"act": "set", "name": sets[shown[sel.get_index()]]["name"],
                                 "monitor": mons[st["mon"]]["name"] if len(mons) > 1 else None})

            listbox.connect("row-selected", lambda _l, r: draw(shown[r.get_index()]) if r is not None else None)
            listbox.connect("row-activated", lambda _l, _r: decide())
            entry.connect("changed", refresh)
            entry.connect("activate", lambda _e: decide())

            def on_key(_c, keyval, _kc, state):
                name = Gdk.keyval_name(keyval)
                ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
                if name == "Escape":
                    self.finish({"act": "cancel"})
                elif name in ("Down", "Tab") or (ctrl and name in ("n", "j")):
                    move(1)
                elif name in ("Up", "ISO_Left_Tab") or (ctrl and name in ("p", "k")):
                    move(-1)
                elif name in ("Left", "Right") and len(mons) > 1 and not (state & ~Gdk.ModifierType.LOCK_MASK):
                    move_mon(1 if name == "Right" else -1)
                else:
                    return False
                return True

            body = Gtk.Box(spacing=14, margin_start=12, margin_end=12)
            body.append(scroll)
            body.append(side)
            top = Gtk.Box(margin_top=10, margin_start=12, margin_end=12, margin_bottom=8)
            top.append(entry)
            hint = Gtk.Label(label="入力で絞り込み ・ ↑↓ で選ぶ" + (" ・ ←→ でモニタを選ぶ" if len(mons) > 1 else "")
                             + " ・ Enter で適用 ・ Esc で閉じる", margin_top=8, margin_bottom=10)
            hint.add_css_class("dim-label")
            hint.add_css_class("caption")
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            for w in (top, body, hint):
                outer.append(w)
            header = Adw.HeaderBar(title_widget=Gtk.Label(label="セットを選ぶ"), show_end_title_buttons=False)
            view = Adw.ToolbarView(content=outer)
            view.add_top_bar(header)
            win = Adw.ApplicationWindow(application=self, title="win-setpick", default_width=780, content=view)
            ctrl = Gtk.EventControllerKey()
            ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            ctrl.connect("key-pressed", on_key)
            win.add_controller(ctrl)
            win.connect("close-request", lambda _w: (self.finish({"act": "cancel"}), True)[1])
            refresh()
            win.present()
            entry.grab_focus_without_selecting()

    App().run([])


def cmd_set(args):
    wc = WindowCalls()
    sets = load_sets()
    name = args.name
    if name is None:
        if not sets:
            raise WinError("セットがありません（win save 名前 で、いまの窓の並びを保存できます）")
        name, monitor = pick_set(wc, load_config(), sets)
        if name is None:
            return 1
        if monitor:
            use_screen(find_screen(monitor))              # 小窓で選んだモニタを基準にして適用する（行に -m があればそちらが優先）
    elif name not in sets:
        if name in load_commands():
            raise WinError(f"「{name}」はセットではありません（win run {shlex.quote(name)} で実行できます）")
        raise WinError(f"セットが見つかりません: {name}（一覧は win set）")
    return run_entry(sets[name])


def cmd_run(args):
    cmds = load_commands()
    if not args.name:
        if not cmds:
            print("登録されたコマンドはありません（win config で作れます。窓の並びは win save でセットに）")
        for n, c in cmds.items():
            print(f"{n:<18} {c.get('type', 'win'):<8} {describe_command(c)}")
        return 0
    c = cmds.get(args.name)
    if c is None:
        c = load_sets().get(args.name)                        # 以前は run でセットも呼べたので、その呼び方も残す
    if c is None:
        raise WinError(f"コマンドが見つかりません: {args.name}（一覧は win run、セットは win set）")
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
    raise WinError(f"知らない種類です: {t}")

"""汎用の小窓の描画側（_tilepick）と、その部品（絞り込み・アプリの一覧・起動）、端末での対話（interactive）。"""

import gi
import json
import os
import re
import shlex
import subprocess
import sys
from gi.repository import GLib
from gi.repository import Gio

from .common import CURRENT_FILE, GioUnix, TILEPICK_APP_ID, TILE_APP_ID, WinError
from .i18n import tr
from .screen import load_config
from .shortcuts import WIN_BIN
from .dbus import find_windows, focused, normal_windows, selector_for, usable_windows
from .store import icon_widget
from .pickwin import ask_line
from .placement import apply_one, describe, launch, raise_group
from .textui import ascii_map, set_current, start_placeholders, stop_placeholders
from .sets import monitors_for_preview
from .prompt import run_with_ascii_input
from .appstate import current_tiles, tile_order


def fuzzy(query, text, subseq=True):
    """query の各語（空白区切り）がすべて text に含まれれば点数、そうでなければ None。

    連続した部分文字列 > 語頭 > 飛び飛びの部分列 の順に高い点を付ける（subseq=False なら部分列は不一致）。
    """
    low, total = text.lower(), 0
    for term in query.lower().split():
        i = low.find(term)
        if i >= 0:
            total += 100 - min(i, 50) + (20 if i == 0 or low[i - 1] in " -_./(" else 0)
            continue
        if not subseq:
            return None
        pos, gaps = -1, 0
        for ch in term:
            j = low.find(ch, pos + 1)
            if j < 0:
                return None
            gaps += (j - pos - 1) if pos >= 0 else 0
            pos = j
        total += max(1, 50 - gaps)
    return total


def tile_candidates(text, windows, apps):
    """入力文字列に対する候補。先頭が ! ならアプリ（と、コマンドとして実行）、そうでなければ窓。

    戻り値は (モード, [{"act": 動作, "title": ..., "sub": ..., "icon": ...}])。
    同点なら元の順（窓は前面が先）を保つ。
    """
    if text.startswith("!"):
        q = text[1:].strip()
        scored = []
        for k, a in enumerate(apps):
            sc = 0
            if q:
                sc = fuzzy(q, a["name"])                      # 名前は飛び飛びの一致も許す
                if sc is None:                                # 説明・ID は連続一致だけ（雑音を避ける）
                    sc = fuzzy(q, f"{a['desc']} {a['id']}", subseq=False)
                    sc = None if sc is None else sc - 40
            if sc is not None:
                scored.append((-sc, k, a))
        scored.sort(key=lambda t: (t[0], t[1]))
        rows = [{"act": {"act": "app", "id": a["id"]}, "title": a["name"], "sub": a["desc"], "icon": a["icon"]}
                for _, _, a in scored[:60]]
        if q:
            rows.append({"act": {"act": "cmd", "text": q}, "title": tr("コマンドとして実行: {0}").format(q), "sub": "",
                         "icon": "utilities-terminal-symbolic"})
        return "app", rows
    q = text.strip()
    scored = []
    for k, w in enumerate(windows):
        sc = fuzzy(q, f"{w['cls']} {w['title']}") if q else 0
        if sc is not None:
            scored.append((-sc, k, w))
    scored.sort(key=lambda t: (t[0], t[1]))
    return "win", [{"act": {"act": "win", "id": w["id"]}, "title": w["title"] or w["cls"], "sub": w["cls"],
                    "icon": w.get("icon", "")} for _, _, w in scored]


def list_apps():
    apps = []
    for a in Gio.AppInfo.get_all():
        if not a.should_show():
            continue
        icon = a.get_icon()
        desc = getattr(a, "get_generic_name", lambda: None)() or a.get_description() or ""
        apps.append({"id": a.get_id(), "name": a.get_name(), "desc": desc, "icon": icon.to_string() if icon else ""})
    apps.sort(key=lambda a: a["name"].lower())
    return apps


def app_commandline(info):
    return re.sub(r"\s*%[a-zA-Z%]", "", info.get_commandline() or "").strip()


def launch_app(wc, app_id, timeout=12):
    """アプリを起動し、新しく現れた窓と起動コマンドを返す。"""
    info = (GioUnix.DesktopAppInfo if GioUnix else Gio.DesktopAppInfo).new(app_id)
    if info is None:
        raise WinError(tr("アプリが見つかりません: {0}").format(app_id))
    cmdline = app_commandline(info)
    return launch(wc, cmdline, timeout), cmdline






def screen_info(screen=None):
    """ミニ地図に描く、全モニタ {"monitors": [{"name", "rect", "work"}…], "current": 基準モニタの添字}。取れなければ None。"""
    mons, cur = monitors_for_preview(load_config(), screen)
    return {"monitors": mons, "current": cur} if mons else None


def spawn_tilepick(screen=None):
    """絞り込みの小窓（_tilepick）を起動する。画面の位置は環境変数で渡す（ミニ地図に全モニタを薄く描くため）。"""
    env = dict(os.environ)
    info = screen_info(screen)
    if info:
        env["WIN_SCREEN"] = json.dumps(info)
    return subprocess.Popen([sys.executable, WIN_BIN, "_tilepick"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, bufsize=1, env=env)


def run_tilepick():
    """汎用の小窓（dialog.Dialog の描画側）。親と 1 行 1 JSON でやり取りする。
    親→子: show（全体を描いて入力を待つ）・patch（渡した項目だけ更新）・busy・quit。
    子→親: select・key・text・app/cmd・none（行がないまま Tab）・cancel は返信を待つ。highlight・edit は返信を待たない通知。"""
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk, Pango

    MAP_W, MAP_H = 300, 150
    scr = None                                    # 全モニタを囲む枠 bbox と各モニタ monitors（name・rect・work。画面の座標）。無ければ作業領域だけの地図
    cur_mon = 0
    try:
        info = json.loads(os.environ.get("WIN_SCREEN") or "null")
        if info and info["monitors"]:
            mons = info["monitors"]
            bx, by = min(m["rect"][0] for m in mons), min(m["rect"][1] for m in mons)
            bw, bh = max(m["rect"][0] + m["rect"][2] for m in mons) - bx, max(m["rect"][1] + m["rect"][3] for m in mons) - by
            k = min(MAP_W / bw, MAP_H / bh)             # 縦横比を保って 300x150 に収める
            MAP_W, MAP_H = max(60, round(bw * k)), max(30, round(bh * k))
            scr = {"bbox": (bx, by, bw, bh), "monitors": mons}
            cur_mon = min(max(info.get("current") or 0, 0), len(mons) - 1)
    except (ValueError, KeyError, TypeError):
        scr = None
    st = {"apps": [], "rows": [], "busy": True, "mon": cur_mon, "dlg": {}, "free": [], "keep_selection": None, "applying": False}

    class App(Adw.Application):
        def __init__(self):
            super().__init__(application_id=TILEPICK_APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)

        # -- 親への返信
        def reply(self, act):
            if st["busy"]:
                return
            st["busy"] = True
            self.entry.set_sensitive(False)
            print(json.dumps(act, ensure_ascii=False), flush=True)
            if act.get("act") == "cancel":
                self.quit()

        # -- 画面の更新
        def set_notice(self, text):
            self.notice.set_text(text or "")
            self.notice.set_visible(bool(text))

        def draw_map(self, rects, cur, labels):
            child = self.map.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                self.map.remove(child)
                child = nxt
            if scr:
                bx, by, bw, bh = scr["bbox"]
                for n, m in enumerate(scr["monitors"]):          # 画面全体を薄く描く（タイルはその上）。並べる先のモニタだけ強調
                    mx, my, mw, mh = m["rect"]
                    mon = Gtk.Box()
                    mon.add_css_class("screen-box")
                    if n == st["mon"] and len(scr["monitors"]) > 1:
                        mon.add_css_class("cur")
                    mon.set_size_request(max(4, round(mw / bw * MAP_W)), max(4, round(mh / bh * MAP_H)))
                    self.map.put(mon, round((mx - bx) / bw * MAP_W), round((my - by) / bh * MAP_H))
                wx, wy, ww, wh = scr["monitors"][st["mon"]]["work"]    # タイルの座標は作業領域に対する割合なので、地図全体に対する割合へ直す
                rects = [((wx + x * ww - bx) / bw, (wy + y * wh - by) / bh, w * ww / bw, h * wh / bh)
                         for x, y, w, h in rects]
            for i, (x, y, w, h) in enumerate(rects):
                label = labels[i] if labels and i < len(labels) else ""
                lab = Gtk.Label(label=f"{i + 1}" + (f"\n{label}" if label else ""), ellipsize=Pango.EllipsizeMode.END,
                                max_width_chars=1, justify=Gtk.Justification.CENTER)
                lab.add_css_class("tile-box")
                if st["free"] and i < len(st["free"]) and st["free"][i]:
                    lab.add_css_class("free")
                if i == cur:
                    lab.add_css_class("cur")
                elif label:
                    lab.add_css_class("done")
                lab.set_size_request(max(8, int(w * MAP_W) - 2), max(8, int(h * MAP_H) - 2))
                self.map.put(lab, int(x * MAP_W) + 1, int(y * MAP_H) + 1)

        def on_row_selected(self, _lb, row):
            if row is not None and st["dlg"].get("highlight") and 0 <= row.get_index() < len(st["rows"]):
                act = st["rows"][row.get_index()]["act"]
                if act.get("act") == "select":                # 選択が動いたことを親へ知らせる（返信を待たない）
                    print(json.dumps({"act": "highlight", "index": act["index"]}), flush=True)

        def populate(self):
            d, text = st["dlg"], self.entry.get_text()
            if d.get("launch") and text.startswith("!"):
                _mode, rows = tile_candidates(text, [], st["apps"])
                self.chip.set_text(tr("アプリを新規起動"))
            else:
                q, scored = text.strip(), []
                for i, r in enumerate(d.get("rows") or []):
                    sc = fuzzy(q, f"{r['title']} {r.get('sub', '')}") if q and d.get("filter", True) else 0
                    if sc is not None:
                        scored.append((-sc, i, r))
                scored.sort(key=lambda t: (t[0], t[1]))
                rows = [{"act": {"act": "select", "index": i}, "title": r["title"], "sub": r.get("sub", ""),
                         **({"icon": r["icon"]} if r.get("icon") else {}),
                         **({"num": k + 1} if d.get("numbers") and k < 9 else {})} for k, (_, i, r) in enumerate(scored)]
                self.chip.set_text(d.get("chip") or tr("選ぶ"))
            st["rows"] = rows
            while (r := self.listbox.get_row_at_index(0)) is not None:
                self.listbox.remove(r)
            for r in rows:
                box = Gtk.Box(spacing=10, margin_top=5, margin_bottom=5, margin_start=10, margin_end=10)
                if d.get("numbers"):                           # 1〜9 の数字キーで直接選べる行の番号
                    num = Gtk.Label(label=str(r.get("num", "")), width_chars=2, xalign=1)
                    num.add_css_class("dim-label")
                    box.append(num)
                if "icon" in r:
                    box.append(icon_widget(Gtk, Gdk, r["icon"]))
                title = Gtk.Label(label=r["title"], xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                                  max_width_chars=44)
                sub = Gtk.Label(label=r["sub"], xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=22)
                sub.add_css_class("dim-label")
                box.append(title)
                box.append(sub)
                row = Gtk.ListBoxRow(can_focus=False)
                row.set_child(box)
                self.listbox.append(row)
            if not rows:
                self.listbox.append(Gtk.ListBoxRow(can_focus=False, selectable=False, child=Gtk.Label(
                    label=d.get("empty") or tr("一致する項目がありません"), margin_top=14, margin_bottom=14)))
            else:
                keep = st["keep_selection"]
                self.listbox.select_row(self.listbox.get_row_at_index(min(keep, len(rows) - 1) if keep is not None else 0))
            self.scroller.get_vadjustment().set_value(0)

        def move(self, d):
            if not st["rows"]:
                return
            sel = self.listbox.get_selected_row()
            self.select_index((sel.get_index() if sel else 0) + d)

        def select_index(self, i):
            rows = st["rows"]
            if not rows:
                return
            i = max(0, min(len(rows) - 1, i))
            row = self.listbox.get_row_at_index(i)
            self.listbox.select_row(row)
            adj, a = self.scroller.get_vadjustment(), row.get_allocation()
            if a.y < adj.get_value():
                adj.set_value(a.y)
            elif a.y + a.height > adj.get_value() + adj.get_page_size():
                adj.set_value(a.y + a.height - adj.get_page_size())

        def choose(self, rest):
            row = self.listbox.get_selected_row()
            if row is None or not st["rows"]:
                if st["dlg"].get("ask"):                      # 文字を入力する画面: Enter でその文字を返す
                    self.reply({"act": "text", "text": self.entry.get_text()})
                elif rest:
                    self.reply({"act": "none", "via": "tab"})  # 行がないまま Tab
                return
            act = dict(st["rows"][row.get_index()]["act"])
            act["via"] = "tab" if rest else "enter"            # どのキーで決めたか
            self.reply(act)

        def vim_key(self, name):
            """一覧だけの画面（vim: 入力欄なし）のキー: j/k・g/G・l（決定）・h/q（取消）・1〜9（その行を直接）。扱ったら True。"""
            if name in ("j", "n"):
                self.move(1)
            elif name in ("k", "p"):
                self.move(-1)
            elif name in ("g", "Home"):
                self.select_index(0)
            elif name in ("G", "End"):
                self.select_index(len(st["rows"]) - 1)
            elif name == "l":
                self.choose(False)
            elif name in ("h", "q"):
                self.reply({"act": "cancel"})
            elif name and len(name) == 1 and name in "123456789" and int(name) <= len(st["rows"]):
                self.select_index(int(name) - 1)
                self.choose(False)
            else:
                return False
            return True

        # -- 親からの命令
        def on_message(self, m):
            c = m.get("cmd")
            if c in ("show", "patch"):
                # show は全体を描き直して入力を待つ。patch は渡した項目だけ更新する（返信を待たない通知への応答）
                d = st["dlg"] = {**st["dlg"], **m} if c == "patch" else m
                self.title_lab.set_text(d.get("title") or "")
                self.title_lab.set_visible(bool(d.get("title")))
                self.header_lab.set_label(d.get("window_title") or "win")
                self.hint.set_text(d.get("hint") or "")
                self.entry.set_placeholder_text(d.get("placeholder") or "")
                self.entry.set_visible(d.get("entry", True))
                self.chip.set_visible(d.get("entry", True))
                self.scroller.set_visible(d.get("list", True))
                mp = d.get("map")
                st["free"] = (mp or {}).get("free") or []
                if mp and mp.get("mon") is not None:
                    st["mon"] = mp["mon"]
                self.map.set_visible(bool(mp))
                if mp:
                    self.draw_map(mp["rects"], mp.get("index", -1), mp.get("labels"))
                if "apps" in m:
                    st["apps"] = m["apps"]
                self.set_notice(d.get("notice"))
                if c == "show":
                    sel = self.listbox.get_selected_row()
                    st["keep_selection"] = sel.get_index() if (d.get("keep_selection") and sel is not None) else None
                    st["busy"] = False
                    self.entry.set_sensitive(True)
                    if m.get("text") is not None:
                        st["applying"] = True                  # 親が置き換えた文字は、入力の変化として知らせない
                        self.entry.set_text(m["text"])
                        st["applying"] = False
                    self.populate()
                    self.entry.grab_focus_without_selecting()
                elif "rows" in m:
                    self.populate()
            elif c == "busy":
                st["busy"] = True
                self.entry.set_sensitive(False)
                self.set_notice(m.get("text"))
            elif c == "quit":
                self.quit()

        def got_line(self, stream, res):
            try:
                line, _ = stream.read_line_finish_utf8(res)
            except GLib.Error:
                line = None
            if line is None:
                self.quit()
                return
            if line.strip():
                self.on_message(json.loads(line))
            stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self.got_line)

        def on_entry_changed(self, _e):
            d = st["dlg"]
            if st["busy"] or st["applying"]:
                return
            if d.get("watch"):                                # 入力が変わったことを親へ知らせる（返信を待たない）
                print(json.dumps({"act": "edit", "text": self.entry.get_text()}, ensure_ascii=False), flush=True)
            if d.get("filter", True) or d.get("launch"):
                self.populate()

        def do_activate(self):
            css = Gtk.CssProvider()
            css.load_from_string(
                ".tile-box { border: 1px solid alpha(currentColor, .35); border-radius: 4px; font-size: 8pt; }"
                ".screen-box { background: alpha(currentColor, .05); border: 1px solid alpha(currentColor, .18); border-radius: 3px; }"
                ".screen-box.cur { background: alpha(currentColor, .09); border: 2px solid alpha(@accent_bg_color, .9); }"
                ".tile-box.cur { background: @accent_bg_color; color: @accent_fg_color; border-color: @accent_bg_color; }"
                ".tile-box.done { background: alpha(currentColor, .12); }"
                ".tile-box.free { border-style: dashed; }"
                ".mode-chip { padding: 2px 10px; border-radius: 12px; background: alpha(currentColor, .12); font-size: 9pt; }")
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.title_lab = Gtk.Label(xalign=0, margin_start=14, margin_top=10)
            self.title_lab.add_css_class("heading")
            self.map = Gtk.Fixed(halign=Gtk.Align.CENTER, margin_top=8, margin_bottom=6)
            self.map.set_size_request(MAP_W, MAP_H)
            self.chip = Gtk.Label()
            self.chip.add_css_class("mode-chip")
            self.entry = Gtk.Entry(hexpand=True)
            self.entry.set_sensitive(False)
            row = Gtk.Box(spacing=8, margin_start=12, margin_end=12)
            row.append(self.chip)
            row.append(self.entry)
            self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.BROWSE, can_focus=False)
            self.listbox.add_css_class("boxed-list")
            self.listbox.connect("row-activated", lambda _lb, _r: self.choose(False))
            self.listbox.connect("row-selected", self.on_row_selected)
            self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=self.listbox,
                                               min_content_height=300, max_content_height=300,
                                               margin_top=8, margin_start=12, margin_end=12)
            self.notice = Gtk.Label(xalign=0, wrap=True, margin_top=6, margin_start=14, margin_end=14, visible=False)
            self.notice.add_css_class("error")
            hint = self.hint = Gtk.Label(margin_top=8, margin_bottom=10)
            hint.add_css_class("dim-label")
            hint.add_css_class("caption")
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            for wdg in (self.title_lab, self.map, row, self.scroller, self.notice, hint):
                outer.append(wdg)
            self.header_lab = Gtk.Label(label="win")
            header = Adw.HeaderBar(title_widget=self.header_lab, show_end_title_buttons=False)
            view = Adw.ToolbarView(content=outer)
            view.add_top_bar(header)
            win = Adw.ApplicationWindow(application=self, title="win-tilepick", default_width=720, content=view)

            def on_key(_c, keyval, _kc, state_mask):
                name = Gdk.keyval_name(keyval)
                ctrl = bool(state_mask & Gdk.ModifierType.CONTROL_MASK)
                combo = ("Ctrl+" if ctrl else "") + (name or "")
                d = st["dlg"]
                if name == "Escape":
                    self.reply({"act": "cancel"})
                elif d.get("vim") and not ctrl and self.vim_key(name):
                    pass
                elif combo in (d.get("keys") or []) and not (state_mask & (Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK)):
                    self.reply({"act": "key", "key": combo})   # 親が受け取りたいと言ったキーは、親へ渡す
                elif name == "Down" or (ctrl and name in ("n", "j")):
                    self.move(1)
                elif name == "Up" or (ctrl and name in ("p", "k")):
                    self.move(-1)
                elif name in ("Return", "KP_Enter"):
                    self.choose(False)
                elif name in ("Tab", "ISO_Left_Tab"):
                    self.choose(True)
                elif ctrl and name == "u":
                    self.entry.set_text("")
                else:
                    return False
                return True

            ctrl = Gtk.EventControllerKey()
            ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            ctrl.connect("key-pressed", on_key)
            win.add_controller(ctrl)
            self.entry.connect("changed", self.on_entry_changed)
            win.connect("close-request", lambda _w: (self.reply({"act": "cancel"}), self.quit(), True)[2])
            win.present()
            unix = (GioUnix.InputStream if GioUnix else Gio.UnixInputStream).new(0, False)
            stream = Gio.DataInputStream.new(unix)
            stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self.got_line)

    run_with_ascii_input(lambda: App().run([]))


def slot_map(wc, n=None, screen=None):
    """いまの並び（逆算）の、小窓の地図用のタイル（0〜1 の割合）と、各タイルの窓のクラス名。"""
    cfg = load_config()
    cur = current_tiles(wc, cfg, screen)
    if cur["tree"] is None:
        return None, None
    order = tile_order(cur, cfg)[1]
    box = {it[0]: it[1:5] for it in cur["items"]}
    rects = [(box[i][0], box[i][1], box[i][2] - box[i][0], box[i][3] - box[i][1]) for i in order]
    labels = [(cur["by_id"][i].get("wm_class") or "")[:14] for i in order]
    return rects, labels


def interactive(wc, args, expr, rects, area):
    n = len(rects)
    me = focused(wc)
    assigned = [None] * n      # (window, recipe) か None
    labels = [""] * n
    procs = [] if args.no_preview else start_placeholders(wc, rects)
    wc.simple("Activate", me["id"])
    print(tr("型 {0}（{1}）: タイル {2} 枚").format(args.layout, expr, n))
    print(tr("入力: 窓の番号 / 検索語（既存の窓）/ !コマンド（新しく起動）/ p 一覧から選ぶ / 空行（空けておく）/ < 戻る / q 終了"))
    i = 0
    try:
        while i < n:
            set_current(i + 1)
            print("\n" + ascii_map(rects, area, i, labels))
            taken = {a[0]["id"] for a in assigned if a}
            pool = [w for w in usable_windows(wc) if w["id"] not in taken]
            for k, w in enumerate(pool, 1):
                mark = tr("（このターミナル）") if w["id"] == me["id"] else ""
                print(f"  {k:>2}  {w.get('wm_class')}  「{(w.get('title') or '')[:40]}」{mark}")
            try:
                line = ask_line(wc, pool, i, n, args.pick)
            except EOFError:
                line = "q"
            if line == "q":
                break
            if line == "<":
                if i > 0:
                    i -= 1
                    assigned[i], labels[i] = None, ""
                continue
            if line == "":
                i += 1
                continue
            try:
                if line.startswith("!"):
                    w = launch(wc, line[1:].strip())
                    recipe = "!" + line[1:].strip()
                elif line.isdigit() and 1 <= int(line) <= len(pool):
                    w = pool[int(line) - 1]
                    recipe = selector_for(w, normal_windows(wc))
                else:
                    found = find_windows(wc, line, pool)
                    if not found:
                        print(tr("  見つかりません: {0}").format(line))
                        continue
                    if len(found) > 1:
                        print(tr("  {0} 件に一致しました。番号で選んでください:").format(len(found)))
                        for w in found:
                            print(f"    {pool.index(w) + 1:>2}  {describe(w)}")
                        continue
                    w = found[0]
                    recipe = selector_for(w, normal_windows(wc))
            except WinError as e:
                print(f"  {e}")
                continue
            apply_one(wc, w["id"], rects[i], i + 1)
            wc.simple("Activate", me["id"])
            assigned[i] = (w, recipe)
            labels[i] = (w.get("wm_class") or "")[:20]
            i += 1
    except KeyboardInterrupt:
        print(tr("\n中断しました（ここまでの配置は残ります）"))
    finally:
        stop_placeholders(procs)
        try:
            raise_group(wc, [a[0] for a in assigned if a], me["id"])
        except WinError:
            pass
    toks = [shlex.quote(a[1]) if a else "-" for a in assigned]
    while toks and toks[-1] == "-":
        toks.pop()
    print(tr("\n同じ配置を再現するコマンド:"))
    print("  win layout " + shlex.quote(args.layout) + (" " + " ".join(toks) if toks else ""))
    return 0


def run_tile(idx, total):
    """対話モードで各タイルの位置に出す、番号つきの目印の窓。"""
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    parent = os.getppid()

    class App(Adw.Application):
        def __init__(self):
            super().__init__(application_id=TILE_APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)

        def do_activate(self):
            css = Gtk.CssProvider()
            css.load_from_string(
                ".tile-num { font-size: 96pt; font-weight: 800; opacity: .35; }"
                ".tile-cur { background: @accent_bg_color; }"
                ".tile-cur .tile-num { opacity: .9; color: @accent_fg_color; }")
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            box = Gtk.Box()
            label = Gtk.Label(label=str(idx), hexpand=True, vexpand=True)
            label.add_css_class("tile-num")
            box.append(label)
            win = Adw.ApplicationWindow(application=self, title=f"win-tile {idx}",
                                        default_width=240, default_height=160, content=box)

            def tick():
                if os.getppid() != parent:
                    self.quit()
                    return False
                try:
                    cur = int(open(CURRENT_FILE).read().strip())
                except (OSError, ValueError):
                    cur = 0
                (box.add_css_class if cur == idx else box.remove_css_class)("tile-cur")
                return True

            GLib.timeout_add(200, tick)
            win.present()

    App().run([])

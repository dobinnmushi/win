"""絞り込みで選ぶ小窓（win layout の対話・pick_interactive）。"""

import contextlib
import gi
import json
import os
import re
import shlex
import subprocess
import sys
import time
from gi.repository import GLib
from gi.repository import Gio

from .common import CURRENT_FILE, GioUnix, TILEPICK_APP_ID, TILE_APP_ID, WinError
from .screen import find_screen, load_config
from .layouts import compute_rects, is_shorthand_layout, resolve_layout
from .shortcuts import WIN_BIN
from .dbus import find_windows, focused, normal_windows, selector_for, usable_windows
from .store import icon_for_class, icon_widget
from .pickwin import ask_line, center_and_focus
from .placement import apply_one, cmd_layout, describe, launch, place_settled, raise_group
from .textui import ascii_map, set_current, start_placeholders, stop_placeholders
from .sets import monitors_for_preview
from .prompt import run_with_ascii_input, save_history
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
            rows.append({"act": {"act": "cmd", "text": q}, "title": f"コマンドとして実行: {q}", "sub": "",
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


def layout_candidates(text, items):
    """型の選択画面の候補。items は [{"name", "expr", "n", "rects"}]。式（v( h( full）を直接打つこともできる。"""
    q = text.strip()
    scored = []
    for k, it in enumerate(items):
        sc = fuzzy(q, f"{it['name']} {it['expr']}") if q else 0
        if sc is not None:
            scored.append((-sc, k, it))
    scored.sort(key=lambda t: (t[0], t[1]))
    rows = [{"act": {"act": "layout", "name": it["name"]}, "title": it["name"],
             "sub": f"{it['expr']}　{it['n']}枚", "icon": None, "rects": it["rects"]} for _, _, it in scored]
    if re.match(r"(full|[vh]\s*\()", q) or is_shorthand_layout(q):        # 略記（1,2,2 や 1/1 など）も式として使える
        rows.append({"act": {"act": "layout", "name": q}, "title": f"式として使う: {q}", "sub": "", "icon": None,
                     "rects": []})
    return rows


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
        raise WinError(f"アプリが見つかりません: {app_id}")
    cmdline = app_commandline(info)
    return launch(wc, cmdline, timeout), cmdline


TILE_PLACEHOLDER = "文字で絞り込み　先頭に ! でアプリを探して新規起動"


TILE_HINT = "↑↓ 選択 ・ Enter 決定 ・ Tab 決定して残りを自動 ・ Ctrl+S 空ける ・ Ctrl+B 戻る ・ Esc 終了"


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
    """タイルごとに窓（先頭 ! でアプリ）を絞り込んで選ぶ小窓。親と 1 行 1 JSON でやり取りする。"""
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk, Pango

    MAP_W, MAP_H = 300, 150
    scr = None                                    # 全モニタを囲む枠 bbox と各モニタ monitors（name・rect・work。画面の座標）。無ければ従来どおり作業領域だけの地図
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
    st = {"windows": [], "apps": [], "rows": [], "busy": True, "stage": "tile", "layouts": [], "mon": cur_mon}

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
                label = labels[i] if labels else ""
                lab = Gtk.Label(label=f"{i + 1}" + (f"\n{label}" if label else ""), ellipsize=Pango.EllipsizeMode.END,
                                max_width_chars=1, justify=Gtk.Justification.CENTER)
                lab.add_css_class("tile-box")
                if st.get("free") and i < len(st["free"]) and st["free"][i]:
                    lab.add_css_class("free")
                if i == cur:
                    lab.add_css_class("cur")
                elif label:
                    lab.add_css_class("done")
                lab.set_size_request(max(8, int(w * MAP_W) - 2), max(8, int(h * MAP_H) - 2))
                self.map.put(lab, int(x * MAP_W) + 1, int(y * MAP_H) + 1)

        def set_tile(self, m):
            self.title_lab.set_text(m.get("title") or f"タイル {m['index'] + 1} / {m['n']}　{m['layout']}")
            self.draw_map(m["rects"], m["index"], m["labels"])

        def on_row_selected(self, _lb, row):
            if st["stage"] == "layout" and row is not None and 0 <= row.get_index() < len(st["rows"]):
                self.draw_map(st["rows"][row.get_index()].get("rects", []), -1, None)
            elif st["stage"] == "dialog" and row is not None and st["dlg"].get("highlight") and 0 <= row.get_index() < len(st["rows"]):
                act = st["rows"][row.get_index()]["act"]
                if act.get("act") == "select":                # 選択が動いたことを親へ知らせる（返信を待たない）
                    print(json.dumps({"act": "highlight", "index": act["index"]}), flush=True)

        def populate(self):
            if st["stage"] == "layout":
                rows = layout_candidates(self.entry.get_text(), st["layouts"])
                self.chip.set_text("型")
            elif st["stage"] == "dialog":                     # 汎用の画面（dialog.Dialog）: 親が渡した行を、入力で絞り込む
                d, text = st["dlg"], self.entry.get_text()
                if d.get("launch") and text.startswith("!"):
                    _mode, rows = tile_candidates(text, [], st["apps"])
                    self.chip.set_text("アプリを新規起動")
                else:
                    q, scored = text.strip(), []
                    for i, r in enumerate(d.get("rows") or []):
                        sc = fuzzy(q, f"{r['title']} {r.get('sub', '')}") if q and d.get("filter", True) else 0
                        if sc is not None:
                            scored.append((-sc, i, r))
                    scored.sort(key=lambda t: (t[0], t[1]))
                    rows = [{"act": {"act": "select", "index": i}, "title": r["title"], "sub": r.get("sub", ""),
                             **({"icon": r["icon"]} if r.get("icon") else {})} for _, i, r in scored]
                    self.chip.set_text(d.get("chip") or "選ぶ")
            else:
                mode, rows = tile_candidates(self.entry.get_text(), st["windows"], st["apps"])
                self.chip.set_text("アプリを新規起動" if mode == "app" else "開いている窓")
            st["rows"] = rows
            while (r := self.listbox.get_row_at_index(0)) is not None:
                self.listbox.remove(r)
            for r in rows:
                box = Gtk.Box(spacing=10, margin_top=5, margin_bottom=5, margin_start=10, margin_end=10)
                if "icon" in r:                               # 窓・アプリの行（型の行には出さない）
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
                    label=("一致する型がありません" if st["stage"] == "layout"
                           else (st["dlg"].get("empty") or "一致する項目がありません") if st["stage"] == "dialog"
                           else "一致する窓がありません（先頭に ! でアプリを探す）"), margin_top=14, margin_bottom=14)))
            else:
                keep = st.get("keep_selection")
                self.listbox.select_row(self.listbox.get_row_at_index(min(keep, len(rows) - 1) if keep is not None else 0))
            self.scroller.get_vadjustment().set_value(0)

        def move(self, d):
            rows = st["rows"]
            if not rows:
                return
            sel = self.listbox.get_selected_row()
            i = max(0, min(len(rows) - 1, (sel.get_index() if sel else 0) + d))
            row = self.listbox.get_row_at_index(i)
            self.listbox.select_row(row)
            adj, a = self.scroller.get_vadjustment(), row.get_allocation()
            if a.y < adj.get_value():
                adj.set_value(a.y)
            elif a.y + a.height > adj.get_value() + adj.get_page_size():
                adj.set_value(a.y + a.height - adj.get_page_size())

        def choose(self, rest):
            row = self.listbox.get_selected_row()
            if st["stage"] == "dialog":
                if row is None or not st["rows"]:
                    if st["dlg"].get("ask"):                  # 文字を入力する画面: Enter でその文字を返す
                        self.reply({"act": "text", "text": self.entry.get_text()})
                    return
                act = dict(st["rows"][row.get_index()]["act"])
                act["via"] = "tab" if rest else "enter"        # どのキーで決めたか
                self.reply(act)
                return
            if row is None or not st["rows"]:
                if rest:
                    self.reply({"act": "none", "rest": True})
                return
            act = dict(st["rows"][row.get_index()]["act"])
            if rest:
                act["rest"] = True
            if st["stage"] == "layout" and self.multi_mon():
                act["monitor"] = scr["monitors"][st["mon"]]["name"]       # 並べる先のモニタ
            self.reply(act)

        def multi_mon(self):
            return bool(scr) and len(scr["monitors"]) > 1

        def layout_title(self):
            return "型を選ぶ" + (f"（並べる先: {scr['monitors'][st['mon']]['name']}）" if self.multi_mon() else "")

        def move_mon(self, d):
            """いまのモニタから見て、左（d=-1）・右（d=1）にいちばん近いモニタへ（並び順ではなく実際の位置）。なければそのまま。"""
            def center(m):
                return m["rect"][0] + m["rect"][2] / 2, m["rect"][1] + m["rect"][3] / 2
            mons = scr["monitors"]
            cx, cy = center(mons[st["mon"]])
            side = [(abs(center(m)[0] - cx) + abs(center(m)[1] - cy) / 4, n) for n, m in enumerate(mons)
                    if n != st["mon"] and (center(m)[0] - cx) * d > 0]
            if side:
                st["mon"] = min(side)[1]
                self.title_lab.set_text(self.layout_title())
                self.on_row_selected(None, self.listbox.get_selected_row())

        # -- 親からの命令
        def on_message(self, m):
            c = m.get("cmd")
            if c == "layouts":
                st["stage"], st["layouts"] = "layout", m["items"]
                self.title_lab.set_text(self.layout_title())
                self.entry.set_placeholder_text("型の名前で絞り込み（式も打てます: 1,2,2・1/1・v(1,h(1,1)) など）")
                self.hint.set_text("↑↓ 選択（ミニ地図が変わる）" + (" ・ ←→ 並べる先のモニタ" if self.multi_mon() else "")
                                   + " ・ Enter 決定してタイルごとに選ぶ ・ Tab 決定して前面の窓で自動配置 ・ Esc 閉じる")
                self.set_notice(m.get("notice"))
                st["busy"] = False
                self.entry.set_sensitive(True)
                self.entry.set_text("")
                self.populate()
                self.entry.grab_focus_without_selecting()
            elif c == "tile":
                st["stage"] = "tile"
                self.entry.set_placeholder_text(m.get("placeholder") or TILE_PLACEHOLDER)
                self.hint.set_text(m.get("hint") or TILE_HINT)
                st["windows"] = m["windows"]
                st["free"] = m.get("free") or []              # 空きスペースのタイル（点線で描く）
                st["keep_selection"] = None
                self.map.set_visible(True)
                self.entry.set_visible(True)
                self.chip.set_visible(True)
                self.scroller.set_visible(True)
                if m.get("mon") is not None:
                    st["mon"] = m["mon"]
                if "apps" in m:
                    st["apps"] = m["apps"]
                self.set_tile(m)
                self.set_notice(m.get("notice"))
                st["busy"] = False
                self.entry.set_sensitive(True)
                self.entry.set_text("")
                self.populate()
                self.entry.grab_focus_without_selecting()
            elif c in ("show", "patch"):
                # 汎用の画面（dialog.Dialog）。show は全体を描き直して入力を待つ。patch は渡した項目だけ更新する（返信を待たない通知への応答）
                d = st["dlg"] = {**st.get("dlg", {}), **m} if c == "patch" else m
                st["stage"] = "dialog"
                self.title_lab.set_text(d.get("title") or "")
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
                        self.entry.set_text(m["text"])
                    self.populate()
                    self.entry.grab_focus_without_selecting()
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
            self.entry = Gtk.Entry(hexpand=True, placeholder_text=TILE_PLACEHOLDER)
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
            hint = self.hint = Gtk.Label(margin_top=8, margin_bottom=10, label=TILE_HINT)
            hint.add_css_class("dim-label")
            hint.add_css_class("caption")
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            for wdg in (self.title_lab, self.map, row, self.scroller, self.notice, hint):
                outer.append(wdg)
            self.header_lab = Gtk.Label(label="窓を並べる")
            header = Adw.HeaderBar(title_widget=self.header_lab, show_end_title_buttons=False)
            view = Adw.ToolbarView(content=outer)
            view.add_top_bar(header)
            win = Adw.ApplicationWindow(application=self, title="win-tilepick", default_width=720, content=view)

            def on_key(_c, keyval, _kc, state_mask):
                name = Gdk.keyval_name(keyval)
                ctrl = bool(state_mask & Gdk.ModifierType.CONTROL_MASK)
                combo = ("Ctrl+" if ctrl else "") + (name or "")
                if name == "Escape":
                    self.reply({"act": "cancel"})
                elif st["stage"] == "dialog" and combo in (st["dlg"].get("keys") or []) \
                        and not (state_mask & (Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK)):
                    self.reply({"act": "key", "key": combo})   # 親が受け取りたいと言ったキーは、親へ渡す
                elif name == "Down" or (ctrl and name in ("n", "j")):
                    self.move(1)
                elif name == "Up" or (ctrl and name in ("p", "k")):
                    self.move(-1)
                elif name in ("Left", "Right") and st["stage"] == "layout" and self.multi_mon() \
                        and not (state_mask & ~Gdk.ModifierType.LOCK_MASK):
                    self.move_mon(1 if name == "Right" else -1)
                elif name in ("Return", "KP_Enter"):
                    self.choose(False)
                elif name in ("Tab", "ISO_Left_Tab"):
                    self.choose(True)
                elif ctrl and name == "s" and st["stage"] == "tile":
                    self.reply({"act": "skip"})
                elif ctrl and name == "b" and st["stage"] == "tile":
                    self.reply({"act": "back"})
                elif ctrl and name == "u":
                    self.entry.set_text("")
                else:
                    return False
                return True

            ctrl = Gtk.EventControllerKey()
            ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            ctrl.connect("key-pressed", on_key)
            win.add_controller(ctrl)
            self.entry.connect("changed", lambda _e: self.populate() if not st["busy"] else None)
            win.connect("close-request", lambda _w: (self.reply({"act": "cancel"}), self.quit(), True)[2])
            win.present()
            unix = (GioUnix.InputStream if GioUnix else Gio.UnixInputStream).new(0, False)
            stream = Gio.DataInputStream.new(unix)
            stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self.got_line)

    run_with_ascii_input(lambda: App().run([]))


PICK_HINT = "↑↓ 選択 ・ Enter 決定 ・ 先頭 ! でアプリを探して新しく起動 ・ Esc 取り消す"


def pick_interactive(wc, title="窓を選ぶ", rects=None, index=0, labels=None, allow_launch=True, exclude=()):
    """layout -i と同じ小窓で窓を 1 枚選ぶ（先頭 ! でアプリを起動して、その窓）。選んだ窓、取り消しなら None。
    rects（作業領域を 0〜1 にした (x, y, 幅, 高さ) のリスト）と index を渡すと、小窓の地図でそのタイルを強調する。"""
    if rects is None:                                     # 地図には、いまの並び（どこに何があるか）を出す。強調はしない
        rects, labels = slot_map(wc)
        index = -1
    rects = rects or [(0.0, 0.0, 1.0, 1.0)]
    exclude = set(exclude)
    child = spawn_tilepick()

    def send(msg):
        child.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        child.stdin.flush()

    def msg(notice="", first=False):
        m = {"cmd": "tile", "index": index, "n": len(rects), "layout": "", "rects": rects, "notice": notice,
             "labels": labels or [""] * len(rects), "title": title,
             "hint": PICK_HINT if allow_launch else "↑↓ 選択 ・ Enter 決定 ・ Esc 取り消す",
             "placeholder": TILE_PLACEHOLDER if allow_launch else "文字で絞り込み",
             "windows": [{"id": w["id"], "cls": w.get("wm_class") or "", "title": (w.get("title") or "")[:90],
                           "icon": icon_for_class(w.get("wm_class"))}
                         for w in usable_windows(wc) if w["id"] not in exclude]}
        if first:
            m["apps"] = list_apps() if allow_launch else []
        return m

    wid = None
    try:
        send(msg(first=True))
        wid = center_and_focus(wc, child, TILEPICK_APP_ID)
        while True:
            line = child.stdout.readline()
            try:
                res = json.loads(line) if line else {"act": "cancel"}
            except ValueError:
                res = {"act": "cancel"}
            act = res.get("act")
            if act == "cancel":
                return None
            try:
                if act == "win":
                    w = next((x for x in normal_windows(wc) if x["id"] == res["id"]), None)
                    if w is None:
                        raise WinError("その窓はもう閉じられました")
                    return w
                if act in ("app", "cmd") and not allow_launch:
                    raise WinError("ここでは新しく起動できません。開いている窓から選んでください")
                if act in ("app", "cmd"):
                    send({"cmd": "busy", "text": "起動しています…"})
                    return launch_app(wc, res["id"])[0] if act == "app" else launch(wc, res["text"], 12)
            except WinError as e:
                send(msg(str(e)))
            else:
                send(msg())                               # 空ける・戻る などは、1 枚選ぶときは使わない
            if wid:
                with contextlib.suppress(WinError):
                    wc.simple("Activate", wid)
    finally:
        with contextlib.suppress(OSError, ValueError):
            send({"cmd": "quit"})
        try:
            child.wait(3)
        except subprocess.TimeoutExpired:
            child.kill()


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


def gui_layout_flow(wc, args, cfg, area, gap):
    """型の名前なしで呼ばれたとき: 小窓で型を選び、Enter ならタイルごとの選択へ、Tab なら前面の窓で自動配置。"""
    if args.windows or args.dry_run:
        raise WinError("型を省くときは、窓の指定や -n は使えません")
    ax, ay, aw, ah = area
    items = []
    for name, expr in cfg["layouts"].items():
        r = compute_rects(expr, area, 0)
        items.append({"name": name, "expr": expr, "n": len(r),
                      "rects": [((x - ax) / aw, (y - ay) / ah, w / aw, h / ah) for x, y, w, h in r]})
    child = spawn_tilepick()

    def send(msg):
        child.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        child.stdin.flush()

    def close_child():
        try:
            send({"cmd": "quit"})
        except (OSError, ValueError):
            pass
        try:
            child.wait(3)
        except subprocess.TimeoutExpired:
            child.kill()

    handed_over = False
    try:
        send({"cmd": "layouts", "items": items})
        wid = center_and_focus(wc, child, TILEPICK_APP_ID)
        while True:
            line = child.stdout.readline()
            try:
                res = json.loads(line) if line else {"act": "cancel"}
            except ValueError:
                res = {"act": "cancel"}
            if res.get("act") != "layout":
                return 0
            expr = resolve_layout(cfg, res["name"])
            if res.get("monitor"):                       # 小窓で選んだモニタを基準にして並べる（全体の既定は変えず、args で持ち回る）
                args.monitor = res["monitor"]
                area = find_screen(args.monitor).work_area(cfg)
            try:
                rects = compute_rects(expr, area, gap)
            except WinError as e:
                send({"cmd": "layouts", "items": items, "notice": str(e)})
                wc.simple("Activate", wid)
                continue
            args.layout = res["name"]
            if res.get("rest"):
                close_child()
                time.sleep(0.3)                      # 小窓が閉じて、元の窓にフォーカスが戻るのを待つ
                args.interactive, args.windows = False, []
                return cmd_layout(args)
            handed_over = True
            return gui_interactive(wc, args, expr, rects, area, child, [wid])
    finally:
        if not handed_over:
            close_child()


def gui_interactive(wc, args, expr, rects, area, child=None, child_wid=None):
    n = len(rects)
    ax, ay, aw, ah = area
    norm = [((x - ax) / aw, (y - ay) / ah, w / aw, h / ah) for x, y, w, h in rects]
    try:
        me = focused(wc)["id"]
    except WinError:
        me = None
    assigned = [None] * n                    # (窓, 再現用の指定) か None
    procs = start_placeholders(wc, rects) if args.preview else []
    reuse = child is not None                # 型の選択画面から引き継いだ小窓
    if not reuse:
        child = spawn_tilepick()
        child_wid = [None]

    def send(msg):
        child.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        child.stdin.flush()

    def refocus():
        if child_wid[0]:
            try:
                wc.simple("Activate", child_wid[0])
            except WinError:
                pass

    def tile_msg(i, notice="", first=False):
        taken = {a[0]["id"] for a in assigned if a}
        msg = {"cmd": "tile", "index": i, "n": n, "layout": args.layout, "rects": norm, "notice": notice,
               "labels": [(a[0].get("wm_class") or "")[:14] if a else "" for a in assigned],
               "windows": [{"id": w["id"], "cls": w.get("wm_class") or "", "title": (w.get("title") or "")[:90],
                           "icon": icon_for_class(w.get("wm_class"))}
                           for w in usable_windows(wc) if w["id"] not in taken]}
        if first:
            msg["apps"] = list_apps()
        return msg

    def read_reply():
        line = child.stdout.readline()
        if not line:
            return {"act": "cancel"}
        try:
            return json.loads(line)
        except ValueError:
            return {"act": "cancel"}

    def place_checked(w, i):
        got = place_settled(wc, w["id"], rects[i])
        return (f"タイル {i + 1} の窓は希望の大きさにならず {got[2]}x{got[3]} です（最小サイズなど）" if got else "")

    i, notice, auto_from = 0, "", None
    try:
        send(tile_msg(i, first=True))
        if not reuse:
            child_wid[0] = center_and_focus(wc, child, TILEPICK_APP_ID)
        while True:
            res = read_reply()
            act, notice = res.get("act"), ""
            if act == "cancel":
                break
            chosen = None
            try:
                if act == "win":
                    w = next((x for x in normal_windows(wc) if x["id"] == res["id"]), None)
                    if w is None:
                        raise WinError("その窓はもう閉じられました")
                    chosen = (w, selector_for(w, normal_windows(wc)))
                elif act in ("app", "cmd"):
                    send({"cmd": "busy", "text": "起動しています…"})
                    if act == "app":
                        w, cmdline = launch_app(wc, res["id"])
                    else:
                        w, cmdline = launch(wc, res["text"], 12), res["text"]
                    chosen = (w, "!" + cmdline)
                elif act == "skip":
                    i += 1
                elif act == "back":
                    i = max(0, i - 1)
                    assigned[i] = None
            except WinError as e:
                notice = str(e)
                send(tile_msg(i, notice))
                refocus()
                continue
            if chosen:
                notice = place_checked(chosen[0], i)
                assigned[i] = chosen
                i += 1
            if res.get("rest"):
                auto_from = i
                taken = {a[0]["id"] for a in assigned if a}
                others = [w for w in usable_windows(wc) if w["id"] not in taken]
                for j in range(i, n):
                    if not others:
                        break
                    w = others.pop(0)
                    place_checked(w, j)
                    assigned[j] = (w, selector_for(w, normal_windows(wc)))
                break
            if i >= n:
                break
            send(tile_msg(i, notice))
            refocus()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            send({"cmd": "quit"})
        except (OSError, ValueError):
            pass
        try:
            child.wait(3)
        except subprocess.TimeoutExpired:
            child.kill()
        stop_placeholders(procs)
        try:
            raise_group(wc, [a[0] for a in assigned if a], me)
        except WinError:
            pass
    explicit = assigned[:auto_from] if auto_from is not None else assigned
    toks = [shlex.quote(a[1]) if a else "-" for a in explicit]
    while toks and toks[-1] == "-":
        toks.pop()
    if auto_from is not None:
        toks.append("...")
    if toks:
        recipe = "layout " + shlex.quote(args.layout) + " " + " ".join(toks)
        if getattr(args, "monitor", None):
            recipe += " -m " + shlex.quote(args.monitor)
        print("同じ配置を再現するコマンド:\n  win " + recipe)
        save_history(recipe)
    return 0


def interactive(wc, args, expr, rects, area):
    n = len(rects)
    me = focused(wc)
    assigned = [None] * n      # (window, recipe) か None
    labels = [""] * n
    procs = [] if args.no_preview else start_placeholders(wc, rects)
    wc.simple("Activate", me["id"])
    print(f"型 {args.layout}（{expr}）: タイル {n} 枚")
    print("入力: 窓の番号 / 検索語（既存の窓）/ !コマンド（新しく起動）/ p 一覧から選ぶ / 空行（空けておく）/ < 戻る / q 終了")
    i = 0
    try:
        while i < n:
            set_current(i + 1)
            print("\n" + ascii_map(rects, area, i, labels))
            taken = {a[0]["id"] for a in assigned if a}
            pool = [w for w in usable_windows(wc) if w["id"] not in taken]
            for k, w in enumerate(pool, 1):
                mark = "（このターミナル）" if w["id"] == me["id"] else ""
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
                        print(f"  見つかりません: {line}")
                        continue
                    if len(found) > 1:
                        print(f"  {len(found)} 件に一致しました。番号で選んでください:")
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
        print("\n中断しました（ここまでの配置は残ります）")
    finally:
        stop_placeholders(procs)
        try:
            raise_group(wc, [a[0] for a in assigned if a], me["id"])
        except WinError:
            pass
    toks = [shlex.quote(a[1]) if a else "-" for a in assigned]
    while toks and toks[-1] == "-":
        toks.pop()
    print("\n同じ配置を再現するコマンド:")
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

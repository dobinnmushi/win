"""窓の一覧から選ぶ小窓（win pick）。"""

import gi
import json
import subprocess
import sys
import time
from gi.repository import Gio

from .common import PICK_APP_ID
from .screen import load_config, work_area
from .shortcuts import WIN_BIN
from .store import icon_for_class, icon_widget


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


def pick_window(wc, windows, extras, title="窓を選ぶ"):
    """窓の一覧を小さく出し、選ばれた行の動作 {"act": ...} を返す（取消は None）。"""
    rows = [{"cls": w.get("wm_class") or "", "title": row_title(w, wc.details(w["id"])),
             "icon": icon_for_class(w.get("wm_class")), "act": {"act": "win", "id": w["id"]}} for w in windows]
    rows += [{"cls": "", "title": label, "act": {"act": act}} for act, label in extras]
    if not rows:
        return None
    proc = subprocess.Popen([sys.executable, WIN_BIN, "_pick"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    proc.stdin.write(json.dumps({"title": title, "rows": rows}))
    proc.stdin.close()
    center_and_focus(wc, proc, PICK_APP_ID)
    out = proc.stdout.read()
    proc.wait()
    for line in reversed(out.strip().splitlines()):
        try:
            res = json.loads(line)
        except ValueError:
            continue
        return None if res.get("act") == "cancel" else res
    return None


def line_from_picker(wc, pool):
    """一覧の選択を、対話モードの入力文字列に直す（取消は None）。"""
    res = pick_window(wc, pool, [("cmd", "コマンドを入力して新しく起動…"),
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


def run_pick():
    """一覧を出して、j/k・矢印で動き、Enter で決める小さな窓。結果は 1 行の JSON で標準出力へ。"""
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    spec = json.load(sys.stdin)
    rows_spec = spec["rows"]

    class App(Adw.Application):
        def __init__(self):
            super().__init__(application_id=PICK_APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)

        def finish(self, act):
            print(json.dumps(act), flush=True)
            self.quit()

        def do_activate(self):
            listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.BROWSE, activate_on_single_click=True)
            listbox.add_css_class("boxed-list")
            rows = []
            for k, r in enumerate(rows_spec, 1):
                box = Gtk.Box(spacing=12, margin_top=7, margin_bottom=7, margin_start=12, margin_end=12)
                num = Gtk.Label(label=str(k) if k <= 9 else "", width_chars=2, xalign=1)
                num.add_css_class("dim-label")
                cls = Gtk.Label(label=r["cls"], xalign=0, width_chars=16, max_width_chars=16,
                                ellipsize=3)
                cls.add_css_class("dim-label")
                title = Gtk.Label(label=r["title"], xalign=0, hexpand=True, ellipsize=3, max_width_chars=48)
                parts = (num, icon_widget(Gtk, Gdk, r["icon"]), cls, title) if "icon" in r else (num, cls, title)
                for wdg in parts:
                    box.append(wdg)
                row = Gtk.ListBoxRow()
                row.set_child(box)
                listbox.append(row)
                rows.append(row)

            def select(i):
                i = max(0, min(len(rows) - 1, i))
                listbox.select_row(rows[i])
                rows[i].grab_focus()

            def current():
                sel = listbox.get_selected_row()
                return sel.get_index() if sel else 0

            def on_key(_ctrl, keyval, _keycode, state):
                name = Gdk.keyval_name(keyval)
                if name in ("j", "Down", "n"):
                    select(current() + 1)
                elif name in ("k", "Up", "p"):
                    select(current() - 1)
                elif name in ("g", "Home"):
                    select(0)
                elif name in ("G", "End"):
                    select(len(rows) - 1)
                elif name in ("Return", "KP_Enter", "l"):
                    self.finish(rows_spec[current()]["act"])
                elif name in ("Escape", "q", "h"):
                    self.finish({"act": "cancel"})
                elif name and len(name) == 1 and name in "123456789" and int(name) <= len(rows):
                    self.finish(rows_spec[int(name) - 1]["act"])
                else:
                    return False
                return True

            listbox.connect("row-activated", lambda _lb, row: self.finish(rows_spec[row.get_index()]["act"]))
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                        max_content_height=440, child=listbox, margin_top=6, margin_bottom=6,
                                        margin_start=8, margin_end=8)
            hint = Gtk.Label(label="j/k ↑↓ 移動 ・ Enter/l 決定 ・ 1–9 直接 ・ Esc/q/h 取消", margin_bottom=8)
            hint.add_css_class("dim-label")
            hint.add_css_class("caption")
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            outer.append(scroll)
            outer.append(hint)
            header = Adw.HeaderBar(title_widget=Gtk.Label(label=spec["title"]), show_end_title_buttons=False)
            view = Adw.ToolbarView(content=outer)
            view.add_top_bar(header)
            win = Adw.ApplicationWindow(application=self, title="win-pick", default_width=620, content=view)
            ctrl = Gtk.EventControllerKey()
            ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            ctrl.connect("key-pressed", on_key)
            win.add_controller(ctrl)
            win.connect("close-request", lambda _w: (self.finish({"act": "cancel"}), True)[1])
            win.present()
            select(0)

    App().run([])

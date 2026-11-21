"""設定の窓（win config）。"""

import gi
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import tomllib
from gi.repository import GLib
from gi.repository import Gio

from .common import BUILTIN_LAYOUTS, CONFIG, DEFAULT_INSETS, NameExistsError, WinError
from .i18n import tr
from .screen import load_config
from .layouts import compute_rects
from .shortcuts import ACTION_GROUPS, G_CMD, G_MOVE, G_OTHER, G_SET, JP_KEYS, WIN_ACTIONS, WIN_BIN, accel_conflicts, accel_label, accel_norm, accel_note, accel_parse, command_slug, ext_slug, kb_list, kb_remove, kb_set, scan_accelerators, set_slug
from .dbus import WindowCalls, normal_windows, selector_for
from .store import SETS, check_win_line, describe_command, load_commands, load_sets, save_commands, save_sets, signature_markup, win_lines, write_toml
from .sets import set_summary
from .prompt import ibus_engine, suggest
from .appstate import save_arrangement
from .ext import EXT, EXT_DIR, EXT_ERRORS, EXT_TEMPLATE, _error_line, builtin_commands, ext_spec, reload_extensions, write_ext_support


CONFIG_APP_ID = "local.win.config"


# 拡張のソースを開くエディタ。$VISUAL → $EDITOR → nvim の順（引数つきの指定も可。例: "nvim -p"）。
# 窓で開く（端末を使わない）エディタ。これ以外は端末のエディタとして、Ptyxis の窓の中で開く。
GUI_EDITORS = {"code", "codium", "gnome-text-editor", "gedit", "kate", "subl", "zed", "xed", "pluma", "mousepad"}
LINE_PLUS_EDITORS = {"nvim", "vim", "vi", "view", "nano", "emacs", "micro"}       # 「+行 ファイル」で行へ飛べる


def editor_argv(path, line):
    """拡張のソース path を、line 行目で開くエディタの起動コマンドと、窓で開くエディタか（端末が要らないか）。"""
    try:
        cmd = shlex.split(os.environ.get("VISUAL") or os.environ.get("EDITOR") or "")
    except ValueError:
        cmd = []
    cmd = cmd or ["nvim"]
    name = os.path.basename(cmd[0])
    line = line or 1
    if name in LINE_PLUS_EDITORS:
        return cmd + [f"+{line}", path], False
    if name in ("code", "codium"):
        return cmd + ["-g", f"{path}:{line}"], True
    if name == "hx":
        return cmd + [f"{path}:{line}"], False
    return cmd + [path], name in GUI_EDITORS               # 行へ飛ぶ書き方を知らないエディタは、ファイルだけ開く


def read_layout_file():
    """layouts.toml の、自作の型・作業領域の余白・タイル間の隙間。"""
    try:
        with open(CONFIG, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        data = {}
    return dict(data.get("layouts", {})), {**DEFAULT_INSETS, **data.get("workarea", {})}, int(data.get("gap", 0))


def write_layout_file(layouts, insets, gap):
    data = {"gap": gap}
    if layouts:
        data["layouts"] = layouts
    data["workarea"] = dict(insets)
    write_toml(CONFIG, data)


def run_config(page="shortcuts"):
    """win の設定の窓。ショートカット・コマンド・セット・型の 4 ページ。"""
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk, Pango

    MODIFIER_KEYS = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Super_L", "Super_R",
                     "Meta_L", "Meta_R", "Hyper_L", "Hyper_R", "ISO_Level3_Shift", "ISO_Level5_Shift",
                     "Caps_Lock", "Num_Lock"}

    def clear(box):
        while (c := box.get_first_child()) is not None:
            box.remove(c)

    def plain(cls, **kw):
        """題名・説明を、マークアップではなく文字としてそのまま表示する行を作る（名前に < や & があっても壊れない）。"""
        kw.setdefault("use_markup", False)
        return cls(**kw)

    class ConfigWindow(Adw.ApplicationWindow):
        def __init__(self, app):
            super().__init__(application=app, title=tr("win の設定"), default_width=1040, default_height=880)
            self.used = {}
            css = Gtk.CssProvider()
            css.load_from_string(".tile-box { border: 1px solid alpha(currentColor, .4); border-radius: 4px; "
                                 "background: alpha(@accent_bg_color, .18); font-size: 9pt; } "
                                 ".cand-list row:selected { background: alpha(@accent_bg_color, .3); }")
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.toasts = Adw.ToastOverlay()
            self.stack = Adw.ViewStack()
            self.pages = {}
            for key, title, icon in (("shortcuts", tr("ショートカット"), "input-keyboard-symbolic"),
                                     ("commands", tr("コマンド"), "utilities-terminal-symbolic"),
                                     ("sets", tr("セット"), "view-dual-symbolic"),
                                     ("layouts", tr("型"), "view-grid-symbolic")):
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=18, margin_bottom=24,
                              margin_start=18, margin_end=18)
                clamp = Adw.Clamp(maximum_size=820, child=box)
                scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, child=clamp)
                self.pages[key] = box
                self.stack.add_titled_with_icon(scroll, key, title, icon)
            header = Adw.HeaderBar(title_widget=Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE))
            view = Adw.ToolbarView(content=self.stack)
            view.add_top_bar(header)
            self.toasts.set_child(view)
            self.set_content(self.toasts)
            self.refresh()

        # ------------------------------------------------------------ 共通
        def toast(self, text):
            self.toasts.add_toast(Adw.Toast.new(text))

        def refresh(self):
            reload_extensions()
            self.used = scan_accelerators()
            self.build_shortcuts()
            self.build_commands()
            self.build_sets()
            self.build_layouts()

        def suffix_box(self, *widgets):
            box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
            for w in widgets:
                box.append(w)
            return box

        def button(self, label, cb, css=None, tip=None):
            b = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
            if css:
                b.add_css_class(css)
            if tip:
                b.set_tooltip_text(tip)
            b.connect("clicked", lambda _b: cb())
            return b

        def icon_button(self, icon, cb, tip):
            b = Gtk.Button(icon_name=icon, valign=Gtk.Align.CENTER, tooltip_text=tip)
            b.add_css_class("flat")
            b.connect("clicked", lambda _b: cb())
            return b

        def dialog(self, title, child, width=520, height=0):
            dlg = Adw.Dialog(title=title, content_width=width)
            if height:
                dlg.set_content_height(height)
            dlg.set_child(child)
            dlg.present(self)
            return dlg

        def confirm(self, heading, body, label, cb, destructive=True):
            d = Adw.AlertDialog(heading=heading, body=body)
            d.add_response("cancel", tr("キャンセル"))
            d.add_response("ok", label)
            if destructive:
                d.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
            d.set_default_response("cancel")
            d.connect("response", lambda _d, r: cb() if r == "ok" else None)
            d.present(self)

        # ------------------------------------------------------------ キーを押して設定する
        def capture_key(self, title, current, slug, on_set):
            """キーを実際に押して選ぶ（文字での入力も可）。衝突と、Mozc オンで届かない形を知らせる。"""
            state = {"accel": current or "", "syncing": False}
            shown = Gtk.Label(label=accel_label(current), focusable=True)       # 開いたときのフォーカス先（文字入力ではない）
            shown.add_css_class("title-1")
            hint = Gtk.Label(label=tr("割り当てたいキーを、実際に押してください（Esc で取消）"), wrap=True)
            hint.add_css_class("dim-label")
            status = Gtk.Label(wrap=True, xalign=0, max_width_chars=60)
            entry = plain(Adw.EntryRow, title=tr("キーを文字で入力（例: <Super><Alt>m）"))
            entry.set_text(current or "")
            group = Adw.PreferencesGroup()
            group.add(entry)
            # 変換・無変換などは GNOME が先に処理して押しても届かないことがあるので、一覧からも選べるようにする
            special = plain(Adw.ComboRow, title=tr("日本語キーから選ぶ"))
            special.set_model(Gtk.StringList.new([tr("（選ばない）")] + list(JP_KEYS.values())))
            group.add(special)
            allow = Gtk.CheckButton(label=tr("ほかと競合していても設定する"))
            ok = self.button(tr("設定する"), lambda: finish(state["accel"]), "suggested-action")
            clear_b = self.button(tr("解除する"), lambda: finish(""))
            cancel = self.button(tr("キャンセル"), lambda: dlg.close())
            inhibit = self.button(tr("使用中のキーも押して調べる…"), lambda: do_inhibit(),
                                  tip=tr("GNOME の確認（ショートカットの無効化の許可）が出ます。許可すると、すでに使われているキーも押して確かめられます"))
            buttons = Gtk.Box(spacing=8, halign=Gtk.Align.END)
            for b in (clear_b, cancel, ok):
                buttons.append(b)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                          margin_start=18, margin_end=18)
            for w in (shown, hint, group, status, allow, inhibit, buttons):
                box.append(w)

            def update(accel, sync=True):
                state["accel"] = accel
                shown.set_label(accel_label(accel))
                if sync:                                            # 手で打っている最中は、欄を書き換えない
                    state["syncing"] = True
                    if entry.get_text() != accel:
                        entry.set_text(accel)
                    state["syncing"] = False
                conflicts = accel_conflicts(self.used, accel, slug) if accel else []
                note = accel_note(accel) if accel else ""
                lines = []
                if conflicts:
                    lines.append(tr("すでに使われています: ") + " ／ ".join(conflicts))
                if note:
                    lines.append(note)
                status.set_label("\n".join(lines))
                for c in ("error", "warning"):
                    status.remove_css_class(c)
                status.add_css_class("error" if conflicts else "warning")
                allow.set_visible(bool(conflicts))
                ok.set_sensitive(bool(accel) and (not conflicts or allow.get_active()))

            def finish(accel):
                dlg.close()
                on_set(accel)

            def on_key(_c, keyval, _kc, mask):
                focus = self.get_focus()
                if focus is not None and (focus is entry or focus.is_ancestor(entry)):
                    return False                                   # 文字入力の欄に打っているときは、そのまま
                name = Gdk.keyval_name(keyval) or ""
                if name in MODIFIER_KEYS:
                    return True
                mods = mask & Gtk.accelerator_get_default_mod_mask()
                if not mods and name == "Escape":
                    dlg.close()
                    return True
                if not mods and name in ("Tab", "ISO_Left_Tab"):
                    return False
                if not mods and name in ("Return", "KP_Enter") and ok.get_sensitive():
                    finish(state["accel"])
                    return True
                update(Gtk.accelerator_name(Gdk.keyval_to_lower(keyval), mods))
                return True

            def on_entry(_e):
                if state["syncing"]:
                    return
                text = entry.get_text().strip()
                if text and accel_parse(text):
                    update(accel_norm(text), sync=False)
                else:
                    update("", sync=False)
                    if text:
                        status.set_label(tr("キーの形式が読めません（例: <Super><Alt>m）"))
                        for c in ("error", "warning"):
                            status.remove_css_class(c)
                        status.add_css_class("warning")

            def do_inhibit():
                surf = self.get_native().get_surface()
                surf.inhibit_system_shortcuts(None)
                inhibit.set_sensitive(False)

            ctrl = Gtk.EventControllerKey()
            ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            ctrl.connect("key-pressed", on_key)
            entry.connect("changed", on_entry)

            def on_special(_r, _p):
                i = special.get_selected()
                if i > 0:
                    update(list(JP_KEYS)[i - 1])

            special.connect("notify::selected", on_special)
            allow.connect("toggled", lambda _c: update(state["accel"]))
            dlg = self.dialog(title, box)
            # ダイアログを開いている間、窓のフォーカスは空になり、内側の部品にはキーが届かない。窓全体で受け取る
            self.add_controller(ctrl)
            # 手入力の欄に英字（Super など）を打つので、開いている間だけ Mozc を直接入力にする
            prev = ibus_engine()
            switched = prev.startswith("mozc") and prev != "mozc-off"
            if switched:
                ibus_engine("mozc-off")

            def on_closed(_d):
                self.remove_controller(ctrl)
                self.get_native().get_surface().restore_system_shortcuts()
                if switched:
                    ibus_engine(prev)

            dlg.connect("closed", on_closed)
            update(current or "")
            GLib.idle_add(lambda: (dlg.set_focus(shown), False)[1])

        # ------------------------------------------------------------ ページ 1: ショートカット
        def key_label(self, accel):
            lab = Gtk.Label(label=accel_label(accel), valign=Gtk.Align.CENTER, margin_end=6)
            lab.add_css_class("monospace")
            if accel:
                lab.add_css_class("accent")
            else:
                lab.add_css_class("dim-label")
            return lab

        def set_binding(self, slug, name, command, accel):
            kb_set(slug, name=name, command=command, binding=accel)
            self.toast(tr("キーを解除しました") if not accel else tr("{0} に設定しました（反映まで数秒かかることがあります）").format(accel_label(accel)))
            self.refresh()

        def shortcut_row(self, slug, title, subtitle, current, name, command, deletable=False,
                         editable=False, kind=None):
            row = plain(Adw.ActionRow, title=title, subtitle=subtitle)
            row.set_subtitle_lines(1)
            btns = [self.key_label(current),
                    self.button(tr("変更"), lambda: self.capture_key(title, current, slug,
                                lambda a: self.set_binding(slug, name, command, a)))]
            if current:
                btns.append(self.icon_button("edit-clear-symbolic",
                            lambda: self.set_binding(slug, name, command, ""), tr("キーを解除")))
            if editable:
                btns.append(self.icon_button("document-edit-symbolic", lambda: self.shortcut_form(slug), tr("名前とコマンドを編集")))
            if deletable:
                btns.append(self.icon_button("user-trash-symbolic", lambda: self.confirm(
                    tr("このショートカットを削除しますか？"), tr("「{0}」を削除します。").format(title), tr("削除"),
                    lambda: (kb_remove(slug), self.toast(tr("削除しました")), self.refresh())), tr("削除")))
            if kind:                                      # 組み込み・拡張・コマンド・セットの別（小さな印）
                chip = Gtk.Label(label=kind, valign=Gtk.Align.CENTER)
                chip.add_css_class("caption")
                chip.add_css_class("dim-label")
                row.add_prefix(chip)
            row.add_suffix(self.suffix_box(*btns))
            return row

        def build_shortcuts(self):
            box = self.pages["shortcuts"]
            clear(box)
            intro = Gtk.Label(wrap=True, xalign=0, label=(
                tr("キーは、ここで一元管理します（GNOME の「カスタムショートカット」と同じ場所に書きます）。"
                "変更はすぐ保存され、反映まで数秒かかることがあります。")))
            intro.add_css_class("dim-label")
            box.append(intro)
            kbs = {e["slug"]: e for e in kb_list()}
            rows = {g: [] for g, _ in ACTION_GROUPS}          # グループ → 行（目的別に並べる。種類は行の印で示す）
            slot_rows = []
            for slug, label, args, group in WIN_ACTIONS:
                e = kbs.get(slug)
                row = self.shortcut_row(slug, label, f"win {args}", e["binding"] if e else "",
                                        f"win {args}（{label}）", f"{WIN_BIN} {args}", kind=tr("組み込み"))
                (slot_rows if slug.startswith("win-slot-") else rows[group]).append(row)
            if slot_rows:                                     # 1〜9 は 1 行にまとめ、開くと 9 個のキーを付けられる
                bound = sum(1 for slug, *_ in WIN_ACTIONS if slug.startswith("win-slot-") and kbs.get(slug, {}).get("binding"))
                exp = Adw.ExpanderRow(title=tr("n 番目のタイルの窓へ（1〜9）"), subtitle=tr("9 個のうち {0} 個にキーが付いています").format(bound))
                for r in slot_rows:
                    exp.add_row(r)
                rows[G_MOVE].append(exp)
            for name, c in load_commands().items():
                slug = command_slug(name)
                e = kbs.get(slug)
                rows[G_CMD].append(self.shortcut_row(slug, name, describe_command(c), e["binding"] if e else "",
                                                     f"win run: {name}", f"{WIN_BIN} run {shlex.quote(name)}", kind=tr("コマンド")))
            for name, c in load_sets().items():
                slug = set_slug(name)
                e = kbs.get(slug)
                rows[G_SET].append(self.shortcut_row(slug, name, set_summary(c), e["binding"] if e else "",
                                                     f"win set: {name}", f"{WIN_BIN} set {shlex.quote(name)}", kind=tr("セット")))
            for name, c in EXT.items():                       # 拡張の命令。@command(group=…) で、目的別のグループに入れられる
                slug = ext_slug(name)
                e = kbs.get(slug)
                rows[c.group if c.group in rows else G_OTHER].append(
                    self.shortcut_row(slug, name, c.summary, e["binding"] if e else "",
                                      f"win: {name}", f"{WIN_BIN} {shlex.quote(name)}", kind=tr("拡張")))
            for e in [e for slug, e in kbs.items() if slug.startswith("win-ext-") and slug not in {ext_slug(n) for n in EXT}]:
                row = self.shortcut_row(e["slug"], e["name"] or e["slug"], tr("⚠ この命令は拡張に見つかりません（消すか、拡張を直してください）"),
                                        e["binding"], e["name"], e["command"], deletable=True)   # 命令が消えた（名前が変わった）のに、キーだけ残っているもの
                row.add_css_class("warning")
                rows[G_OTHER].append(row)
            for gname, desc in ACTION_GROUPS:
                if rows[gname]:
                    g = Adw.PreferencesGroup(title=gname, description=desc)
                    for r in rows[gname]:
                        g.add(r)
                    box.append(g)
            own = {s for s, *_ in WIN_ACTIONS}
            g3 = Adw.PreferencesGroup(title=tr("その他の自作ショートカット"), description=tr("win 以外で、自分で登録したものです。"))
            g3.set_header_suffix(self.button(tr("＋ 追加"), lambda: self.shortcut_form(None)))
            for slug, e in kbs.items():
                if slug in own or slug.startswith(("win-run-", "win-set-", "win-ext-")):
                    continue
                g3.add(self.shortcut_row(slug, e["name"] or slug, e["command"], e["binding"], e["name"], e["command"],
                                         deletable=True, editable=True))
            box.append(g3)

        def shortcut_form(self, slug):
            """名前とコマンドを入力する（新規なら、続けてキーを押して設定する）。"""
            cur = next((e for e in kb_list() if e["slug"] == slug), None) if slug else None
            name_row = plain(Adw.EntryRow, title=tr("名前"))
            cmd_row = plain(Adw.EntryRow, title=tr("コマンド（例: /usr/bin/ibus engine mozc-on）"))
            if cur:
                name_row.set_text(cur["name"])
                cmd_row.set_text(cur["command"])
            group = Adw.PreferencesGroup()
            group.add(name_row)
            group.add(cmd_row)
            msg = Gtk.Label(wrap=True, xalign=0)
            msg.add_css_class("error")

            def save():
                n, c = name_row.get_text().strip(), cmd_row.get_text().strip()
                if not n or not c:
                    msg.set_label(tr("名前とコマンドの両方を入力してください"))
                    return
                dlg.close()
                if cur:
                    kb_set(slug, name=n, command=c)
                    self.toast(tr("保存しました"))
                    self.refresh()
                else:
                    new = "custom-" + hashlib.sha1(f"{n}{time.time()}".encode()).hexdigest()[:8]
                    self.capture_key(n, "", new, lambda a: (kb_set(new, name=n, command=c, binding=a),
                                                            self.toast(tr("追加しました")), self.refresh()))

            btns = Gtk.Box(spacing=8, halign=Gtk.Align.END)
            btns.append(self.button(tr("キャンセル"), lambda: dlg.close()))
            btns.append(self.button(tr("保存") if cur else tr("次へ（キーを設定）"), save, "suggested-action"))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                          margin_start=18, margin_end=18)
            for w in (group, msg, btns):
                box.append(w)
            dlg = self.dialog(tr("ショートカットを編集") if cur else tr("ショートカットを追加"), box)

        # ------------------------------------------------------------ ページ 2: コマンド
        def build_commands(self):
            box = self.pages["commands"]
            clear(box)
            intro = Gtk.Label(wrap=True, xalign=0, label=(
                tr("よく使う操作に名前をつけて登録します。`win run 名前` で呼べて、入力欄（win prompt）の補完にも出ます。"
                "窓の並びは「セット」ページで保存します。キーは「ショートカット」ページで付けます。")))
            intro.add_css_class("dim-label")
            box.append(intro)
            cmds = load_commands()
            g = Adw.PreferencesGroup(title=tr("登録したコマンド"))
            g.set_header_suffix(self.button(tr("＋ 新しいコマンド"), lambda: self.command_form(None), "suggested-action"))
            kinds = {"win": tr("win の命令"), "shell": tr("シェルコマンド")}
            for name, c in cmds.items():
                row = plain(Adw.ActionRow, title=name, subtitle=f"{kinds.get(c.get('type', 'win'), '?')}　{describe_command(c)}")
                row.set_subtitle_lines(1)
                row.add_suffix(self.suffix_box(
                    self.button(tr("実行"), lambda n=name: self.run_command(n), tip=tr("いま実行する")),
                    self.icon_button("document-edit-symbolic", lambda n=name: self.command_form(n), tr("編集")),
                    self.icon_button("user-trash-symbolic", lambda n=name: self.confirm(
                        tr("コマンドを削除しますか？"), tr("「{0}」と、それに付けたキーを削除します。").format(n), tr("削除"),
                        lambda: self.delete_command(n)), tr("削除"))))
                g.add(row)
            if not cmds:
                g.add(plain(Adw.ActionRow, title=tr("（まだありません。右上のボタンから作れます）")))
            box.append(g)
            ge = Adw.PreferencesGroup(
                title=tr("拡張（Python）"),
                description=tr("{0} に .py を置き、関数に @command を付けると win の命令になります（win 名前 で呼べて、入力欄の補完・登録したコマンド・ショートカットでも使えます）。書き方は同じ場所の winapi.pyi と、win help にあります。").format(EXT_DIR))
            ge.set_header_suffix(self.suffix_box(
                self.button(tr("フォルダを開く"), self.open_ext_dir),
                self.button(tr("再読み込み"), lambda: (self.refresh(), self.toast(tr("拡張を読み直しました")))),
                self.button(tr("＋ 新しい拡張"), self.new_ext_form, "suggested-action")))
            for name, c in EXT.items():
                row = plain(Adw.ActionRow, title=name, subtitle=f"{c.summary}　{c.usage()}")
                row.set_subtitle_lines(1)
                row.add_suffix(self.suffix_box(
                    self.button(tr("実行"), lambda n=name: self.run_ext_command(n), tip=tr("引数を省いて、いま実行する")),
                    self.icon_button("document-edit-symbolic", lambda c=c: self.open_ext_source(c.file, c.line),
                                     tr("定義を開く（エディタ）")),
                    self.icon_button("user-trash-symbolic", lambda c=c: self.confirm_delete_ext(c.file), tr("削除"))))
                ge.add(row)
            for path, msg in EXT_ERRORS:
                row = plain(Adw.ActionRow, title=tr("読み込めませんでした: {0}").format(os.path.basename(path)), subtitle=msg)
                row.add_css_class("error")
                row.add_suffix(self.suffix_box(
                    self.icon_button("document-edit-symbolic", lambda p=path, m=msg: self.open_ext_source(p, _error_line(m)), tr("開く")),
                    self.icon_button("user-trash-symbolic", lambda p=path: self.confirm_delete_ext(p), tr("削除"))))
                ge.add(row)
            if not EXT and not EXT_ERRORS:
                ge.add(plain(Adw.ActionRow, title=tr("（拡張はまだありません）")))
            box.append(ge)

        def new_ext_form(self):
            """名前を聞いて、ひな形の拡張を作り、エディタで開く。"""
            name_row = plain(Adw.EntryRow, title=tr("命令の名前（英字・数字・_。例: swap）"))
            group = Adw.PreferencesGroup(
                description=tr("{0}/名前.py を作り、エディタ（$VISUAL・$EDITOR。なければ端末の nvim）で開きます。保存した後、この画面の「再読み込み」で一覧に出ます。").format(EXT_DIR))
            group.add(name_row)
            msg = Gtk.Label(wrap=True, xalign=0)
            msg.add_css_class("error")

            def create():
                n = name_row.get_text().strip()
                if not n.isidentifier():
                    msg.set_label(tr("英字・数字・_ で、数字以外から始まる名前にしてください"))
                    return
                if n in builtin_commands():
                    msg.set_label(tr("「{0}」は win の組み込みの命令と同じ名前です").format(n))
                    return
                if n in EXT:
                    msg.set_label(tr("「{0}」はすでにあります（{1}）").format(n, EXT[n].file))
                    return
                path = os.path.join(EXT_DIR, f"{n}.py")
                if os.path.exists(path):
                    msg.set_label(tr("{0} はすでにあります").format(path))
                    return
                os.makedirs(EXT_DIR, exist_ok=True)
                write_ext_support()
                with open(path, "w", encoding="utf-8") as f:
                    f.write(EXT_TEMPLATE.format(name=n))
                dlg.close()
                self.open_ext_source(path, EXT_TEMPLATE.splitlines().index("@command") + 2)
                self.toast(tr("{0} を作りました。保存したら「再読み込み」を押してください").format(path))

            name_row.connect("entry-activated", lambda _r: create())
            btns = Gtk.Box(spacing=8, halign=Gtk.Align.END)
            btns.append(self.button(tr("キャンセル"), lambda: dlg.close()))
            btns.append(self.button(tr("作って開く"), create, "suggested-action"))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                          margin_start=18, margin_end=18)
            for w in (group, msg, btns):
                box.append(w)
            dlg = self.dialog(tr("新しい拡張"), box, 560)

        def open_ext_dir(self):
            os.makedirs(EXT_DIR, exist_ok=True)
            write_ext_support()
            Gio.AppInfo.launch_default_for_uri(GLib.filename_to_uri(EXT_DIR), None)

        def open_ext_source(self, path, line):
            if not path:
                return
            argv, gui = editor_argv(path, line)
            if not shutil.which(argv[0]):
                self.toast(tr("拡張のソースを開くには、エディタ（{0}）が要ります。ファイルは ").format(argv[0]) + path + tr(" にあります"))
                return
            if not gui:                                                              # 端末のエディタは、端末（Ptyxis）の窓の中で開く
                if not shutil.which("ptyxis"):
                    self.toast(tr("端末のエディタで開くには、ptyxis が要ります。ファイルは ") + path + tr(" にあります"))
                    return
                argv = ["ptyxis", "--new-window", "-d", os.path.dirname(path), "--"] + argv
            subprocess.Popen(argv, cwd=os.path.dirname(path), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)

        def confirm_delete_ext(self, path):
            """拡張のファイルを、確かめてからゴミ箱へ移す。ファイルの中の命令（1 つとは限らない）のキーも消す。"""
            names = [n for n, c in EXT.items() if c.file == path]
            body = tr("「{0}」をゴミ箱へ移します。").format(os.path.basename(path))
            if names:
                body += tr("この中の命令（{0}）と、それに付けたキーが使えなくなります。").format("・".join(names))
            self.confirm(tr("拡張を削除しますか？"), body, tr("削除"), lambda: self.delete_ext(path, names))

        def delete_ext(self, path, names):
            try:
                Gio.File.new_for_path(path).trash(None)
            except GLib.Error as e:
                self.toast(tr("削除できませんでした: {0}").format(e.message))
                return
            for n in names:
                kb_remove(ext_slug(n))
            self.toast(tr("ゴミ箱へ移しました"))
            self.refresh()

        def run_ext_command(self, name):
            subprocess.Popen([sys.executable, WIN_BIN, name], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            self.toast(tr("「{0}」を実行しました").format(name))

        # ------------------------------------------------------------ ページ 3: セット
        def build_sets(self):
            box = self.pages["sets"]
            clear(box)
            intro = Gtk.Label(wrap=True, xalign=0, label=(
                tr("窓の並びに名前をつけて保存したものです。`win set 名前`、または `win set`（絞り込みの小窓）で呼べます。保存先は {0} です。キーは「ショートカット」ページで付けます。").format(SETS)))
            intro.add_css_class("dim-label")
            box.append(intro)
            sets = load_sets()
            g = Adw.PreferencesGroup(title=tr("保存したセット"))
            g.set_header_suffix(self.suffix_box(
                self.button(tr("＋ 手で書く"), lambda: self.command_form(None, is_set=True)),
                self.button(tr("今の窓の並びを保存…"), self.save_arrangement_form, "suggested-action")))
            for name, c in sets.items():
                row = plain(Adw.ActionRow, title=name, subtitle=set_summary(c))
                row.set_subtitle_lines(1)
                row.add_suffix(self.suffix_box(
                    self.button(tr("適用"), lambda n=name: self.run_set(n), tip=tr("いま適用する")),
                    self.icon_button("document-edit-symbolic", lambda n=name: self.command_form(n, is_set=True), tr("編集")),
                    self.icon_button("user-trash-symbolic", lambda n=name: self.confirm(
                        tr("セットを削除しますか？"), tr("「{0}」と、それに付けたキーを削除します。").format(n), tr("削除"),
                        lambda: self.delete_set(n)), tr("削除"))))
                g.add(row)
            if not sets:
                g.add(plain(Adw.ActionRow, title=tr("（まだありません。右上の「今の窓の並びを保存…」から作れます）")))
            box.append(g)

        def run_set(self, name):
            subprocess.Popen([sys.executable, WIN_BIN, "set", name], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            self.toast(tr("「{0}」を適用しました").format(name))

        def delete_set(self, name):
            sets = load_sets()
            sets.pop(name, None)
            save_sets(sets)
            kb_remove(set_slug(name))
            self.toast(tr("削除しました"))
            self.refresh()

        def run_command(self, name):
            subprocess.Popen([sys.executable, WIN_BIN, "run", name], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            self.toast(tr("「{0}」を実行しました").format(name))

        def delete_command(self, name):
            cmds = load_commands()
            cmds.pop(name, None)
            save_commands(cmds)
            kb_remove(command_slug(name))
            self.toast(tr("削除しました"))
            self.refresh()

        def command_form(self, name, is_set=False):
            """コマンド（is_set なら セット）を作る・直すダイアログ。セットは win の命令だけを持つ。"""
            cmds = load_sets() if is_set else load_commands()
            c = cmds.get(name, {"type": "win", "run": ""}) if name else {"type": "win", "run": ""}
            arrange = c.get("type") == "arrange"
            name_row = plain(Adw.EntryRow, title=tr("名前"))
            name_row.set_text(name or "")
            type_row = plain(Adw.ComboRow, title=tr("種類"), model=Gtk.StringList.new([tr("win の命令（複数行可）"), tr("シェルコマンド（複数行可）")]))
            type_row.set_selected(1 if c.get("type") == "shell" else 0)
            run_buf = Gtk.TextBuffer()
            run_buf.set_text(c.get("run", ""))
            run_view = Gtk.TextView(buffer=run_buf, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR, accepts_tab=False,
                                    top_margin=8, bottom_margin=8, left_margin=10, right_margin=10)
            run_scroll = Gtk.ScrolledWindow(child=run_view, min_content_height=260, vexpand=True, has_frame=True)

            def run_text():
                return run_buf.get_text(run_buf.get_start_iter(), run_buf.get_end_iter(), False)

            group = Adw.PreferencesGroup()
            group.add(name_row)
            if not arrange and not is_set:
                group.add(type_row)
            sig_label = Gtk.Label(wrap=True, xalign=0, use_markup=True, selectable=False, margin_start=4, margin_end=4)
            sig_label.add_css_class("dim-label")
            spec = {"layouts": load_config()["layouts"], "commands": load_commands(), **ext_spec(), "windows": [
                {"sel": selector_for(w, ws), "cls": w.get("wm_class") or "", "title": (w.get("title") or "")[:60]}
                for ws in [normal_windows(WindowCalls())] for w in reversed(ws)]}
            cand = {"shown": [], "token": "", "quiet": False}         # 候補 [(挿入する語, 説明)]、置き換える語、自動の書き換え中か
            cand_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.BROWSE, can_focus=False)
            cand_scroll = Gtk.ScrolledWindow(child=cand_list, hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                             max_content_height=230, min_content_width=460)
            popup = Gtk.Popover(autohide=False, has_arrow=False, can_focus=False, focusable=False, child=cand_scroll,
                                position=Gtk.PositionType.BOTTOM)
            popup.add_css_class("menu")
            cand_list.add_css_class("cand-list")                          # 選択中の行を目立たせる（CSS は設定窓の定義）
            cand_scroll.set_size_request(520, -1)
            popup.set_halign(Gtk.Align.START)                          # 左端をカーソルに合わせる（中央寄せだと左にはみ出す）
            popup.set_parent(run_view)

            def line_before_cursor():
                it = run_buf.get_iter_at_mark(run_buf.get_insert())
                start = it.copy()
                start.set_line_offset(0)
                return run_buf.get_text(start, it, False)

            def completion_text(before):
                """候補を出す対象の文字列（win の命令の部分）。出さない行は None。"""
                if type_row.get_selected() == 1:                     # シェル: win … で始まる行だけ
                    return before[4:] if before.startswith("win ") else None
                return before[4:] if before.startswith("win ") else before

            def hide_popup():
                if popup.is_visible():
                    popup.popdown()

            def refresh_candidates(force=False):
                before = line_before_cursor()
                text = completion_text(before)
                if text is None or (not text and not force) or (cand["quiet"] and not force):
                    hide_popup()
                    return
                items = suggest(text, spec)
                if type_row.get_selected() == 0:                     # win の命令の中では run / config は使えない
                    items = [(i, d) for i, d in items if i.strip() not in ("run", "config")]
                items = items[:8]
                cand["shown"], cand["token"] = items, text.split(" ")[-1]
                while (r := cand_list.get_row_at_index(0)) is not None:
                    cand_list.remove(r)
                if not items:
                    hide_popup()
                    return
                for ins, desc in items:
                    row_box = Gtk.Box(spacing=12, margin_top=4, margin_bottom=4, margin_start=10, margin_end=10)
                    first = Gtk.Label(label=ins.strip(), xalign=0, width_chars=14)
                    second = Gtk.Label(label=desc, xalign=0, hexpand=True, ellipsize=3, max_width_chars=48)
                    second.add_css_class("dim-label")
                    row_box.append(first)
                    row_box.append(second)
                    cand_list.append(Gtk.ListBoxRow(can_focus=False, child=row_box))
                cand_list.select_row(cand_list.get_row_at_index(0))
                rect = run_view.get_iter_location(run_buf.get_iter_at_mark(run_buf.get_insert()))
                x, y = run_view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, rect.x, rect.y)
                area = Gdk.Rectangle()
                area.x, area.y, area.width, area.height = x, y, 1, rect.height
                popup.set_pointing_to(area)
                if not popup.is_visible():
                    popup.popup()

            def accept_candidate():
                sel = cand_list.get_selected_row()
                if sel is None or not cand["shown"]:
                    return
                ins = cand["shown"][sel.get_index()][0]
                end = run_buf.get_iter_at_mark(run_buf.get_insert())
                start = end.copy()
                start.backward_chars(len(cand["token"]))
                run_buf.delete(start, end)
                cand["quiet"] = True
                run_buf.insert_at_cursor(ins)
                cand["quiet"] = False
                refresh_candidates()                                  # 続けて次の語の候補を出す
                update_signature()

            def update_signature(*_):
                before = line_before_cursor()
                text = completion_text(before) if before.strip() else None
                markup = signature_markup(text) if text else None
                if type_row.get_selected() == 1 and text is None:
                    markup = None
                sig_label.set_markup(markup or tr("命令を打つと候補が出ます（Tab で確定、↑↓で選択、Esc で閉じる、Ctrl+Space で候補を出す）。"))

            def on_changed(_b):
                refresh_candidates()
                update_signature()

            def on_cursor(*_):
                update_signature()
                if popup.is_visible():                                # 動かしたら、その位置での候補に合わせる（なければ閉じる）
                    refresh_candidates(force=True)

            def on_run_key(_c, keyval, _kc, state):
                name = Gdk.keyval_name(keyval)
                ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
                if ctrl and name == "space":
                    refresh_candidates(force=True)
                    return True
                if not popup.is_visible():
                    return False
                if name in ("Tab", "ISO_Left_Tab"):
                    accept_candidate()
                    return True
                if name in ("Down", "Up"):
                    sel = cand_list.get_selected_row()
                    n = len(cand["shown"])
                    cand_list.select_row(cand_list.get_row_at_index(((sel.get_index() if sel else 0) + (1 if name == "Down" else -1)) % n))
                    return True
                if name == "Escape":
                    hide_popup()
                    return True
                return False

            key_ctrl = Gtk.EventControllerKey()
            key_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            key_ctrl.connect("key-pressed", on_run_key)
            run_view.add_controller(key_ctrl)
            run_buf.connect("changed", on_changed)
            run_buf.connect("notify::cursor-position", on_cursor)
            update_signature()
            help_l = Gtk.Label(wrap=True, xalign=0)
            help_l.add_css_class("dim-label")
            msg = Gtk.Label(wrap=True, xalign=0)
            msg.add_css_class("error")

            def update_help(*_):
                if arrange:
                    help_l.set_label(tr("窓の並び {0} 枚を保存しています（作り直すには「今の窓の並びを保存」を、同じ名前で）。").format(len(c.get('windows', []))))
                elif type_row.get_selected() == 0:
                    help_l.set_label(tr("win の命令を、1 行に 1 つ書きます。上から順に実行し、失敗したらそこで止まります。# で始まる行は無視されます。")
                                     + (tr("ふつうは最初の layout 行が並びで、一覧のプレビューにもその行が使われます。") if is_set else ""))
                else:
                    help_l.set_label(tr("シェルで実行されます（複数行はそのまま 1 つのスクリプトになります）。win の命令を呼ぶときは頭に win を付けます。"))

            def validate():
                n = name_row.get_text().strip()
                if not n:
                    return tr("名前を入力してください")
                if n != name and n in cmds:
                    return tr("「{0}」はすでにあります").format(n)
                if not arrange:
                    text = run_text().strip()
                    if not text:
                        return tr("内容を入力してください")
                    if type_row.get_selected() == 0:
                        return check_win_line(text)
                return None

            def save():
                err = validate()
                if err:
                    msg.set_label(err)
                    return
                n = name_row.get_text().strip()
                new = dict(c)
                if not arrange:
                    new["type"] = "shell" if type_row.get_selected() == 1 else "win"
                    new["run"] = run_text().strip()
                if name and n != name:                        # 名前の変更: 並びを保ち、キーも付け替える
                    cmds.pop(name)
                    slug, verb = (set_slug, "set") if is_set else (command_slug, "run")
                    old = next((e for e in kb_list() if e["slug"] == slug(name)), None)
                    if old:
                        kb_remove(slug(name))
                        kb_set(slug(n), name=f"win {verb}: {n}", command=f"{WIN_BIN} {verb} {shlex.quote(n)}",
                               binding=old["binding"])
                cmds[n] = new
                (save_sets if is_set else save_commands)(cmds)
                dlg.close()
                self.toast(tr("保存しました"))
                self.refresh()

            def try_it():
                err = validate()
                if err:
                    msg.set_label(err)
                    return
                msg.set_label("")
                tmp = dict(c)
                if not arrange:
                    tmp["type"] = "shell" if type_row.get_selected() == 1 else "win"
                    tmp["run"] = run_text().strip()
                if arrange:
                    self.toast(tr("保存済みの並びは、保存後に「実行」で試せます"))
                    return
                if tmp["type"] == "shell":
                    subprocess.Popen(["sh", "-c", tmp["run"]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
                else:
                    def seq():                                   # 上から順に。失敗したら止める
                        for line in win_lines(tmp["run"]):
                            argv = shlex.split(line)
                            argv = argv[1:] if argv[0] == "win" else argv
                            r = subprocess.run([sys.executable, WIN_BIN] + argv, stdin=subprocess.DEVNULL,
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            if r.returncode:
                                break
                    threading.Thread(target=seq, daemon=True).start()
                self.toast(tr("実行しました"))

            type_row.connect("notify::selected", update_help)
            update_help()
            btns = Gtk.Box(spacing=8, halign=Gtk.Align.END)
            if not arrange:
                btns.append(self.button(tr("試す"), try_it, tip=tr("保存せずに、いま実行します")))
            btns.append(self.button(tr("キャンセル"), lambda: dlg.close()))
            btns.append(self.button(tr("保存"), save, "suggested-action"))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                          margin_start=18, margin_end=18)
            if arrange:
                widgets = (group, help_l, msg, btns)
            else:
                label = Gtk.Label(label=tr("内容"), xalign=0)
                label.add_css_class("heading")
                widgets = (group, label, run_scroll, sig_label, help_l, msg, btns)
            for w in widgets:
                box.append(w)
            what = tr("セット") if is_set else tr("コマンド")
            dlg = self.dialog(tr("{0}を編集").format(what) if name else tr("新しい{0}").format(what), box, 780, 0 if arrange else 800)
            if not arrange:
                dlg.connect("closed", lambda _d: popup.unparent())

        def save_arrangement_form(self):
            name_row = plain(Adw.EntryRow, title=tr("名前（例: 作業用）"))
            group = Adw.PreferencesGroup(
                description=tr("いま表に出ている窓（この画面にあるもの）を、型と窓の列（例: layout v(1,2,1) firefox? ...）として保存します。"
                            "ピクセルは保存しないので、画面の大きさが変わっても使えます。窓がなければ起動します。`win set 名前` で呼べます。"))
            group.add(name_row)
            fx_row = plain(Adw.SwitchRow, title=tr("Firefox のタブも保存する"),
                           subtitle=tr("開いているタブの URL を保存し、窓がなければそのタブで開き直します。URL は平文で保存されます"))
            tm_row = plain(Adw.SwitchRow, title=tr("端末の作業ディレクトリも保存する"),
                           subtitle=tr("タブごとの作業ディレクトリを保存し、窓がなければそこで開き直します"))
            state_group = Adw.PreferencesGroup(
                title=tr("状態も保存する（必要なときだけ）"),
                description=tr("特定の作業を繰り返すときのための設定です。汎用の並びでは、オフのままにしてください（開く場所が固定されます）。"))
            state_group.add(fx_row)
            state_group.add(tm_row)
            msg = Gtk.Label(wrap=True, xalign=0)
            msg.add_css_class("error")

            def state():
                return tuple(k for k, r in (("firefox", fx_row), ("terminal", tm_row)) if r.get_active())

            def do_save(overwrite=False):
                n = name_row.get_text().strip()
                if not n:
                    msg.set_label(tr("名前を入力してください"))
                    return
                try:
                    count, notes = save_arrangement(WindowCalls(), n, overwrite, state())
                except NameExistsError:
                    self.confirm(tr("上書きしますか？"), tr("「{0}」はすでにあります。").format(n), tr("上書き"),
                                 lambda: (dlg.close(), do_save_force(n)), destructive=False)
                    return
                except WinError as e:
                    msg.set_label(str(e))
                    return
                dlg.close()
                self.toast(tr("「{0}」を保存しました（窓 {1} 枚）").format(n, count) + (tr("　注意: ") + " ／ ".join(notes) if notes else ""))
                self.refresh()

            def do_save_force(n):
                try:
                    count, notes = save_arrangement(WindowCalls(), n, True, state())
                    self.toast(tr("「{0}」を上書きしました（窓 {1} 枚）").format(n, count) + (tr("　注意: ") + " ／ ".join(notes) if notes else ""))
                except WinError as e:
                    self.toast(str(e))
                self.refresh()

            btns = Gtk.Box(spacing=8, halign=Gtk.Align.END)
            btns.append(self.button(tr("キャンセル"), lambda: dlg.close()))
            btns.append(self.button(tr("保存"), lambda: do_save(), "suggested-action"))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                          margin_start=18, margin_end=18)
            for w in (group, state_group, msg, btns):
                box.append(w)
            dlg = self.dialog(tr("今の窓の並びを保存"), box, 560)

        # ------------------------------------------------------------ ページ 4: 型
        def layout_preview(self, fixed, expr, w=380, h=230):
            clear(fixed)
            try:
                rects = compute_rects(expr, (0, 0, 1000, 1000), 0)
            except WinError as e:
                return str(e)
            for i, (x, y, rw, rh) in enumerate(rects):
                lab = Gtk.Label(label=str(i + 1))
                lab.add_css_class("tile-box")
                lab.set_size_request(max(8, int(rw * w / 1000) - 2), max(8, int(rh * h / 1000) - 2))
                fixed.put(lab, int(x * w / 1000) + 1, int(y * h / 1000) + 1)
            return ""

        def build_layouts(self):
            box = self.pages["layouts"]
            clear(box)
            user, insets, gap = read_layout_file()
            allay = dict(BUILTIN_LAYOUTS)
            allay.update(user)
            intro = Gtk.Label(wrap=True, xalign=0, label=(
                tr("窓を並べる「型」です。`v(…)` は左右に、`h(…)` は上下に分けます。数は割合で、`2:v(1,1)` のように、"
                "割合つきで中をさらに分けられます。略記もあり、`,` で左右、`/` で上下、`( )` でまとめ、`2:` で割合です"
                "（例: `1,2:1/1/1,1` = v(1,2:h(1,1,1),1)。引用符は要りません）。組み込みの型は、複製して編集できます。")))
            intro.add_css_class("dim-label")
            box.append(intro)

            names = list(allay)
            current = {"name": names[0] if names else "", "new": False}
            lst = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
            lst.add_css_class("boxed-list")
            for n in names:
                r = plain(Adw.ActionRow, title=n, subtitle=allay[n])
                r.set_subtitle_lines(1)
                tag = tr("自作") if n in user else tr("組み込み")
                badge = Gtk.Label(label=tag + (tr("（上書き）") if n in user and n in BUILTIN_LAYOUTS else ""), valign=Gtk.Align.CENTER)
                badge.add_css_class("dim-label")
                r.add_suffix(badge)
                lst.append(r)
            lst_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=lst, hexpand=False)
            lst_scroll.set_size_request(290, 300)

            preview = Gtk.Fixed(halign=Gtk.Align.CENTER, margin_top=6, margin_bottom=6)
            preview.set_size_request(380, 230)
            name_row = plain(Adw.EntryRow, title=tr("名前"))
            expr_row = plain(Adw.EntryRow, title=tr("式（例: h(1,2:v(1,1),1)　略記: 1,2:1/1/1,1）"))
            eg = Adw.PreferencesGroup()
            eg.add(name_row)
            eg.add(expr_row)
            status = Gtk.Label(wrap=True, xalign=0)
            ed = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            save_b = self.button(tr("保存"), lambda: save_layout(), "suggested-action")
            del_b = self.button(tr("削除"), lambda: del_layout())
            dup_b = self.button(tr("複製して編集"), lambda: dup_layout())
            new_b = self.button(tr("＋ 新しい型"), lambda: new_layout())
            row_btns = Gtk.Box(spacing=8, halign=Gtk.Align.END)
            for b in (new_b, dup_b, del_b, save_b):
                row_btns.append(b)
            for w in (preview, eg, status, row_btns):
                ed.append(w)
            body = Gtk.Box(spacing=18)
            body.append(lst_scroll)
            ed.set_hexpand(True)
            body.append(ed)
            g = Adw.PreferencesGroup(title=tr("型の一覧と編集"))
            g.add(body)
            box.append(g)

            def load(name):
                current["name"], current["new"] = name, False
                builtin_only = name in BUILTIN_LAYOUTS and name not in user
                name_row.set_text(name)
                expr_row.set_text(allay[name])
                name_row.set_editable(not builtin_only)
                expr_row.set_editable(not builtin_only)
                save_b.set_sensitive(not builtin_only)
                del_b.set_sensitive(name in user)
                dup_b.set_sensitive(True)
                check()

            def check(*_):
                err = self.layout_preview(preview, expr_row.get_text().strip())
                nm = name_row.get_text().strip()
                if not err and not nm:
                    err = tr("名前を入力してください")
                if not err and (current["new"] or nm != current["name"]) and nm in allay:
                    err = tr("「{0}」はすでにあります").format(nm)
                if err:
                    status.set_label(err)
                    status.remove_css_class("success")
                    status.add_css_class("error")
                else:
                    n = len(compute_rects(expr_row.get_text().strip(), (0, 0, 1, 1), 0))
                    status.set_label(tr("タイル {0} 枚").format(n))
                    status.remove_css_class("error")
                    status.add_css_class("dim-label")
                editable = name_row.get_editable()
                save_b.set_sensitive(editable and not err)

            def save_layout():
                nm, ex = name_row.get_text().strip(), expr_row.get_text().strip()
                u = dict(user)
                if not current["new"] and current["name"] != nm:
                    u.pop(current["name"], None)
                u[nm] = ex
                write_layout_file(u, insets, gap)
                self.layout_to_select = nm
                self.toast(tr("型「{0}」を保存しました").format(nm))
                self.refresh()

            def del_layout():
                u = dict(user)
                u.pop(current["name"], None)
                write_layout_file(u, insets, gap)
                self.toast(tr("型「{0}」を削除しました").format(current['name']))
                self.refresh()

            def dup_layout():
                base = expr_row.get_text().strip() or "full"
                nm = name_row.get_text().strip() or "my-layout"
                k = 2
                while f"{nm}-{k}" in allay:
                    k += 1
                current["new"] = True
                name_row.set_editable(True)
                expr_row.set_editable(True)
                name_row.set_text(f"{nm}-{k}")
                expr_row.set_text(base)
                del_b.set_sensitive(False)
                check()

            def new_layout():
                dup_layout()
                name_row.set_text("my-layout" if "my-layout" not in allay else "my-layout-2")
                expr_row.set_text("v(1,1)")

            lst.connect("row-selected", lambda _l, r: load(names[r.get_index()]) if r is not None else None)
            name_row.connect("changed", check)
            expr_row.connect("changed", check)
            want = getattr(self, "layout_to_select", None)               # 保存した型を選び直す（なければ先頭）
            self.layout_to_select = None
            pos = names.index(want) if want in names else 0
            lst.select_row(lst.get_row_at_index(pos))
            if pos:
                GLib.idle_add(lambda: (lst.get_row_at_index(pos).grab_focus(), False)[1])   # 一覧をそこまでスクロールする

            # 配置の設定（隙間・作業領域の余白）
            g2 = Adw.PreferencesGroup(title=tr("配置の設定"),
                                      description=tr("タイルどうしの隙間と、作業領域の余白（画面の端から窓を置かない幅）。単位は px。"))
            spins = {}
            for key, label, val in (("gap", tr("タイルどうしの隙間"), gap), ("top", tr("上の余白（上部バーの高さ。主モニタだけに適用）"), insets["top"]),
                                    ("bottom", tr("下の余白"), insets["bottom"]), ("left", tr("左の余白"), insets["left"]),
                                    ("right", tr("右の余白"), insets["right"])):
                sp = plain(Adw.SpinRow, title=label, adjustment=Gtk.Adjustment(value=val, lower=0, upper=400, step_increment=1))
                spins[key] = sp
                g2.add(sp)

            def save_settings():
                ins = {k: int(spins[k].get_value()) for k in ("top", "bottom", "left", "right")}
                write_layout_file(user, ins, int(spins["gap"].get_value()))
                self.toast(tr("配置の設定を保存しました"))
                self.refresh()

            g2.set_header_suffix(self.button(tr("保存"), save_settings, "suggested-action"))
            box.append(g2)

    class ConfigApp(Adw.Application):
        def __init__(self):
            super().__init__(application_id=CONFIG_APP_ID)
            self.win = None

        def do_activate(self):
            if self.win is None:
                self.win = ConfigWindow(self)
            self.win.stack.set_visible_child_name(page)
            self.win.present()

    ConfigApp().run([])

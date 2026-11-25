"""コマンド入力の小窓（win prompt）と補完。"""

import contextlib
import gi
import io
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from gi.repository import GLib
from gi.repository import Gio

from .common import HISTORY, NVPROMPT_APP_ID, PROMPT_APP_ID
from .i18n import tr
from .screen import load_config
from .shortcuts import WIN_BIN
from .dbus import AT_SELECTORS, WindowCalls, normal_windows, selector_for
from .store import SIGNATURES, describe_command, load_commands, load_sets, signature_markup
from .pickwin import center_and_focus
from .sets import set_summary


SUBCOMMANDS = [("here", tr("選んだ窓を今の窓と同じ位置・大きさにして前面へ")), ("place", tr("選んだ窓を、置き先（番号のタイル・空き）に重ねる")), ("stack", tr("重なった窓の層を切り替える")), ("group", tr("窓のグループ")), ("stats", tr("使用の集計")), ("send", tr("窓を別のモニタへ送る")), ("shortcuts", tr("ショートカットの設定の書き出し・反映")), ("undo", tr("直前の操作を元に戻す")), ("desktop", tr("デスクトップを切り替える")), ("focus", tr("窓を前面に出す")), ("nav", tr("上下左右の窓へ")), ("layout", tr("窓を分割配置する")),
               ("pick", tr("窓の一覧から選ぶ")), ("list", tr("窓の一覧を表示")), ("layouts", tr("型の一覧を表示")),
               ("move", tr("窓を移動する")), ("size", tr("大きさを変える")), ("state", tr("最大化・最小化・常に手前")),
               ("max", tr("窓を最大化する")), ("unmax", tr("最大化を戻す")), ("min", tr("窓を最小化する")),
               ("unmin", tr("最小化を戻す")), ("close", tr("窓を閉じる")), ("run", tr("登録したコマンド・保存した並びを実行")),
               ("save", tr("いまの窓の並びを名前をつけて保存")), ("set", tr("保存した並び（セット）を選んで適用")),
               ("term", tr("端末を作業ディレクトリのタブつきで開く")), ("browse", tr("Firefox を URL のタブつきで開く")),
               ("config", tr("設定の画面を開く")), ("help", tr("命令の書式と説明を表示"))]


STATE_ACTIONS = ["max", "unmax", "min", "unmin", "above", "unabove"]


SHOW_OUTPUT = {"list", "layouts", "help"}   # 結果を入力欄の下に出す命令


def run_with_ascii_input(run):
    """run() の間だけ、日本語入力（IBus Mozc／fcitx5 Mozc）を Mozc を通さない状態にして、終わったら戻す（英字がかな・全角にならないように。
    mozc-off でも Mozc の中が全角・かなのことがあった）。切り替え（約 0.08 秒）は窓を作るのと同時に進める。"""
    if _im_backend() == "fcitx5":
        # fcitx5 は状態をアプリごとに持つ。元のアプリには触らず、この窓（自分のプログラム）だけを切る（復元は要らない）。
        me = _own_program()
        th = threading.Thread(target=lambda: _run_quiet(_im_cmd(), "off-for", me), daemon=True)
        th.start()
        try:
            return run()
        finally:
            th.join()
    state = {"prev": ""}

    def switch():
        state["prev"] = ime_state()
        if ime_is_mozc(state["prev"]):
            ime_plain()

    th = threading.Thread(target=switch, daemon=True)
    th.start()
    try:
        return run()
    finally:
        th.join()
        if ime_is_mozc(state["prev"]):
            ime_set(state["prev"])


def _im_backend():
    im = _im_cmd()
    return _run_quiet(im, "backend") if im else "ibus"


def _own_program():
    """このプロセスのプログラム名（fcitx5 が program: として見る名前）。"""
    try:
        with open("/proc/self/comm", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _im_cmd():
    """共通コマンド im（IBus と fcitx5 を自動で見分ける）の場所。無ければ空文字（IBus を直接呼ぶ）。"""
    return shutil.which("im") or ""


def _run_quiet(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def ime_state():
    """日本語入力の今の状態（あとで ime_set に渡せる文字列）。IBus はエンジン名、fcitx5 は fcitx5:on@アプリ名／fcitx5:off@アプリ名。無ければ空文字。"""
    im = _im_cmd()
    return _run_quiet(im, "state") if im else _run_quiet("ibus", "engine")


def ime_is_mozc(state):
    """Mozc を通して入力する状態か（元に戻す必要があるか）。"""
    return state.startswith("mozc") or state.startswith("fcitx5:on")


def ime_is_on(state):
    """Mozc が「あ」（変換する側）か。mozc-off と fcitx5:off は違う。"""
    return (state.startswith("mozc") and state != "mozc-off") or state.startswith("fcitx5:on")


def ime_set(state):
    im = _im_cmd()
    if im:
        _run_quiet(im, "set", state)
    elif state:
        _run_quiet("ibus", "engine", state)


def ime_plain():
    """配列そのまま（Mozc を通さない）にする。"""
    im = _im_cmd()
    if im:
        _run_quiet(im, "plain")
    else:
        _run_quiet("ibus", "engine", "xkb:jp::jpn")


def ime_off():
    """日本語入力を切る（IBus は mozc-off）。"""
    im = _im_cmd()
    if im:
        _run_quiet(im, "off")
    else:
        _run_quiet("ibus", "engine", "mozc-off")


def ibus_engine(name=None):
    """IBus の入力エンジン名を返す。name があれば先に切り替える。ibus が無ければ空文字（互換のために残す）。"""
    try:
        if name:
            subprocess.run(["ibus", "engine", name], capture_output=True)
        return subprocess.run(["ibus", "engine"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def load_history():
    try:
        with open(HISTORY, encoding="utf-8") as f:
            return [ln.rstrip("\n") for ln in f if ln.strip()]
    except OSError:
        return []


def save_history(line):
    hist = [h for h in load_history() if h != line] + [line]
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    with open(HISTORY, "w", encoding="utf-8") as f:
        f.write("\n".join(hist[-100:]) + "\n")


def suggest(text, spec):
    """入力中の文字列に対する候補 [(挿入する語, 説明)]。最後の語を置き換える。"""
    parts = text.split(" ")
    cur, first = parts[-1], parts[0]
    ext = spec.get("ext", {})                          # 拡張の命令 {名前: {"summary", "win": [位置引数ごとに窓か], "rep": 残りが窓か}}
    if len(parts) == 1:
        return [(c + " ", d) for c, d in SUBCOMMANDS if c.startswith(cur)] + \
               [(n + " ", e["summary"]) for n, e in ext.items() if n.startswith(cur)]
    prev = parts[-2]
    if first == "help" and len(parts) == 2:
        topics = [("api", tr("拡張で使える関数の一覧")), ("commands", tr("登録したコマンドの一覧")), ("sets", tr("セットの一覧")),
                  ("layouts", tr("型の一覧"))]
        return [(t + " ", d) for t, d in topics if t.startswith(cur)] + \
               [(c + " ", d) for c, d in SUBCOMMANDS if c.startswith(cur)] + \
               [(n + " ", e["summary"]) for n, e in ext.items() if n.startswith(cur)]
    if first == "nav":
        return [(d + " ", "") for d in ("next", "prev", "left", "right", "up", "down") if d.startswith(cur)]
    if first in ("run", "set") and len(parts) == 2:
        pool = spec.get("commands", {}) if first == "run" else spec.get("sets", {})
        return [(shlex.quote(n) + " ", (set_summary(c) if first == "set" else describe_command(c))[:40])
                for n, c in pool.items() if n.startswith(cur)]
    if first == "state" and len(parts) == 2:
        return [(a + " ", "") for a in STATE_ACTIONS if a.startswith(cur)]
    if first == "layout" and len(parts) == 2:
        return [(n + " ", f"{e}") for n, e in spec["layouts"].items() if n.startswith(cur)]
    if cur.startswith("-") and first in SIGNATURES:
        return [(p[1] + " ", p[3] if p[0] == "opt" else p[2]) for p in SIGNATURES[first][0]
                if p[0] in ("opt", "flag") and p[1].startswith(cur)]
    if cur.startswith("-") and first in ext:
        return [(p[1] + " ", p[-1]) for p in spec.get("ext_sig", {}).get(first, [[]])[0]
                if p[0] in ("opt", "flag") and p[1].startswith(cur)]
    wants_window = first in ("focus", "here") or prev in ("-w", "--window") or (first == "layout" and len(parts) > 2)
    if first in ext:                                   # 拡張の命令は、いま打っている位置の引数が窓なら
        k = len([t for t in parts[1:-1] if t and not t.startswith("-")])
        kinds = ext[first]["win"]
        wants_window = kinds[k] if k < len(kinds) else ext[first]["rep"]
    if wants_window and cur.lower().startswith("@class:"):    # @class: の後は、いま開いている窓のクラス名
        classes = dict.fromkeys(w["cls"] for w in spec["windows"] if w["cls"])
        return [(f"@class:{c} ", tr("【複数】このクラスの窓すべて")) for c in classes if f"@class:{c}".lower().startswith(cur.lower())]
    if wants_window:
        low = cur.lower().lstrip("!")
        ats = [(s, d) for s, d in AT_SELECTORS if s.startswith(cur)] if cur.startswith("@") or not cur else []
        return [(shlex.quote(w["sel"]) + " ", f"{w['cls']} — {w['title']}") for w in spec["windows"]
                if not cur.startswith("@") and (not low or low in (w["cls"] + " " + w["title"]).lower())] + \
               [(s if s.endswith(":") else s + " ", d) for s, d in ats]
    if not cur and first in SIGNATURES:               # 空白の後に何も打っていないときも、使える指定（-w など）を出す（すでに打ったものは除く）
        return [(p[1] + " ", p[3] if p[0] == "opt" else p[2]) for p in SIGNATURES[first][0]
                if p[0] in ("opt", "flag") and p[1] not in parts]
    return []


def run_prompt():
    """コマンドを 1 行打つ小さな窓。結果は 1 行の JSON（{"act": "run", "line": ...} か cancel）で標準出力へ。"""
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    spec = json.load(sys.stdin)
    SIGNATURES.update({n: (parts, summary) for n, (parts, summary) in spec.get("ext_sig", {}).items()})
    hist, hist_pos = spec.get("history", []), [None]

    class App(Adw.Application):
        def __init__(self):
            super().__init__(application_id=PROMPT_APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)

        def finish(self, act):
            print(json.dumps(act), flush=True)
            self.quit()

        def do_activate(self):
            try:
                from gi.repository import GLibUnix
                GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (self.quit(), False)[1])
            except ImportError:
                GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (self.quit(), False)[1])
            entry = Gtk.Entry(hexpand=True, text=spec.get("initial", ""),
                              placeholder_text=tr("例: layout quad / focus firefox / nav right"))
            entry.set_position(-1)
            row = Gtk.Box(spacing=8, margin_top=10, margin_start=12, margin_end=12)
            prefix = Gtk.Label(label="win")
            prefix.add_css_class("heading")
            row.append(prefix)
            row.append(entry)
            sugg = Gtk.ListBox(selection_mode=Gtk.SelectionMode.BROWSE, can_focus=False, margin_top=6,
                               margin_start=12, margin_end=12)
            sugg.add_css_class("boxed-list")
            sugg_box = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=sugg,
                                          min_content_height=215, max_content_height=215)
            shown = []                      # 表示中の候補 [(挿入する語, 説明)]

            sig = Gtk.Label(xalign=0, wrap=True, use_markup=True, visible=False, margin_top=6, margin_start=14, margin_end=14)
            sig.add_css_class("caption")

            def refresh(*_):
                while (r := sugg.get_row_at_index(0)) is not None:
                    sugg.remove(r)
                shown[:] = suggest(entry.get_text(), spec)
                markup = signature_markup(entry.get_text())     # 打っている命令の書式（いま打っている引数は太字）
                sig.set_markup(markup or "")
                sig.set_visible(bool(markup))
                for ins, desc in shown:
                    box = Gtk.Box(spacing=12, margin_top=4, margin_bottom=4, margin_start=10, margin_end=10)
                    a = Gtk.Label(label=ins.strip(), xalign=0, width_chars=14)
                    b = Gtk.Label(label=desc, xalign=0, hexpand=True, ellipsize=3, max_width_chars=50)
                    b.add_css_class("dim-label")
                    box.append(a)
                    box.append(b)
                    r = Gtk.ListBoxRow(can_focus=False)
                    r.set_child(box)
                    sugg.append(r)
                if shown:
                    sugg.select_row(sugg.get_row_at_index(0))
                sugg_box.get_vadjustment().set_value(0)

            def show_selected():
                """選んでいる候補が、欄の中で見えるようにスクロールする（ListBox は、選んだ行までは動かしてくれない）。"""
                sel = sugg.get_selected_row()
                adj = sugg_box.get_vadjustment()
                ok, rect = sel.compute_bounds(sugg) if sel is not None else (False, None)
                if ok:
                    top, bottom = rect.get_y(), rect.get_y() + rect.get_height()
                    if top < adj.get_value():
                        adj.set_value(top)
                    elif bottom > adj.get_value() + adj.get_page_size():
                        adj.set_value(bottom - adj.get_page_size())
                return False

            def move(d):
                if shown:
                    sel = sugg.get_selected_row()
                    sugg.select_row(sugg.get_row_at_index(((sel.get_index() if sel else 0) + d) % len(shown)))
                    GLib.idle_add(show_selected)

            def complete():
                sel = sugg.get_selected_row()
                if not shown or sel is None:
                    return
                parts = entry.get_text().split(" ")
                parts[-1] = shown[sel.get_index()][0]
                entry.set_text(" ".join(parts))
                entry.set_position(-1)

            def history(d):
                if not hist:
                    return
                pos = len(hist) if hist_pos[0] is None else hist_pos[0]
                pos = max(0, min(len(hist), pos + d))
                hist_pos[0] = pos
                entry.set_text(hist[pos] if pos < len(hist) else "")
                entry.set_position(-1)

            entry.connect("changed", refresh)
            entry.connect("activate", lambda _e: self.finish({"act": "run", "line": entry.get_text()}))

            def on_key(_c, keyval, _kc, state):
                name = Gdk.keyval_name(keyval)
                ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
                if name == "Escape":
                    self.finish({"act": "cancel"})
                elif name in ("Tab", "ISO_Left_Tab"):
                    complete()
                elif ctrl and name == "Up":
                    history(-1)
                elif ctrl and name == "Down":
                    history(1)
                elif name == "Down" or (ctrl and name == "n"):
                    move(1)
                elif name == "Up" or (ctrl and name == "p"):
                    move(-1)
                else:
                    return False
                return True

            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_bottom=10)
            outer.append(row)
            outer.append(sig)
            outer.append(sugg_box)
            for text, css in ((spec.get("error"), "error"), (spec.get("info"), "monospace")):
                if text:
                    lab = Gtk.Label(label=text, xalign=0, wrap=True, margin_top=8, margin_start=14, margin_end=14,
                                    selectable=True)
                    lab.add_css_class(css)
                    outer.append(lab)
            hint = Gtk.Label(label=tr("Tab 補完 ・ ↑↓ 候補 ・ Ctrl+↑↓ 履歴 ・ Enter 実行 ・ Esc 閉じる"), margin_top=8)
            hint.add_css_class("dim-label")
            hint.add_css_class("caption")
            outer.append(hint)
            header = Adw.HeaderBar(title_widget=Gtk.Label(label=tr("窓の操作")), show_end_title_buttons=False)
            view = Adw.ToolbarView(content=outer)
            view.add_top_bar(header)
            win = Adw.ApplicationWindow(application=self, title="win-prompt", default_width=640, content=view)
            ctrl = Gtk.EventControllerKey()
            ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            ctrl.connect("key-pressed", on_key)
            win.add_controller(ctrl)
            win.connect("close-request", lambda _w: (self.finish({"act": "cancel"}), True)[1])
            refresh()
            win.present()
            entry.grab_focus_without_selecting()

    run_with_ascii_input(lambda: App().run([]))


def run_inline(argv):
    """win の命令をこのプロセスで実行し、(終了コード, 標準出力, 標準エラー) を返す。"""
    from .cli import main        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = main(argv)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
    return rc or 0, out.getvalue(), err.getvalue()


def cmd_prompt_gtk(args):
    """1 行の入力欄（GTK）。win prompt の既定。"""
    from .ext import ext_spec        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
    wc = WindowCalls()
    cfg = load_config()
    all_windows = normal_windows(wc)
    spec = {"layouts": cfg["layouts"], "commands": load_commands(), "sets": load_sets(), "history": load_history(), "initial": "",
            **ext_spec(),
            "error": None, "info": None,
            "windows": [{"sel": selector_for(w, all_windows), "cls": w.get("wm_class") or "",
                         "title": (w.get("title") or "")[:60]} for w in reversed(all_windows)]}
    while True:
        proc = subprocess.Popen([sys.executable, WIN_BIN, "_prompt"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        proc.stdin.write(json.dumps(spec))
        proc.stdin.close()
        center_and_focus(wc, proc, PROMPT_APP_ID)
        out = proc.stdout.read()
        proc.wait()
        res = None
        for line in reversed(out.strip().splitlines()):
            try:
                res = json.loads(line)
                break
            except ValueError:
                continue
        if not res or res.get("act") != "run" or not res.get("line", "").strip():
            return 0
        line = res["line"].strip()
        try:
            argv = shlex.split(line)
        except ValueError as e:
            spec.update(initial=line, error=tr("引用符が閉じていません: {0}").format(e), info=None)
            continue
        if argv and argv[0] == "win":
            argv = argv[1:]
        problem = None
        if not argv:
            return 0
        if argv[0] == "prompt":
            problem = tr("ここでは prompt は使えません")
        if problem:
            spec.update(initial=line, error=problem, info=None)
            continue
        argv, line = bare_window_to_pick(argv, line)
        time.sleep(0.25)            # 入力窓が閉じて、元の窓にフォーカスが戻るのを待つ
        rc, so, se = run_inline(argv)
        if rc == 0:
            if not (argv[0] == "layout" and any(a in ("-i", "--interactive") for a in argv)):
                save_history(line)
            if argv[0] in SHOW_OUTPUT and so.strip():
                if argv[0] == "list":
                    so = "\n".join(f"{'*' if w.get('focus') else ' '} {(w.get('wm_class') or '')[:22]:<22} "
                                    f"{(w.get('title') or '')[:48]}" for w in reversed(normal_windows(wc)))
                spec.update(initial="", error=None, info=so.rstrip())
                spec["history"] = load_history()
                continue
            return 0
        msg = (se.strip() or so.strip() or tr("失敗しました（終了コード {0}）").format(rc))
        spec.update(initial=line, error=msg, info=None)


NVPROMPT_LUA = tr(r'''-- win prompt（nvim の入力欄）。win が開くたびに書き出すファイルなので、編集しても上書きされます。
local buf = vim.api.nvim_get_current_buf()
vim.bo[buf].filetype = "win"
vim.bo[buf].swapfile = false
vim.lsp.start({ name = "win", cmd = { vim.g.win_python, vim.g.win_bin, "lsp" }, root_dir = vim.fn.fnamemodify(vim.g.win_result, ":h") },
  { bufnr = buf })

local function finish(line)
  local f = io.open(vim.g.win_result, "w")
  if f then
    f:write(line or "")
    f:close()
  end
  vim.cmd("qall!")
end

-- Enter: カーソルのある行を実行する（# の行・空の行では何もしない）
vim.keymap.set({ "n", "i" }, "<CR>", function()
  local line = vim.api.nvim_get_current_line()
  if line:match("^%s*$") or line:match("^%s*#") then
    return
  end
  finish(line)
end, { buffer = buf, desc = "win: この行を実行" })
-- ノーマルモードの Esc・q、どのモードでも Ctrl+C: 何もせずに閉じる
vim.keymap.set("n", "<Esc>", function() finish(nil) end, { buffer = buf, desc = "win: 閉じる" })
vim.keymap.set("n", "q", function() finish(nil) end, { buffer = buf, desc = "win: 閉じる" })
vim.keymap.set({ "n", "i" }, "<C-c>", function() finish(nil) end, { buffer = buf, desc = "win: 閉じる" })

-- 書式・説明の浮き窓。nvim 標準の表示は markdown の構文解析器を使い、入っていないと失敗するので、普通の文字で出す
local float = {}
local function close_float()
  if float.win and vim.api.nvim_win_is_valid(float.win) then
    vim.api.nvim_win_close(float.win, true)
  end
  float.win = nil
end
local function show_float(lines, active, at_top)
  close_float()
  if not lines or #lines == 0 then
    return
  end
  local width = 10
  for _, l in ipairs(lines) do
    width = math.max(width, vim.fn.strdisplaywidth(l))
  end
  width = math.min(width, vim.o.columns - 4)
  local b = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_buf_set_lines(b, 0, -1, false, lines)
  if active then
    vim.api.nvim_buf_set_extmark(b, vim.api.nvim_create_namespace("win_prompt"), active, 0,
      { end_row = active + 1, hl_group = "Search", hl_eol = true })
  end
  local below = vim.fn.winline() < vim.api.nvim_win_get_height(0) - #lines - 1
  local pos = at_top and { relative = "editor", row = 0, col = vim.o.columns - width - 2 }      -- 補完の一覧と重ならない、右上
    or { relative = "cursor", row = below and 1 or -math.min(#lines, 10) - 2, col = 0 }
  float.win = vim.api.nvim_open_win(b, false, vim.tbl_extend("force", pos, {
    width = width, height = math.min(#lines, 10), style = "minimal", border = "rounded", focusable = false, zindex = 60,
  }))
end
local function request(method, cb)
  local client = vim.lsp.get_clients({ bufnr = buf, name = "win" })[1]
  if not client then
    return
  end
  local params = vim.lsp.util.make_position_params(0, client.offset_encoding)
  client:request(method, params, function(err, result)
    if not err then
      cb(result)
    end
  end, buf)
end
local function signature()
  request("textDocument/signatureHelp", function(r)
    local sig = r and r.signatures and r.signatures[1]
    if not sig then
      close_float()
      return
    end
    local lines, active = { sig.label .. "　" .. (sig.documentation or "") }, nil
    for k, prm in ipairs(sig.parameters or {}) do
      table.insert(lines, prm.label .. "　" .. (prm.documentation or ""))
      if r.activeParameter == k - 1 then
        active = k
      end
    end
    show_float(lines, active, true)
  end)
end
local function hover()
  request("textDocument/hover", function(r)
    local text = r and r.contents and r.contents.value
    if not text then
      return
    end
    local lines = {}
    for _, l in ipairs(vim.split(text, "\n")) do
      if not l:match("^```") then
        table.insert(lines, (l:gsub("`", "")))
      end
    end
    show_float(lines)
  end)
end
vim.keymap.set("n", "K", hover, { buffer = buf, desc = "win: 説明" })
vim.api.nvim_create_autocmd({ "InsertLeave", "CursorMoved" }, { buffer = buf, callback = close_float })

-- 空白を打ったら、引数の書式を出し、補完の候補も出す（行が空・コメントなら閉じる）
vim.api.nvim_create_autocmd("TextChangedI", {
  buffer = buf,
  callback = function()
    local col = vim.api.nvim_win_get_cursor(0)[2]
    local line = vim.api.nvim_get_current_line()
    if line:match("^%s*$") or line:match("^%s*#") then
      close_float()
    elseif col > 0 and line:sub(col, col) == " " then
      signature()
      local ok, blink = pcall(require, "blink.cmp")
      if ok then
        vim.schedule(function() pcall(blink.show) end)
      end
    end
  end,
})

-- 最後の行（入力の行）の末尾から、挿入モードで始める
vim.api.nvim_win_set_cursor(0, { vim.api.nvim_buf_line_count(buf), 0 })
vim.cmd("startinsert!")
if vim.g.win_error and vim.g.win_error ~= "" then
  vim.schedule(function() vim.api.nvim_echo({ { vim.g.win_error, "ErrorMsg" } }, false, {}) end)
end
''')


def nvim_prompt_available():
    if not shutil.which("nvim"):
        return False
    try:
        gi.require_version("Vte", "2.91")
        return True
    except ValueError:
        return False


def nvim_prompt_once(wc, initial, notes, error):
    """nvim の入力欄を 1 回開き、実行する行（取り消しなら None）を返す。上に履歴、その下に notes（# の行）、最後が入力の行。"""
    d = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "win")
    os.makedirs(d, mode=0o700, exist_ok=True)
    text_path, result_path, lua_path = (os.path.join(d, n) for n in ("prompt.win", "prompt.result", "prompt.lua"))
    hist = load_history()[-30:]                           # 古い順（ファイルも古い順。新しいものほど入力の行の近く）
    lines = hist + [f"# {n}" for n in notes] + [initial]
    with open(text_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(lua_path, "w", encoding="utf-8") as f:
        f.write(NVPROMPT_LUA)
    with contextlib.suppress(FileNotFoundError):
        os.remove(result_path)
    proc = subprocess.Popen([sys.executable, WIN_BIN, "_nvprompt", text_path, result_path, lua_path, error or ""],
                            stdin=subprocess.DEVNULL)
    center_and_focus(wc, proc, NVPROMPT_APP_ID)
    proc.wait()
    try:
        with open(result_path, encoding="utf-8") as f:
            line = f.read().strip()
    except FileNotFoundError:
        return None
    return line or None


def run_nvprompt(text_path, result_path, lua_path, error):
    """nvim を中に持つ小さな窓（GTK3 + VTE）。nvim が終わったら閉じる。"""
    gi.require_version("Gtk", "3.0")
    gi.require_version("Vte", "2.91")
    from gi.repository import Gtk, Vte

    GLib.set_prgname(NVPROMPT_APP_ID)                    # GTK3 の窓のクラス名（Wayland の app id）はプログラム名になる
    app = Gtk.Application(application_id=NVPROMPT_APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)

    def activate(a):
        win = Gtk.ApplicationWindow(application=a, title="win prompt")
        term = Vte.Terminal()
        term.set_size(100, 20)
        win.add(term)
        argv = ["nvim", "--cmd", f"let g:win_bin = {json.dumps(WIN_BIN)} | let g:win_python = {json.dumps(sys.executable)}"
                f" | let g:win_result = {json.dumps(result_path)} | let g:win_error = {json.dumps(error)}",
                "-c", f"luafile {lua_path}", text_path]
        term.spawn_async(Vte.PtyFlags.DEFAULT, os.path.dirname(text_path), argv, None, GLib.SpawnFlags.SEARCH_PATH,
                         None, None, -1, None, None)
        term.connect("child-exited", lambda *_: a.quit())
        win.connect("delete-event", lambda *_: (a.quit(), False)[1])
        win.show_all()
        term.grab_focus()

    app.connect("activate", activate)
    run_with_ascii_input(lambda: app.run([]))


def bare_window_to_pick(argv, line):
    """-w で窓を指定せずに Enter を押したときは、窓の選択画面で選ぶ（@pick と同じ）。(argv, 履歴に残す行) を返す。"""
    if argv and argv[-1] in ("-w", "--window"):
        return argv + ["@pick"], line.rstrip() + " @pick"
    return argv, line


def prompt_execute(wc, line):
    """入力欄で打った 1 行を実行する。("done", None)・("show", 出力)・("error", 説明) のどれかを返す。"""
    try:
        argv = shlex.split(line)
    except ValueError as e:
        return "error", tr("引用符が閉じていません: {0}").format(e)
    if argv and argv[0] == "win":
        argv = argv[1:]
    if not argv:
        return "done", None
    if argv[0] == "prompt":
        return "error", tr("ここでは prompt は使えません")
    argv, line = bare_window_to_pick(argv, line)
    time.sleep(0.25)            # 入力窓が閉じて、元の窓にフォーカスが戻るのを待つ
    rc, so, se = run_inline(argv)
    if rc == 0:
        if not (argv[0] == "layout" and any(a in ("-i", "--interactive") for a in argv)):
            save_history(line)
        if argv[0] in SHOW_OUTPUT and so.strip():
            if argv[0] == "list":
                so = "\n".join(f"{'*' if w.get('focus') else ' '} {(w.get('wm_class') or '')[:22]:<22} "
                                f"{(w.get('title') or '')[:48]}" for w in reversed(normal_windows(wc)))
            return "show", so.rstrip()
        return "done", None
    return "error", "\n".join(l.removeprefix("win: ") for l in (se.strip() or so.strip() or tr("失敗しました（終了コード {0}）").format(rc)).splitlines())


def cmd_prompt(args):
    from .ext import EXT_ERRORS, load_extensions        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
    if not getattr(args, "nvim", False) or not nvim_prompt_available():
        return cmd_prompt_gtk(args)
    wc = WindowCalls()
    initial, notes, error = "", [], None
    load_extensions()
    notes = [tr("読み込めなかった拡張: {0}: {1}").format(os.path.basename(f), m) for f, m in EXT_ERRORS]
    while True:
        line = nvim_prompt_once(wc, initial, notes, error)
        if not line:
            return 0
        kind, payload = prompt_execute(wc, line)
        if kind == "done":
            return 0
        if kind == "show":
            initial, notes, error = "", payload.splitlines(), None
        else:
            initial, notes, error = line, [f"✗ {l}" for l in payload.splitlines()], payload.splitlines()[0]

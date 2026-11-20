"""設定の保存（commands.toml・sets.toml）。"""

import functools
import json
import os
import re
import shlex
import tomllib
from gi.repository import GLib
from gi.repository import Gio

from .common import WinError
from .shortcuts import WIN_BIN, command_slug, kb_list, kb_remove, kb_set, set_slug


COMMANDS = os.environ.get("WIN_COMMANDS") or os.path.expanduser("~/.config/win/commands.toml")      # 環境変数は試験用の差し替え


SETS = os.environ.get("WIN_SETS") or os.path.join(os.path.dirname(COMMANDS), "sets.toml")


TOML_HEADER = "# win config が書き換えます。手で編集してもかまいません（コメントは、保存し直すと消えます）。\n"


def _toml_key(k):
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k, ensure_ascii=False)


def _toml_val(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_val(x) for x in v) + "]"
    raise TypeError(f"TOML にできない値: {v!r}")


def _is_aot(v):
    return isinstance(v, list) and bool(v) and all(isinstance(x, dict) for x in v)


def toml_dumps(data, path=()):
    """小さな TOML の書き出し（文字列・数・真偽・それらの配列・表・表の配列。tomllib で読み返せる）。"""
    lines = [f"{_toml_key(k)} = {_toml_val(v)}" for k, v in data.items() if not isinstance(v, dict) and not _is_aot(v)]
    for k, v in data.items():
        sub = path + (k,)
        name = ".".join(_toml_key(x) for x in sub)
        if isinstance(v, dict):
            lines += ["", f"[{name}]", toml_dumps(v, sub)]
        elif _is_aot(v):
            for item in v:
                lines += ["", f"[[{name}]]", toml_dumps(item, sub)]
    return "\n".join(lines).strip("\n")


def write_toml(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(TOML_HEADER + "\n" + toml_dumps(data) + "\n")
    os.replace(tmp, path)


def _load_table(path, key):
    try:
        with open(path, "rb") as f:
            return tomllib.load(f).get(key, {})
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as e:
        raise WinError(f"{path} が読めません: {e}")


def load_commands():
    """{名前: {"type": "win"|"shell", ...}}。ファイルが無ければ空。"""
    migrate_sets()
    return _load_table(COMMANDS, "commands")


def save_commands(cmds):
    write_toml(COMMANDS, {"commands": cmds})


def load_sets():
    """{名前: {"type": "win", "run": …} か旧形式 {"type": "arrange", "windows": […]}}。ファイルが無ければ空。"""
    migrate_sets()
    return _load_table(SETS, "sets")


def save_sets(sets):
    write_toml(SETS, {"sets": sets})


def migrate_sets():
    """commands.toml に残っているセット（kind = "set" と旧形式 type = "arrange"）を sets.toml へ移す。付けたキーも付け替える。"""
    from .sets import is_set        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
    cmds = _load_table(COMMANDS, "commands")
    moving = {n: c for n, c in cmds.items() if is_set(c)}
    if not moving:
        return
    sets, renamed = _load_table(SETS, "sets"), {}
    for n, c in moving.items():
        new, i = n, 2
        while new in sets:                                    # 同じ名前のセットがあれば「名前 (2)」にする
            new, i = f"{n} ({i})", i + 1
        sets[new] = {k: v for k, v in c.items() if k != "kind"}
        renamed[n] = new
    save_sets(sets)                                           # 先にセット側へ書いてから消す（途中で止まっても失わない）
    save_commands({n: c for n, c in cmds.items() if n not in moving})
    try:
        kbs = {e["slug"]: e for e in kb_list()}
    except Exception:                                         # GNOME の設定に触れない環境（試験など）
        return
    for old, new in renamed.items():
        e = kbs.get(command_slug(old))
        if e:
            kb_remove(command_slug(old))
            kb_set(set_slug(new), name=f"win set: {new}", command=f"{WIN_BIN} set {shlex.quote(new)}", binding=e["binding"])


def win_lines(text):
    """win の命令の並び（1 行に 1 つ）から、空行と # で始まる行を除いた行のリスト。"""
    return [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]


def _check_win_one(line):
    from .prompt import SUBCOMMANDS        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
    from .ext import EXT, load_extensions        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
    try:
        argv = shlex.split(line)
    except ValueError as e:
        return f"引用符が閉じていません: {e}"
    if argv and argv[0] == "win":
        argv = argv[1:]
    if not argv:
        return "命令が空です"
    if argv[0] in ("run", "config", "set"):
        return f"「{argv[0]}」は、コマンドの中では使えません（無限に呼び合うのを防ぐため）"
    load_extensions()
    if argv[0] not in {c for c, _ in SUBCOMMANDS} | {"prompt"} | set(EXT):
        return f"知らない命令です: {argv[0]}"
    return None


def check_win_line(text):
    """win の命令（複数行可）として正しいか。問題があれば説明、なければ None。"""
    lines = win_lines(text)
    if not lines:
        return "命令が空です"
    for i, line in enumerate(lines, 1):
        err = _check_win_one(line)
        if err:
            return f"{i} 行目: {err}" if len(lines) > 1 else err
    return None


# 各命令の書式（打っている途中の引数の説明に使う）: 命令 → (書式の部品, {部品: 説明})。
# 部品は ("位置", 名前) か ("opt", "-w") のような印。位置の部品は順に対応し、最後が [窓 …] のように繰り返すものは "rep"。
WIN_OPT = ("opt", "-w", "窓", "対象の窓（クラス・題名の一部、@left・@prev など）。省くと前面の窓")


MONITOR_HELP = "基準にするモニタ（primary・current・eDP-1 など）。省くと、いまの窓があるモニタ"


MON_OPT = ("opt", "--monitor", "画面", "基準のモニタ（primary・current・eDP-1 など）。省くと、いまの窓があるモニタ")


SIGNATURES = {
    "here": ([("pos", "窓", "窓の指定（クラス・題名の一部）か !コマンド。省くと小窓で選ぶ", True), MON_OPT], "選んだ窓を今の窓と同じ位置・大きさにして前面へ"),
    "group": ([("pos", "動作", "list（既定）・new・add・remove・delete・next・prev・show・select・place・from-stack", True),
               ("rep", "引数", "名前・窓の指定・タイルの番号（動作による）。名前を省くと、前面の窓の属するグループ", True), MON_OPT],
              "窓のグループ（名前つき・保存つき。1 つの枠を共有し、タブのように切り替える）"),
    "desktop": ([("pos", "デスクトップ", "デスクトップの番号（1 から）・next・prev・list。省くと、いまのデスクトップを表示", True)],
                "デスクトップ（ワークスペース）の表示・切り替え。切り替えには拡張 win-helper@local が要る"),
    "stack": ([("pos", "タイル", "タイルの番号（0 は前面の窓のいるタイル）", True),
               ("pos", "動作", "next（次の層、既定）・prev（前の層）・list（小窓で選ぶ）", True), MON_OPT],
              "同じ位置に重なった窓（層）を、次・前へ切り替える"),
    "place": ([("pos", "置き先", "タイルの番号（0 は前面の窓の位置）か free（いちばん広い空きスペース）", True),
               ("pos", "窓", "置く窓（クラス・題名の一部）か !コマンド。省くと小窓で選ぶ。小窓では ←→ で置き先を動かせる", True),
               ("flag", "--min", "置き先にあった元の窓を最小化する"), MON_OPT], "置き先（番号のタイル・前面の窓・空きスペース）に、選んだ窓を重ねる"),
    "focus": ([("pos", "窓", "窓の指定（クラス・題名の一部）か、5 桁以上の ID", False)], "窓を前面に出す"),
    "nav": ([("pos", "方向", "next / prev（いまの並びの番号順）、left / right / up / down", False)], "フォーカスを次・前・上下左右の窓へ移す"),
    "layout": ([("pos", "型", "型の名前（win layouts）か式（例: v(1,h(1,1))。略記 1,2:1/1/1,1 も可）。省くと小窓で選ぶ", True),
                ("rep", "窓", "タイル順の窓。- は空け、!コマンド は新しく起動", True),
                ("opt", "--gap", "隙間", "タイル間の隙間（px）"), ("flag", "-n", "動かさず、割り当てだけ表示"),
                ("flag", "--pick", "タイルごとに窓の一覧を自動で出す"), ("flag", "-i", "タイルごとに窓を絞り込んで選ぶ"), MON_OPT],
               "窓を分割配置する"),
    "pick": ([("flag", "--id", "前面に出さず、選んだ窓の ID だけを表示"), MON_OPT], "窓の一覧から選んで前面に出す"),
    "move": ([WIN_OPT, ("pos", "x", "左端の位置（px）", False), ("pos", "y", "上端の位置（px）", False)], "窓を移動する"),
    "size": ([WIN_OPT, ("pos", "幅", "幅（px）", False), ("pos", "高さ", "高さ（px）", False)], "窓の大きさを変える"),
    "state": ([WIN_OPT, ("pos", "動作", "max / unmax / min / unmin / above / unabove", False)], "最大化・最小化・常に手前"),
    "max": ([WIN_OPT], "窓を最大化する"), "unmax": ([WIN_OPT], "最大化を戻す"),
    "min": ([WIN_OPT], "窓を最小化する"), "unmin": ([WIN_OPT], "最小化を戻す"), "close": ([WIN_OPT], "窓を閉じる"),
    "list": ([("flag", "-a", "通常の窓以外も表示")], "窓の一覧を表示する"),
    "layouts": ([], "型の一覧を表示する"),
    "run": ([("pos", "名前", "登録したコマンド・保存した並び", False)], "登録したコマンドを実行する"),
    "save": ([("pos", "名前", "保存する名前（win set 名前 で呼べる）", False),
              ("opt", "--state", "状態", "firefox / terminal / all。タブの URL・作業ディレクトリも保存（選んだときだけ）"), MON_OPT],
             "いまの窓の並びを、型と窓の列として保存する"),
    "term": ([("rep", "作業ディレクトリ", "タブごとの作業ディレクトリ", True)], "端末をタブつきで開く"),
    "browse": ([("rep", "URL", "開く URL（最初の 1 つで窓を開き、残りはタブ）", False)], "Firefox を URL のタブつきで開く"),
    "set": ([("pos", "名前", "セットの名前。省くと、絞り込みの小窓が開く", True), MON_OPT], "保存した並び（セット）を適用する"),
}


def signature_parts(line):
    """入力中の 1 行（先頭の win は省略可）の書式。{"cmd", "summary", "items": [(表示, 名前, 説明)], "active": いま打っている部品の名前}。
    命令が分からなければ None。"""
    tokens = line.lstrip().split(" ")
    if tokens[0] == "win":
        tokens = tokens[1:]
    if len(tokens) < 2 or tokens[0] not in SIGNATURES:
        return None
    cmd, rest = tokens[0], tokens[1:]
    parts, summary = SIGNATURES[cmd]
    opt_value = {p[1] for p in parts if p[0] == "opt"}
    positional, skip = 0, False                       # 入力済みの位置引数の数
    for tok in rest[:-1]:
        if skip:
            skip = False
        elif tok in opt_value:
            skip = True
        elif not tok.startswith("-"):
            positional += 1
    cur = rest[-1]
    active = None                                     # いま打っている部品（名前）
    if len(rest) >= 2 and rest[-2] in opt_value and not skip_flag_value(rest[:-1], opt_value):
        active = rest[-2]
    elif not cur.startswith("-"):
        pos_parts = [p for p in parts if p[0] in ("pos", "rep")]
        if pos_parts:
            last = pos_parts[-1]
            active = last[1] if positional >= len(pos_parts) and last[0] == "rep" else \
                (pos_parts[positional][1] if positional < len(pos_parts) else None)
    items = []
    for p in parts:
        if p[0] == "pos":
            label, desc, optional = p[1], p[2], p[3]
            text = f"[{label}]" if optional else label
        elif p[0] == "rep":
            label, desc = p[1], p[2]
            text = f"[{label} …]"
        elif p[0] == "opt":
            label, desc = p[1], p[3]
            text = f"[{p[1]} {p[2]}]"
        else:
            label, desc = p[1], p[2]
            text = f"[{p[1]}]"
        items.append((text, label, desc))
    return {"cmd": cmd, "summary": summary, "items": items, "active": active}


def signature_markup(line):
    """入力中の 1 行に対する、書式と引数の説明（Pango マークアップ）。命令が分からなければ None。"""
    esc = lambda t: GLib.markup_escape_text(t)
    sp = signature_parts(line)
    if sp is None:
        return None
    shown, lines = [], []
    for text, label, desc in sp["items"]:
        on = label == sp["active"]
        shown.append(f"<b><u>{esc(text)}</u></b>" if on else esc(text))
        lines.append(("<b>" if on else "") + f"{esc(text)}　{esc(desc)}" + ("</b>" if on else ""))
    head = f"<tt>win {esc(sp['cmd'])} {' '.join(shown)}</tt>　{esc(sp['summary'])}"
    return head + ("\n" + "\n".join(lines) if lines else "")


def skip_flag_value(done, opt_value):
    """done の末尾の語が、すでに値を受け取った後のオプションかどうか（直前の語が値なら True）。"""
    return len(done) >= 2 and done[-2] in opt_value


def describe_command(c):
    t = c.get("type", "win")
    if t == "arrange":
        return f"並び {len(c.get('windows', []))} 枚"
    run = c.get("run", "")
    if t == "win":
        return " → ".join(win_lines(run))                 # 複数行は「→」でつなぐ（コメント行は除く）
    lines = [l for l in run.splitlines() if l.strip()]
    return lines[0] + (" …" if len(lines) > 1 else "") if lines else ""


@functools.cache
def app_for_class(cls):
    """窓のクラス名に当たるアプリ（.desktop の StartupWMClass・ID・実行ファイル名で照合）。なければ None。"""
    if not cls:
        return None
    low = cls.lower()
    for a in Gio.AppInfo.get_all():
        if not a.should_show():
            continue
        wm = (getattr(a, "get_startup_wm_class", lambda: None)() or "").lower()
        aid = (a.get_id() or "").lower()
        aid = aid[:-8] if aid.endswith(".desktop") else aid
        exe = os.path.basename(a.get_executable() or "").lower()
        if low in (wm, aid, exe):
            return a
    return None


def launch_for_class(cls):
    """窓のクラス名から、起動コマンド（.desktop の Exec）を探す。見つからなければ空文字。"""
    from .tilepick import app_commandline        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
    a = app_for_class(cls)
    return app_commandline(a) if a else ""


def icon_for_class(cls):
    """窓のクラス名に当たるアプリのアイコン（Gio.Icon の文字列）。なければ空文字。"""
    a = app_for_class(cls)
    icon = a.get_icon() if a else None
    return icon.to_string() if icon else ""


def icon_widget(Gtk, Gdk, icon, size=24, fallback="application-x-executable-symbolic"):
    """一覧の行に出すアイコン。名前・ファイル・Gio.Icon の文字列を受け、テーマになければ fallback。"""
    img = None
    if icon:
        try:
            if os.path.isabs(icon):
                img = Gtk.Image.new_from_file(icon)
            else:
                g = Gio.Icon.new_for_string(icon)
                theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
                if isinstance(g, Gio.FileIcon) or theme.has_gicon(g):
                    img = Gtk.Image.new_from_gicon(g)
        except GLib.Error:
            img = None
    if img is None:
        img = Gtk.Image.new_from_icon_name(fallback)
    img.set_pixel_size(size)
    return img

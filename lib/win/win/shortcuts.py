"""ショートカットの管理（GNOME のカスタムショートカット）。"""

import gi
import glob
import hashlib
import json
import os
import re
import sys
from gi.repository import GLib
from gi.repository import Gio

from .common import WinError



MK_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"


MK_ENTRY = MK_SCHEMA + ".custom-keybinding"


MK_BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"


WIN_BIN = os.path.abspath(sys.argv[0])  # 起動役（~/.local/bin/win）。子のプロセスもこれで起こし、解析結果のキャッシュを使わせる


# ショートカット画面のグループ（目的別。実装の種類 — 組み込み・拡張・コマンド・セット — では分けない）
G_MOVE, G_ARRANGE, G_SET, G_CMD, G_OTHER = "窓を選ぶ・移る", "窓を並べる・置く", "保存した並び（セット）", "コマンド", "その他の操作"


ACTION_GROUPS = [
    (G_MOVE, "窓を選んで前面に出す、フォーカスを移す操作です。"),
    (G_ARRANGE, "窓を型で並べる、置き先に重ねる操作です。"),
    (G_SET, "「セット」ページで保存した窓の並びを呼びます。"),
    (G_CMD, "「コマンド」ページで作ったコマンドを呼びます。"),
    (G_OTHER, "上のどれにも入らない、win の操作と拡張の命令です。"),
]


# win の標準の操作（slug, 表示名, 引数, 既定のキー, グループ）。slug は dconf の項目名
WIN_ACTIONS = [
    ("win-pick", "窓を選んで前面に出す", "pick", "<Super><Alt>p", G_MOVE),
    ("win-prompt", "コマンドを入力して窓を操作", "prompt", "<Super><Alt>semicolon", G_CMD),
    ("win-nav-prev-d", "前の窓へ（左手）", "nav prev", "<Super><Alt>d", G_MOVE),
    ("win-nav-next-f", "次の窓へ（左手）", "nav next", "<Super><Alt>f", G_MOVE),
    ("win-focus-prev", "直前の窓へ（交互に切り替える）", "focus @prev", "<Super><Alt>e", G_MOVE),
    ("win-focus-other-monitor", "反対側のモニタの窓へ", "focus @monitor:other", "<Super><Alt>q", G_MOVE),
    ("win-stack-prev", "重なった窓の、前の層を表示", "stack prev", "<Shift><Super><Alt>t", G_MOVE),
    ("win-group-prev", "グループの、前のメンバーを表示", "group prev", "<Shift><Super><Alt>g", G_MOVE),
    ("win-send", "窓を、別のモニタへ送る", "send", "<Super><Alt>v", G_ARRANGE),
    ("win-undo", "直前の操作を元に戻す", "undo", "<Super><Alt>z", G_ARRANGE),
    ("win-stack-next", "重なった窓の、次の層を表示", "stack next", "<Super><Alt>t", G_MOVE),
    ("win-stack-list", "重なった窓の層を、一覧から選ぶ", "stack list", "<Super><Alt>y", G_MOVE),
    ("win-group-next", "グループの、次のメンバーを表示", "group next", "<Super><Alt>g", G_MOVE),
    ("win-group-select", "グループのメンバーを、一覧から選ぶ", "group select", "<Super><Alt>u", G_MOVE),
    ("win-layout", "型を選んで窓を並べる", "layout", "<Super><Alt>m", G_ARRANGE),
    ("win-here", "選んだ窓を今の窓と同じ形にする", "here", "<Super><Alt>o", G_ARRANGE),
    ("win-set", "保存した並び（セット）を選んで適用", "set", "<Super><Alt>s", G_SET),
    ("win-nav-next", "次の窓へ（いまの並びの番号順）", "nav next", "<Super><Alt>j", G_MOVE),
    ("win-nav-prev", "前の窓へ（いまの並びの番号順）", "nav prev", "<Super><Alt>k", G_MOVE),
    *[(f"win-slot-{n}", f"{n} 番目のタイルの窓へ", f"focus @slot:{n}", f"<Super><Alt>{n}", G_MOVE) for n in range(1, 10)],
    ("win-config", "win の設定を開く", "config", "<Super><Alt>comma", G_OTHER),
]


def command_slug(name):
    """登録したコマンド名に対応する、ショートカットの項目名（名前が日本語でも使える固定長の形）。"""
    return "win-run-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]


def ext_slug(name):
    """拡張の命令に対応する、ショートカットの項目名。"""
    return "win-ext-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]


def set_slug(name):
    """セットの名前に対応する、ショートカットの項目名。"""
    return "win-set-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]


def kb_entry(slug):
    return Gio.Settings.new_with_path(MK_ENTRY, f"{MK_BASE}{slug}/")


def kb_slugs():
    return [p.rstrip("/").rsplit("/", 1)[-1] for p in Gio.Settings.new(MK_SCHEMA).get_strv("custom-keybindings")]


def kb_list():
    """[{slug, name, command, binding}]（GNOME の設定アプリの「カスタムショートカット」と同じもの）"""
    out = []
    for slug in kb_slugs():
        e = kb_entry(slug)
        out.append({"slug": slug, "name": e.get_string("name"), "command": e.get_string("command"),
                    "binding": e.get_string("binding")})
    return out


def kb_set(slug, name=None, command=None, binding=None):
    """項目を作る（無ければ）か、指定した値だけ更新する。反映まで数秒かかることがある（gsd-media-keys の再読み込み）。"""
    st = Gio.Settings.new(MK_SCHEMA)
    paths = st.get_strv("custom-keybindings")
    path = f"{MK_BASE}{slug}/"
    if path not in paths:
        st.set_strv("custom-keybindings", paths + [path])
    e = kb_entry(slug)
    for key, val in (("name", name), ("command", command), ("binding", binding)):
        if val is not None:
            e.set_string(key, val)
    Gio.Settings.sync()


def kb_remove(slug):
    st = Gio.Settings.new(MK_SCHEMA)
    path = f"{MK_BASE}{slug}/"
    st.set_strv("custom-keybindings", [p for p in st.get_strv("custom-keybindings") if p != path])
    e = kb_entry(slug)
    for key in ("name", "command", "binding"):
        e.reset(key)
    Gio.Settings.sync()


# ---------------------------------------------------------------- 宣言的なショートカット設定（shortcuts.toml）

SHORTCUTS_FILE = os.environ.get("WIN_SHORTCUTS") or os.path.expanduser("~/.config/win/shortcuts.toml")


def installed_bin():
    """導入した win の起動役のパス（ショートカットから呼ぶ実体）。"""
    p = os.path.expanduser("~/.local/bin/win")
    return p if os.path.exists(p) else WIN_BIN


def portable_command(cmd):
    """win の起動役で始まるコマンドを、導入先に依存しない `win …` に直す（ほかのコマンドはそのまま）。"""
    for b in {WIN_BIN, installed_bin(), os.path.expanduser("~/.local/bin/win")}:
        if cmd == b or cmd.startswith(b + " "):
            return "win" + cmd[len(b):]
    return cmd


def resolved_command(cmd):
    """`win …` を、導入した win の実体のパスにする。"""
    return installed_bin() + cmd[3:] if cmd == "win" or cmd.startswith("win ") else cmd


def _toml_str(s):
    return json.dumps(s, ensure_ascii=False)        # JSON の文字列は、TOML の基本文字列としてそのまま読める


def export_shortcuts():
    """いまの GNOME のカスタムショートカットすべてを、shortcuts.toml の文字列にする（slug の順）。"""
    out = ["# win のショートカット（GNOME のカスタムショートカット）。`win shortcuts apply` で GNOME に反映する。",
           "# command の先頭の `win` は、反映のとき、導入した win の実体に置き換わる。", ""]
    for e in sorted(kb_list(), key=lambda e: e["slug"]):
        out += ["[[shortcut]]", f"slug = {_toml_str(e['slug'])}", f"name = {_toml_str(e['name'])}",
                f"binding = {_toml_str(e['binding'])}", f"command = {_toml_str(portable_command(e['command']))}", ""]
    return "\n".join(out)


def apply_shortcuts(path=None, dry_run=False, prune=False):
    """shortcuts.toml を GNOME のカスタムショートカットに反映する。何度実行してもよい。変えた内容の説明のリストを返す。
    prune なら、ファイルにない win-* の項目を消す（それ以外の項目は、消さない）。dry_run なら、反映せずに説明だけ返す。"""
    import tomllib
    path = path or SHORTCUTS_FILE
    try:
        with open(path, "rb") as f:
            entries = tomllib.load(f).get("shortcut", [])
    except FileNotFoundError:
        raise WinError(f"ショートカットの設定がありません: {path}（作るには win shortcuts export）")
    except tomllib.TOMLDecodeError as e:
        raise WinError(f"ショートカットの設定を読めません: {path}: {e}")
    have = {e["slug"]: e for e in kb_list()}
    changes, seen = [], set()
    for i, e in enumerate(entries, 1):
        slug = e.get("slug")
        if not slug or not e.get("binding") or not e.get("command"):
            raise WinError(f"{i} 番目の項目に slug・binding・command が要ります: {e}")
        if slug in seen:
            raise WinError(f"slug が重複しています: {slug}")
        seen.add(slug)
        want = {"name": e.get("name") or slug, "binding": e["binding"], "command": resolved_command(e["command"])}
        cur = have.get(slug)
        if cur is None:
            changes.append(f"追加: {slug}  {want['binding']}  {portable_command(want['command'])}")
        else:
            diff = [k for k in ("binding", "command", "name") if cur[k] != want[k]]
            if not diff:
                continue
            changes.append(f"更新: {slug}  " + "・".join(f"{k}: {cur[k]!r} → {want[k]!r}" if k != "command" else
                                                         f"command: {portable_command(cur[k])!r} → {portable_command(want[k])!r}" for k in diff))
        if not dry_run:
            kb_set(slug, name=want["name"], command=want["command"], binding=want["binding"])
    if prune:
        for slug in have:
            if slug.startswith("win-") and slug not in seen:
                changes.append(f"削除: {slug}")
                if not dry_run:
                    kb_remove(slug)
    return changes


def _gtk():
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk, Gtk
    return Gtk, Gdk


def accel_parse(accel):
    Gtk, _ = _gtk()
    ok, key, mods = Gtk.accelerator_parse(accel)
    return (key, mods) if ok and key else None


def accel_norm(accel):
    """比べるための正規化（修飾キーの順序や表記の違いをそろえる）。読めなければ None。"""
    p = accel_parse(accel)
    return _gtk()[0].accelerator_name(*p) if p else None


# 日本語キーボードの特殊キー（キーシンボル名 → 画面での表記）。半角/全角は jp 配列で GRAVE（`）の位置にある
JP_KEYS = {"Henkan": "変換", "Muhenkan": "無変換", "Zenkaku_Hankaku": "半角/全角",
           "Hiragana_Katakana": "ひらがな/カタカナ"}


# 同じ物理キーを指す別名（日本語配列の半角/全角は `` ` `` と同じキー。GNOME の Above_Tab はこのキー）
PHYSICAL_KEY_ALIASES = {"above_tab": "grave", "zenkaku_hankaku": "grave", "kanji": "grave", "asciitilde": "grave"}


MOD_ALIASES = {"primary": "control", "ctrl": "control", "control": "control", "mod1": "alt", "alt": "alt",
               "mod4": "super", "super": "super", "shift": "shift", "meta": "meta", "hyper": "hyper"}


def accel_id(accel):
    """衝突を調べるための識別子（修飾キーの別名・順序と、同じ物理キーを指す別名をそろえる）。読めなければ None。
    GTK が解析できない表記（Above_Tab など）でも、文字列として比べられる。"""
    m = re.fullmatch(r"\s*((?:<[^<>]+>)*)\s*(\S*)\s*", accel or "")
    if not m or not m.group(2):
        return None
    mods = sorted({MOD_ALIASES.get(t.lower(), t.lower()) for t in re.findall(r"<([^<>]+)>", m.group(1))})
    key = m.group(2).lower()
    key = PHYSICAL_KEY_ALIASES.get(key, key)
    return "+".join(mods + [key])


def accel_label(accel):
    """画面に出す表記（例: Super+Alt+M、変換、Super+半角/全角）。空なら「（未割り当て）」。"""
    if not accel:
        return "（未割り当て）"
    p = accel_parse(accel)
    if not p:
        return accel
    Gtk, Gdk = _gtk()
    label = Gtk.accelerator_get_label(*p)
    jp = JP_KEYS.get(Gdk.keyval_name(p[0]) or "")
    bare = Gtk.accelerator_get_label(p[0], 0)
    if jp and label.endswith(bare):
        label = label[:len(label) - len(bare)] + jp
    return label


def scan_accelerators():
    """GNOME・拡張・自作のショートカットが使っているキー: {accel_id: [(使っている所, slug)]}。"""
    used = {}

    def add(accel, where, slug=None):
        n = accel_id(accel)
        if n:
            used.setdefault(n, []).append((where, slug))

    def scan_source(src, ids, label):
        for sid in ids:
            schema = src.lookup(sid, True)
            if schema is None:
                continue
            st = Gio.Settings.new_full(schema, None, None)
            for key in schema.list_keys():
                v = st.get_value(key)
                t = v.get_type_string()
                for acc in ([v.get_string()] if t == "s" else (list(v.get_strv()) if t == "as" else [])):
                    if "<" in acc:
                        summary = (schema.get_key(key).get_summary() or "").strip()      # GNOME が持つ説明文（英語のことが多い）
                        add(acc, f"{label}: {key}" + (f"（{summary}）" if summary else ""))

    default = Gio.SettingsSchemaSource.get_default()
    words = ("keybindings", "media-keys", "shell", "mutter", "wm", "settings-daemon")
    scan_source(default, [s for s in default.list_schemas(True)[0] if any(w in s for w in words)], "GNOME")
    for d in glob.glob(os.path.expanduser("~/.local/share/gnome-shell/extensions/*/schemas")):
        try:
            src = Gio.SettingsSchemaSource.new_from_directory(d, default, False)
        except GLib.Error:
            continue
        scan_source(src, src.list_schemas(False)[0], "拡張 " + d.split("/")[-2].split("@")[0])
    for e in kb_list():
        if e["binding"]:
            add(e["binding"], f"自作: {e['name'] or e['slug']}", e["slug"])
    return used


def accel_conflicts(used, accel, ignore_slug=None):
    """accel を、すでに使っている所の一覧（ignore_slug 自身は除く）。"""
    return [w for w, slug in used.get(accel_id(accel) or "", []) if ignore_slug is None or slug != ignore_slug]


def accel_note(accel):
    """Mozc オンの端末などで届かない可能性があるときの注意（なければ空文字）。確認済みで届くのは、
    Ctrl・Alt・Super のうち 2 つ以上と文字キーの組み合わせ（Shift なし）。"""
    p = accel_parse(accel)
    if not p:
        return "キーの形式が読めません"
    key, mods = p
    _, Gdk = _gtk()
    name = Gdk.keyval_name(key) or ""
    if not mods:
        return ""                                              # 修飾キーなし（変換キーなど）は判断しない
    n = sum(1 for m in (Gdk.ModifierType.CONTROL_MASK, Gdk.ModifierType.ALT_MASK, Gdk.ModifierType.SUPER_MASK) if mods & m)
    if len(name) == 1 and name.isalnum() and n >= 2 and not mods & Gdk.ModifierType.SHIFT_MASK:
        return ""
    return ("Mozc オンの端末などで届かないことがあります。確認済みで届く形は、Ctrl・Alt・Super のうち 2 つ以上と"
            "文字キーの組み合わせ（Shift なし）です。")

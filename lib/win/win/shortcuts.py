"""ショートカットの管理（GNOME のカスタムショートカット）。"""

import gi
import glob
import hashlib
import os
import re
import sys
from gi.repository import GLib
from gi.repository import Gio



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
    ("win-stack-next", "重なった窓の、次の層を表示", "stack next", "<Super><Alt>t", G_MOVE),
    ("win-stack-list", "重なった窓の層を、一覧から選ぶ", "stack list", "<Super><Alt>y", G_MOVE),
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


# 変換＋キー: keyd（/etc/keyd/default.conf）の [win] レイヤーが、変換を押しながらのキーを Super+Alt+キー にする。
# GNOME 側は Super+Alt+キー のショートカットとして登録するので、keyd さえ全キー分あれば、あとは sudo なしで付け外しできる。
KEYD_CONF = "/etc/keyd/default.conf"


KEYD_GENERATED = os.path.expanduser("~/.config/win/keyd-default.conf")


# 変換＋キーにできるキー: keyd のキー名 → (GNOME のキー名, 表示)。日本語配列と US 配列で同じ文字になるものだけ
# （@・[・^ などは配列で文字が変わり、keyd が出すキーと GNOME の登録が食い違うので外す）
HENKAN_KEYS = {**{c: (c, c.upper()) for c in "abcdefghijklmnopqrstuvwxyz"}, **{d: (d, d) for d in "0123456789"},
               "minus": ("minus", "-"), "semicolon": ("semicolon", ";"), "comma": ("comma", ","),
               "dot": ("period", "."), "slash": ("slash", "/")}


def keyd_win_layer(path=KEYD_CONF):
    """keyd の [win] レイヤー {keyd のキー名: 出すもの（例 M-A-e）}。読めなければ空。"""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return {}
    out, inside = {}, False
    for line in text.splitlines():
        t = line.strip()
        if t.startswith("["):
            inside = t == "[win]"
        elif inside and "=" in t and not t.startswith("#"):
            k, v = (x.strip() for x in t.split("=", 1))
            out[k] = v
    return out


def henkan_map():
    """{GNOME の Super+Alt+キー の識別子: 変換＋何キーで出るか（表示）}。keyd の設定から作る。"""
    names = {k: v for k, v in HENKAN_KEYS.items()}
    out = {}
    for key, produced in keyd_win_layer().items():
        m = re.fullmatch(r"M-A-(\w+)", produced)
        if m and m.group(1) in names and key in names:
            out[accel_id(f"<Super><Alt>{names[m.group(1)][0]}")] = names[key][1]
    return out


def keyd_full_layer_text(path=KEYD_CONF):
    """今の keyd の設定の [win] レイヤーだけを、変換＋キーにできる全キー（キー → Super+Alt+同じキー）にした設定の全文。"""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        text = "[ids]\n*\n\n[main]\nhenkan = overload(win, henkan)\n"
    lines, out, inside, done = text.splitlines(), [], False, False
    body = ["# 変換を押しながら: 英字・数字・- ; , . / を Super+Alt+同じキー にする（win の設定画面が作った。",
            "# GNOME のショートカット Super+Alt+キー で win などを呼ぶ。付け外しは win config のショートカットのページで）",
            "[win]"] + [f"{k} = M-A-{k}" for k in HENKAN_KEYS]
    for line in lines:
        t = line.strip()
        if t.startswith("["):
            if inside:
                inside = False
            if t == "[win]":
                inside, done = True, True
                while out and out[-1].lstrip().startswith("#"):   # [win] の直前の説明のコメントも差し替える
                    out.pop()
                out += body
                continue
        if not inside:
            out.append(line)
    if not done:
        out += [""] + body
    return "\n".join(out).rstrip("\n") + "\n"


def henkan_layer_missing():
    """変換＋キーにできるのに、keyd がまだ Super+Alt+同じキー にしていないキー（表示）。"""
    layer = keyd_win_layer()
    return [disp for k, (_g, disp) in HENKAN_KEYS.items() if layer.get(k) != f"M-A-{k}"]


def accel_label(accel):
    """画面に出す表記（例: 変換＋M、Super+Alt+M、変換、Super+半角/全角）。空なら「（未割り当て）」。"""
    if not accel:
        return "（未割り当て）"
    henkan = henkan_map().get(accel_id(accel))
    if henkan:
        return f"変換＋{henkan}"
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
    if accel_id(accel) in henkan_map():                  # 変換＋キー（keyd が出す Super+Alt+キー）は記号も含めて届く
        return ""
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

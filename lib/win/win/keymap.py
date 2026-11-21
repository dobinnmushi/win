"""GUI のキー割り当て。動作名 → キーの表（標準の矢印・Ctrl と、vi 風の普通のキーを並べて、どれも常に効く）。どれも押しつけない。

キーは GTK のアクセラレータの書き方（例: "<Control>1"・"j"・"Down"・"question"）。
Ctrl・Alt・Super を含まない普通のキーは、文字入力中は使わない（呼び出し側が判定する）。
"""

from .i18n import tr

# 動作 → キー（GTK のアクセラレータの書き方）。標準（矢印・Ctrl）と vi 風（j k など）を並べて、どれも常に効く。
# Ctrl などを含まない普通のキーは、文字入力中・ダイアログが開いている間は効かせない（呼び出し側が判定する）。
# 先頭のキーを、ツールチップに出す。
ACTIONS = {
    "page_1": ["<Control>1", "1"],
    "page_2": ["<Control>2", "2"],
    "page_3": ["<Control>3", "3"],
    "page_4": ["<Control>4", "4"],
    "page_prev": ["<Control>Page_Up", "bracketleft"],
    "page_next": ["<Control>Page_Down", "bracketright"],
    "row_down": ["Down", "j"],
    "row_up": ["Up", "k"],
    "row_first": ["Home", "g"],
    "row_last": ["End", "G"],
    "row_default": ["Return", "l"],
    "row_edit": ["<Control>e", "e"],
    "row_delete": ["Delete", "d"],
    "new": ["<Control>n", "n"],
    "filter": ["<Control>f", "slash"],
    "help": ["<Control>question", "question"],
    "close": ["<Control>w", "q"],
}

# キー一覧に出す名前と、順序・まとまり
LABELS = {
    "page_1": tr("ページ 1（ショートカット）"), "page_2": tr("ページ 2（コマンド）"), "page_3": tr("ページ 3（セット）"), "page_4": tr("ページ 4（型）"),
    "page_prev": tr("前のページ"), "page_next": tr("次のページ"),
    "row_down": tr("次の行"), "row_up": tr("前の行"), "row_first": tr("先頭の行"), "row_last": tr("末尾の行"),
    "row_default": tr("行の既定の操作（実行・適用・キーの変更）"), "row_edit": tr("行を編集"), "row_delete": tr("行を削除（確認あり）"),
    "new": tr("新規作成"), "filter": tr("一覧を絞り込む"), "help": tr("キー一覧"), "close": tr("窓を閉じる"),
}
GROUPS = ((tr("ページ"), ("page_1", "page_2", "page_3", "page_4", "page_prev", "page_next")),
          (tr("行"), ("row_down", "row_up", "row_first", "row_last", "row_default", "row_edit", "row_delete", "new")),
          (tr("そのほか"), ("filter", "help", "close")))


def keys_for(action):
    return list(ACTIONS[action])


def tip_for(action):
    """ツールチップ用の表記（例: "Delete / d"）。"""
    return " / ".join(display(k) for k in ACTIONS[action])


_NAMES = {"Down": "↓", "Up": "↑", "Left": "←", "Right": "→", "Return": "Enter", "slash": "/", "question": "?",
          "bracketleft": "[", "bracketright": "]", "Page_Up": "PageUp", "Page_Down": "PageDown", "Escape": "Esc"}
_MODS = {"Control": "Ctrl", "Alt": "Alt", "Super": "Super", "Shift": "Shift"}


def display(accel):
    """キーの表示（例: "<Control>n" → "Ctrl+n"、"Down" → "↓"、"j" → "j"）。"""
    mods, name = [], accel
    while name.startswith("<") and ">" in name:
        m, name = name[1:].split(">", 1)
        mods.append(_MODS.get(m, m))
    return "+".join(mods + [_NAMES.get(name, name)])


def parse(accel):
    """キー → (キー名, 修飾 {"Control", "Alt", "Super"} の集合)。Shift は、キー名の大文字・記号で表すので持たない。"""
    mods, name = set(), accel
    while name.startswith("<") and ">" in name:
        m, name = name[1:].split(">", 1)
        if m in ("Control", "Alt", "Super"):
            mods.add(m)
    return name, mods

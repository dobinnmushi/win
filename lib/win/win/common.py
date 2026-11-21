"""共通の定数・標準ライブラリの読み込み。（win の他のモジュールは、必要な定数や名前をここから読み込む）"""

import os



try:                      # Gio.UnixInputStream / Gio.DesktopAppInfo は非推奨になった
    from gi.repository import GioUnix
except ImportError:
    GioUnix = None


WC_NAME = "org.gnome.Shell"


WC_PATH = "/org/gnome/Shell/Extensions/Windows"


WC_IFACE = "org.gnome.Shell.Extensions.Windows"


TILE_APP_ID = "local.win.tile"




PROMPT_APP_ID = "local.win.prompt"


NVPROMPT_APP_ID = "local.win.nvprompt"


TILEPICK_APP_ID = "local.win.tilepick"




HISTORY = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "win", "history")


CONFIG = os.path.expanduser("~/.config/win/layouts.toml")


CURRENT_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "win-tile-current")


# 設定ファイルが無いときの作業領域の余白（上は GNOME の上部バー）
DEFAULT_INSETS = {"top": 32, "bottom": 0, "left": 0, "right": 0}


BUILTIN_LAYOUTS = {
    "full": "full",
    "lr": "v(1,1)",
    "tb": "h(1,1)",
    "thirds": "v(1,1,1)",
    "quad": "h(v(1,1),v(1,1))",
    "l1r2": "v(1,h(1,1))",
    "l2r1": "v(h(1,1),1)",
    "t1b2": "h(1,v(1,1))",
    "t2b1": "h(v(1,1),1)",
}


class WinError(Exception):
    pass


class NameExistsError(WinError):
    """同じ名前がすでにある（上書きの確認をする呼び出し側が、文言でなく型で見分けるため）。"""

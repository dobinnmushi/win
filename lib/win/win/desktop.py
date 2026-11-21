"""デスクトップ（ワークスペース）の取得・切り替え。Window Calls にはないので、自作の Shell 拡張 win-helper@local（D-Bus）を呼ぶ。"""

import os

from gi.repository import Gio, GLib

from .common import WinError
from .i18n import tr

HELPER_NAME = os.environ.get("WIN_HELPER_NAME") or "org.local.WinHelper"      # D-Bus の名前（試験で模擬のサービスに向けるときだけ差し替える）
HELPER_IFACE = "org.local.WinHelper"
HELPER_PATH = "/org/local/WinHelper"
HELPER_MISSING = (tr("デスクトップの切り替えには、拡張 win-helper@local が要ります"
                  "（~/.local/share/gnome-shell/extensions/win-helper@local。有効にしたあと、再ログインして読み込ませてください）"))


def helper_call(method, fmt=None, *args):
    """win-helper@local の method を呼んで、戻り値を返す。拡張が読み込まれていなければ WinError。"""
    try:
        proxy = Gio.DBusProxy.new_for_bus_sync(Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None,
                                               HELPER_NAME, HELPER_PATH, HELPER_IFACE, None)
        params = GLib.Variant(f"({fmt})", args) if fmt else None
        return proxy.call_sync(method, params, Gio.DBusCallFlags.NONE, 3000, None).unpack()
    except GLib.Error as e:
        remote = Gio.DBusError.get_remote_error(e) or ""
        if remote.endswith(("ServiceUnknown", "NameHasNoOwner")) or "not provided by any" in e.message:
            raise WinError(HELPER_MISSING)
        raise WinError(tr("win-helper の {0} が失敗しました: {1}").format(method, e.message))


def desktops():
    """(いまのデスクトップの番号, デスクトップの数)。番号は 1 から。数は、動的ワークスペースでは末尾の空のものを含む。"""
    cur, count = helper_call("Workspaces")
    return cur + 1, count


def switch_desktop(n):
    """n 番目（1 から）のデスクトップへ切り替える。なければ WinError。"""
    cur, count = desktops()
    if not 1 <= n <= count:
        raise WinError(tr("デスクトップ {0} がありません（1〜{1}）").format(n, count))
    helper_call("Switch", "i", n - 1)


def switch_relative(delta):
    """いまのデスクトップから delta 個ずれたデスクトップへ切り替える（端で一巡はしない）。なければ WinError。"""
    cur, count = desktops()
    if not 1 <= cur + delta <= count:
        raise WinError(tr("デスクトップ {0} がありません（1〜{1}）").format((cur + delta), count))
    helper_call("SwitchRelative", "i", delta)

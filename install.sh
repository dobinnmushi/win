#!/bin/sh
# win を使える状態にする。何度実行してもよい（既にあるものは上書きせず、そろえるだけ）。sudo は使わない。
#   ./install.sh              ~/.local/bin/win へのリンクと、設定画面のランチャーを作り、依存を確かめる
#   ./install.sh --extension  上に加えて、デスクトップの切り替え用の拡張 win-helper@local を入れる（再ログインが要る）
# 事前に必要なもの（Window Calls 拡張・Python・GTK 4・libadwaita）は README の「導入」（Installation）を参照。
set -eu
R=$(cd "$(dirname "$0")" && pwd)
today=$(date +%Y%m%d)
msg() { # msg <日本語> <English>（LANG が ja なら日本語）
    case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in ja*) echo "$1";; *) echo "$2";; esac
}

link() { # link <リポジトリ内のパス> <置き先>
    src=$R/$1 dst=$2
    mkdir -p "$(dirname "$dst")"
    if [ -e "$dst" ] && [ ! -L "$dst" ]; then
        mv "$dst" "$dst.bak-$today"; msg "退避: $dst → $dst.bak-$today" "Backed up: $dst → $dst.bak-$today"
    fi
    ln -sfn "$src" "$dst"; msg "リンク: $dst → $src" "Linked: $dst → $src"
}

extension=false
for a in "$@"; do
    case $a in
        --extension) extension=true;;
        -h|--help) sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
        *) msg "不明なオプション: $a" "Unknown option: $a" >&2; exit 2;;
    esac
done

# --- 依存の確認（足りなくても続け、最後に知らせる）
missing=""
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null || missing="$missing python3(>=3.11)"
python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); from gi.repository import Gtk, Adw' 2>/dev/null \
    || missing="$missing python3-gi/gir1.2-gtk-4.0/gir1.2-adw-1"
wc_dirs="$HOME/.local/share/gnome-shell/extensions/window-calls@domandoman.xyz /usr/share/gnome-shell/extensions/window-calls@domandoman.xyz"
have_wc=false
for d in $wc_dirs; do [ -d "$d" ] && have_wc=true; done

link bin/win "$HOME/.local/bin/win"

# 設定画面のランチャー（Exec は、リンクの絶対パス）
desktop="$HOME/.local/share/applications/win-config.desktop"
mkdir -p "$(dirname "$desktop")"
cat > "$desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=win Settings
Name[ja]=win 設定
Comment=Configure win shortcuts, commands and layouts
Comment[ja]=win のショートカット・コマンド・型を設定する
Exec=$HOME/.local/bin/win config
Icon=preferences-desktop-keyboard-shortcuts
Terminal=false
Categories=Settings;
Keywords=win;window;shortcut;ウィンドウ;ショートカット;窓;設定;
StartupWMClass=local.win.config
DESKTOP
msg "ランチャー: $desktop" "Launcher: $desktop"

if $extension; then
    sh "$R/extension/install.sh"
fi

echo
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) msg "注意: ~/.local/bin が PATH にありません。" "Note: ~/.local/bin is not in your PATH.";; esac
if [ -n "$missing" ]; then
    msg "足りないもの:$missing（Ubuntu なら: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1）" \
        "Missing:$missing (on Ubuntu: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1)"
fi
if ! $have_wc; then
    msg "足りないもの: GNOME 拡張 Window Calls（https://extensions.gnome.org/extension/4724/window-calls/ から入れて、有効にする）。win はこの拡張が無いと動きません。" \
        "Missing: the GNOME extension Window Calls (install it from https://extensions.gnome.org/extension/4724/window-calls/ and enable it). win does not work without it."
fi
msg "次の一歩: win list で窓の一覧が出れば導入できています。ショートカットは presets/super-alt.toml を参考に、win shortcuts apply で反映できます。" \
    "Next: if 'win list' prints your windows, it works. For keyboard shortcuts, see presets/super-alt.toml and apply with 'win shortcuts apply FILE'."

#!/bin/sh
# win-helper@local（デスクトップの取得・切り替えの D-Bus）を、GNOME Shell の拡張として導入する。
# 導入後、有効にして（enabled-extensions に win-helper@local を足す）、再ログインして読み込ませる（Wayland では再起動の代わりに必要）。
set -e
dst="$HOME/.local/share/gnome-shell/extensions/win-helper@local"
mkdir -p "$dst"
cp "$(dirname "$0")/win-helper@local/extension.js" "$(dirname "$0")/win-helper@local/metadata.json" "$dst/"
echo "導入しました: $dst"
echo "有効にする: gnome-extensions enable win-helper@local   （再ログイン後に有効なら、不要。取り消し: gnome-extensions disable win-helper@local）"

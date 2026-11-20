#!/bin/sh
# install.sh で入れたもの（リンク・ランチャー）を外す。
# 設定ファイル（~/.config/win）・使用の記録（~/.local/state/win）・GNOME のショートカット・GNOME 拡張は自動では消さない（最後に消し方を表示）。
set -eu
R=$(cd "$(dirname "$0")" && pwd)
msg() { # msg <日本語> <English>（LANG が ja なら日本語）
    case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in ja*) echo "$1";; *) echo "$2";; esac
}

unlink_if_ours() { # リポジトリを指すリンクのときだけ消す
    dst=$1
    if [ -L "$dst" ] && case "$(readlink "$dst")" in "$R"/*) true;; *) false;; esac; then
        rm "$dst"; msg "削除: $dst" "Removed: $dst"
    fi
}
unlink_if_ours "$HOME/.local/bin/win"
desktop="$HOME/.local/share/applications/win-config.desktop"
if [ -f "$desktop" ] && grep -q "^Exec=$HOME/.local/bin/win config" "$desktop"; then
    rm "$desktop"; msg "削除: $desktop" "Removed: $desktop"
fi

echo
msg "自動では消していないもの（要らなければ手で）:" "Not removed automatically (remove by hand if you want):"
echo "  ~/.config/win  ~/.local/state/win"
msg "  GNOME のショートカット: win shortcuts list で確認し、設定アプリの「カスタムショートカット」で消す（win-* の項目）" \
    "  GNOME shortcuts: check with 'win shortcuts list' (run it before uninstalling) and delete the win-* items in Settings → Keyboard → Custom Shortcuts"
echo "  gnome-extensions disable win-helper@local && rm -r ~/.local/share/gnome-shell/extensions/win-helper@local"

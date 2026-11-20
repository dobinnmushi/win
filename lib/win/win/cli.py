"""コマンド行の入口（main・build_parser）。"""

import argparse
import subprocess
import sys

from .common import WinError
from .screen import resolve_monitor
from .store import MONITOR_HELP
from .placement import cmd_layout
from .simple import cmd_focus, cmd_layouts, cmd_list, cmd_desktop
from .nav import cmd_nav
from .sets import cmd_run, cmd_set
from .prompt import cmd_prompt, run_nvprompt, run_prompt
from .appstate import cmd_browse, cmd_save, cmd_term
from .tilepick import run_tile, run_tilepick
from .ext import EXT, EXT_DIR, cmd_help, load_extensions, run_ext
from .lsp import cmd_lsp
from .overlay import cmd_close, cmd_config, cmd_here, cmd_move, cmd_pick, cmd_place, cmd_size, cmd_stack, cmd_state


def main(argv=None):
    if len(sys.argv) >= 2 and sys.argv[1] == "_tilepick":
        run_tilepick()
        return 0
    if len(sys.argv) >= 2 and sys.argv[1] == "_prompt":
        run_prompt()
        return 0
    if len(sys.argv) >= 6 and sys.argv[1] == "_nvprompt":
        run_nvprompt(*sys.argv[2:6])
        return 0
    if len(sys.argv) >= 4 and sys.argv[1] == "_tile":
        run_tile(int(sys.argv[2]), int(sys.argv[3]))
        return 0
    ap, sub = build_parser()
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and not argv[0].startswith("-") and argv[0] not in sub.choices:
        load_extensions()                                 # 組み込みにない名前は、拡張の命令として探す
        if argv[0] in EXT:
            try:
                return run_ext(argv[0], argv[1:])
            except WinError as e:
                return report_error(e)
    args = ap.parse_args(argv)
    try:
        if args.cmd in ("layout", "here", "place", "stack", "pick", "prompt", "save", "run", "set"):
            resolve_monitor(getattr(args, "monitor", None))      # 基準のモニタを、最初に 1 回決める
        return args.fn(args)
    except WinError as e:
        return report_error(e)


def report_error(e):
    print(f"win: {e}", file=sys.stderr)
    if sys.stderr is sys.__stderr__ and not sys.stderr.isatty():     # ショートカットなど、端末のない呼び出しでは通知で知らせる
        try:
            subprocess.run(["notify-send", "-a", "win", "-i", "dialog-warning-symbolic", "win", str(e)], timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass
    return 1


def build_parser():
    """(引数の解析器, 命令の表)。"""
    ap = argparse.ArgumentParser(prog="win", description="GNOME の窓をコマンドで操作する",
                                 epilog="窓の指定: クラス・題名の一部（大文字小文字は区別しない）か、5 桁以上の ID、"
                                        "または @left・@prev などの位置・状態（一覧は win help）。"
                                        "省略したときの対象は前面の窓（ターミナルから実行すると、そのターミナル）。"
                                        f"拡張の命令（{EXT_DIR} の @command）も win 名前 で呼べる。")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="窓の一覧")
    p.add_argument("-a", "--all", action="store_true", help="通常の窓以外も表示")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("layouts", help="登録済みの型の一覧")
    p.set_defaults(fn=cmd_layouts)

    p = sub.add_parser("focus", help="窓を前面に出す")
    p.add_argument("selector")
    p.set_defaults(fn=cmd_focus)

    p = sub.add_parser("nav", help="フォーカスを移す（next・prev はいまの並びの番号順、left など は上下左右）")
    p.add_argument("direction", choices=["next", "prev", "left", "right", "up", "down"])
    p.set_defaults(fn=cmd_nav)

    p = sub.add_parser("prompt", help="コマンドを 1 行打って窓を操作する小窓（Tab 補完つき）")
    p.add_argument("-m", "--monitor", metavar="画面", help=MONITOR_HELP)
    p.add_argument("--nvim", action="store_true", help="1 行の入力欄でなく、nvim の入力欄を使う（試作）")
    p.add_argument("--gtk", action="store_true", help=argparse.SUPPRESS)      # 既定と同じ（一時期 nvim が既定だったときの指定）
    p.set_defaults(fn=cmd_prompt)

    p = sub.add_parser("config", help="設定の窓（ショートカット・コマンド・型）を開く")
    p.add_argument("page", nargs="?", default="shortcuts", choices=["shortcuts", "commands", "sets", "layouts"],
                   help="開くページ")
    p.set_defaults(fn=cmd_config)

    p = sub.add_parser("run", help="登録したコマンド・保存した並びを実行する（名前なしで一覧）")
    p.add_argument("name", nargs="?")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("set", help="保存した窓の並び（セット）を適用する（名前なしで、絞り込みの小窓から選ぶ）")
    p.add_argument("name", nargs="?", help="セットの名前。省くと、一覧の小窓が開く")
    p.add_argument("-m", "--monitor", metavar="画面", help=MONITOR_HELP)
    p.set_defaults(fn=cmd_set)

    p = sub.add_parser("save", help="いま表に出ている窓の並びを、型と窓の列の命令（セット）として名前をつけて保存する")
    p.add_argument("name")
    p.add_argument("-f", "--force", action="store_true", help="同じ名前があれば上書きする")
    p.add_argument("-s", "--state", action="append", choices=["firefox", "terminal", "all"],
                   help="窓の状態も保存する（Firefox のタブの URL、端末の作業ディレクトリ）。選んだときだけ。URL は平文で保存される")
    p.add_argument("-m", "--monitor", metavar="画面", help=MONITOR_HELP)
    p.set_defaults(fn=cmd_save)

    p = sub.add_parser("browse", help="Firefox を新しい窓で開き、URL をタブとして並べる")
    p.add_argument("urls", nargs="+", metavar="URL", help="開く URL（最初の 1 つで窓を開き、残りはタブ）")
    p.set_defaults(fn=cmd_browse)

    p = sub.add_parser("term", help="端末（Ptyxis）を、作業ディレクトリごとのタブつきで新しく開く")
    p.add_argument("dirs", nargs="*", metavar="作業ディレクトリ", help="タブごとの作業ディレクトリ。省くと今のディレクトリ")
    p.set_defaults(fn=cmd_term)

    p = sub.add_parser("here", help="選んだ窓（先頭 ! でアプリ）を、いまの窓と同じ位置・大きさにして前面に出す")
    p.add_argument("-m", "--monitor", metavar="画面", help=MONITOR_HELP)
    p.add_argument("selector", nargs="?", help="窓の指定（クラス・題名の一部）か !コマンド。省くと小窓で選ぶ")
    p.set_defaults(fn=cmd_here)

    p = sub.add_parser("place", help="置き先（番号のタイル・前面の窓・空きスペース）に、選んだ窓を重ねる（窓を省くと小窓。←→ で置き先を動かせる）")
    p.add_argument("-m", "--monitor", metavar="画面", help=MONITOR_HELP)
    p.add_argument("--min", action="store_true", help="置き先にあった元の窓を最小化する")
    p.add_argument("n", nargs="?", default="0", help="はじめの置き先。タイルの番号（0 は前面の窓の位置）か free（いちばん広い空きスペース）")
    p.add_argument("window", nargs="?", help="置く窓（クラス・題名の一部、@left など）か !コマンド。省くと小窓で選ぶ")
    p.set_defaults(fn=cmd_place)

    p = sub.add_parser("stack", help="同じ位置に重なった窓（層）を、次・前へ切り替える（list なら小窓で選ぶ）")
    p.add_argument("-m", "--monitor", metavar="画面", help=MONITOR_HELP)
    p.add_argument("n", nargs="?", default="0", help="タイルの番号（0 は前面の窓のいるタイル）")
    p.add_argument("action", nargs="?", default="next", choices=["next", "prev", "list"], help="next（既定）・prev・list（小窓で選ぶ）")
    p.set_defaults(fn=cmd_stack)

    p = sub.add_parser("desktop", help="デスクトップ（ワークスペース）の表示・切り替え（N・next・prev・list。切り替えには拡張 win-helper@local が要る）")
    p.add_argument("target", nargs="?", default="", help="デスクトップの番号（1 から）・next・prev・list。省くと、いまのデスクトップを表示")
    p.set_defaults(fn=cmd_desktop)

    p = sub.add_parser("pick", help="窓の一覧を小さく出して選び、前面に出す（j/k・矢印・Enter）")
    p.add_argument("--id", action="store_true", help="前面に出さず、選んだ窓の ID だけを表示")
    p.add_argument("-m", "--monitor", metavar="画面", help=MONITOR_HELP)
    p.set_defaults(fn=cmd_pick)

    p = sub.add_parser("layout", help="窓を分割配置する")
    p.add_argument("layout", nargs="?", help="型の名前（win layouts）か式（例: 'v(1,h(1,1))'。略記は , ＝左右・/＝上下・( )・重み:式、例 1,2:1/1/1,1）。省くと小窓で型を選ぶ")
    p.add_argument("windows", nargs="*", metavar="窓", help="タイル順の窓。- は空け、!コマンド は新しく起動")
    p.add_argument("-i", "--interactive", action="store_true", help="タイルごとに窓を絞り込んで選ぶ・起動する（! でアプリ、Tab で残りを自動）")
    p.add_argument("-n", "--dry-run", action="store_true", help="動かさず、割り当てだけ表示")
    p.add_argument("--gap", type=int, help="タイル間の隙間（px）")
    p.add_argument("-t", "--text", action="store_true", help="対話モードを端末の文字入力で行う（既定は絞り込みの小窓）")
    p.add_argument("--preview", action="store_true", help="対話モードで、各タイルの位置に番号つきの目印の窓を出す")
    p.add_argument("--pick", action="store_true", help="対話モードで、タイルごとに窓の一覧を自動で出す")
    p.add_argument("--no-preview", action="store_true", help="（--text 用）画面上の番号表示を出さない")
    p.add_argument("-m", "--monitor", metavar="画面", help=MONITOR_HELP)
    p.set_defaults(fn=cmd_layout)

    p = sub.add_parser("move", help="窓を移動する")
    p.add_argument("x", type=int); p.add_argument("y", type=int)
    p.add_argument("-w", "--window"); p.set_defaults(fn=cmd_move)

    p = sub.add_parser("size", help="窓の大きさを変える")
    p.add_argument("w", type=int); p.add_argument("h", type=int)
    p.add_argument("-w", "--window"); p.set_defaults(fn=cmd_size)

    p = sub.add_parser("state", help="最大化・最小化・常に手前")
    p.add_argument("action", choices=["max", "unmax", "min", "unmin", "above", "unabove"])
    p.add_argument("-w", "--window"); p.set_defaults(fn=cmd_state)

    for name, action, text in (("max", "max", "窓を最大化する"), ("unmax", "unmax", "最大化を戻す"),
                               ("min", "min", "窓を最小化する"), ("unmin", "unmin", "最小化を戻す")):
        p = sub.add_parser(name, help=text)           # state の短縮形
        p.add_argument("-w", "--window")
        p.set_defaults(fn=cmd_state, action=action)

    p = sub.add_parser("close", help="窓を閉じる")
    p.add_argument("-w", "--window"); p.set_defaults(fn=cmd_close)

    p = sub.add_parser("lsp", help="エディタ（nvim など）向けに、win の命令の補完・書式・説明を出す（LSP。標準入出力で話す）")
    p.set_defaults(fn=cmd_lsp)

    p = sub.add_parser("help", help="命令の書式と説明（拡張の命令、@ の指定も）。名前なしで一覧")
    p.add_argument("name", nargs="?", help="命令・拡張の関数・登録したコマンドやセットの名前か、@ の指定。api・commands・sets・layouts で一覧")
    p.add_argument("--names", action="store_true", help="渡せる名前の一覧を出す（エディタの補完用）")
    p.add_argument("--py", action="store_true", help="拡張（Python）を書くときのヘルプ（名前は winapi の関数を先に引く。名前なしで win help api）")
    p.set_defaults(fn=cmd_help)
    return ap, sub


if __name__ == "__main__":
    sys.exit(main())

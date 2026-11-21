"""win — GNOME の窓をコマンドで操作する。

Window Calls 拡張（window-calls@domandoman.xyz）の D-Bus を呼んで、
一覧・前面化・移動・サイズ変更・状態変更・分割配置（layout）を行う。

  win list                       窓の一覧
  win focus firefox              窓を前面に出す
  win layout                     小窓で型を選ぶ（Enter でタイルごとに選ぶ・Tab で前面の窓から自動配置）
  win layout quad                前面の窓から順に 2x2 に並べる
  win layout lr firefox '!ptyxis'   左に Firefox、右に新しく ptyxis を起動
  win layout quad firefox ...    1枚目に Firefox、残りは前面の窓から順に
  win layout "v(1,h(1,1))" -i    型だけ作って、タイルごとに絞り込んで選ぶ小窓（文字で絞り込み・
                                 先頭 ! でアプリを新規起動・Tab で残りを自動・Ctrl+S 空ける・Ctrl+B 戻る）
  win layouts                    登録済みの型の一覧
  win here                       選んだ窓（先頭 ! でアプリ）を、いまの窓と同じ位置・大きさにして前面へ（place 0 と同じ）
  win place 2 firefox            2 番目のタイルに Firefox を重ねる（窓を省くと小窓。←→ で置き先を動かせる）
  win place free firefox         いちばん広い空きスペースに Firefox を置く
  win stack                      前面の窓のいる位置に重なった窓を、次の層へ切り替える（prev・list も）
  win group new 作業 firefox     窓のグループ（1 つの枠を共有し、next・prev・select でタブのように切り替える）
  win focus 'firefox?'          Firefox へ飛ぶ（なければ起動、すでにいれば次の窓へ巡回）
  win send                       前面の窓を、別のモニタへ送る（位置と大きさの割合を保つ）
  win undo                       直前の操作（layout・place・here・group・set・send）を元に戻す
  win stats                      使用の集計（コマンドごとの回数。キー経由か手入力か）
  win desktop 2                  2 番目のデスクトップへ切り替える（next・prev・list も。要 win-helper@local）
  win pick                       窓の一覧を小さく出し、j/k・矢印・Enter で選んで前面に出す
  win nav left|right|up|down     表に出ている窓の間で、その向きの窓にフォーカスを移す
  win prompt                     コマンドを 1 行打って窓を操作する小窓（Tab 補完・履歴つき）

型の式: full / v(a,b,...) 左右に分ける / h(a,b,...) 上下に分ける。
引数 a は割合の数（葉）、式（部分）、または「割合:式」。
"""

# パッケージとしての入口。下のモジュールを、依存の下から順に読み込む。
from . import common, i18n, usage, screen, layouts, shortcuts, dbus, desktop, store, pickwin, placement, undo, simple, textui, nav, sets, prompt, appstate, groups, tilepick, dialog, pickers, layoutflow, ext, lsp, configwin, overlay, cli

# 互換: win.名前 で、すべてのモジュールの名前を引ける（試験・拡張・古い呼び出し方のため）
for _m in (common, i18n, usage, screen, layouts, shortcuts, dbus, desktop, store, pickwin, placement, undo, simple, textui, nav, sets, prompt, appstate, groups, tilepick, dialog, pickers, layoutflow, ext, lsp, configwin, overlay, cli):
    globals().update({k: v for k, v in vars(_m).items() if not k.startswith('__')})

main = cli.main

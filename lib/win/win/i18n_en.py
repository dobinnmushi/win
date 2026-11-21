"""英語の対応表（鍵は日本語の文字列。i18n.py が、日本語以外の言語のときだけ読み込む）。
このファイルは tests/i18n_check.py が、ソースの tr() の鍵と書式の穴の一致を検査する。"""
EN = {
    "Firefox のセッション情報が見つかりません":
        "Firefox session information not found",
    "mozlz4 ではありません":
        "not a mozlz4 file",
    "Firefox のプロファイルが見つかりません":
        "Firefox profile not found",
    "端末の窓が複数あるため、各窓の表示中のタブの作業ディレクトリだけ保存します":
        "There are several terminal windows, so only the working directory of each window's visible tab is saved",
    "画面の一部しか使っていない並びです。呼ぶと、窓は画面いっぱいに広がります":
        "This arrangement uses only part of the screen. When recalled, the windows will fill the whole screen",
    "名前が空です":
        "The name is empty",
    "端末のタブの作業ディレクトリを読めませんでした":
        "Could not read the working directories of the terminal tabs",
    "前面の窓が、いまの並びのタイルの中にありません":
        "The focused window is not in any tile of the current arrangement",
    "保存できる窓がありません":
        "There are no windows to save",
    "保存しました: 「{0}」（窓 {1} 枚）。呼び出すには: win set {2}":
        "Saved: \"{0}\" ({1} windows). To recall it: win set {2}",
    "端末の窓が複数あり、窓とタブの対応が取れないため、端末の状態は保存しません":
        "There are several terminal windows and tabs cannot be matched to windows, so the terminal state is not saved",
    "タイル {0} がありません（いまの並びのタイルは {1} 枚）":
        "Tile {0} does not exist (the current arrangement has {1} tiles)",
    "タイル {0} に重なりはありません（窓は 1 枚）":
        "Tile {0} has no stacked windows (it has 1 window)",
    "別のモニタにある窓 {0} 枚は含めていません":
        "{0} windows on another monitor are not included",
    "最大化している窓 {0} 枚は含めていません":
        "{0} maximized windows are not included",
    "重なっている窓 {0} 枚は含めていません（{1}）。各タイルで、いちばん上の窓だけ保存します":
        "{0} stacked windows are not included ({1}). Only the topmost window of each tile is saved",
    "「{0}」はすでにあります（上書きするには --force）":
        "\"{0}\" already exists (use --force to overwrite)",
    "注意: {0}":
        "Note: {0}",
    "  ※ 状態（タブの URL・作業ディレクトリ）は {0} に平文で保存されました":
        "  * The state (tab URLs, working directories) was saved to {0} in plain text",
    "Firefox の窓「{0}」: セッションの窓と対応が取れませんでした（タブの保存は 15 秒ほど遅れます）":
        "Firefox window \"{0}\": could not be matched to a session window (saving tabs lags by about 15 seconds)",
    "Firefox の窓「{0}」: 保存できるタブがありません":
        "Firefox window \"{0}\": no tabs to save",
    "最大化している窓のうち、いちばん上の 1 枚だけ保存します（{0} 枚は含めていません）":
        "Only the topmost maximized window is saved ({0} are not included)",
    "Firefox のタブを読めませんでした（{0}）":
        "Could not read the Firefox tabs ({0})",
    "{0} の窓がないため、状態は保存しません":
        "There is no {0} window, so its state is not saved",
    "端末":
        "terminal",
    "{0}: 窓が見つかりません（起動コマンドも不明）":
        "{0}: window not found (and its launch command is unknown)",
    "{0}: 起動できませんでした（{1}）":
        "{0}: could not launch ({1})",
    "GNOME の窓をコマンドで操作する":
        "Control GNOME windows from the command line",
    "窓の一覧":
        "List windows",
    "通常の窓以外も表示":
        "Also show windows other than normal ones",
    "登録済みの型の一覧":
        "List registered layouts",
    "窓を前面に出す":
        "Bring a window to the front",
    "フォーカスを移す（next・prev はいまの並びの番号順、left など は上下左右）":
        "Move the focus (next/prev follow the current arrangement's numbering; left etc. move by direction)",
    "コマンドを 1 行打って窓を操作する小窓（Tab 補完つき）":
        "A small box to type one command line to operate windows (with Tab completion)",
    "画面":
        "MONITOR",
    "1 行の入力欄でなく、nvim の入力欄を使う（試作）":
        "Use an nvim input box instead of the one-line box (experimental)",
    "設定の窓（ショートカット・コマンド・型）を開く":
        "Open the settings window (shortcuts, commands, layouts)",
    "開くページ":
        "page to open",
    "登録したコマンド・保存した並びを実行する（名前なしで一覧）":
        "Run a registered command or saved arrangement (list them without a name)",
    "保存した窓の並び（セット）を適用する（名前なしで、絞り込みの小窓から選ぶ）":
        "Apply a saved window arrangement (set) (without a name, pick from a filter dialog)",
    "セットの名前。省くと、一覧の小窓が開く":
        "Name of the set. If omitted, a list dialog opens",
    "いま表に出ている窓の並びを、型と窓の列の命令（セット）として名前をつけて保存する":
        "Save the windows currently on screen, as a layout and window list (a set), under a name",
    "同じ名前があれば上書きする":
        "Overwrite if the name already exists",
    "窓の状態も保存する（Firefox のタブの URL、端末の作業ディレクトリ）。選んだときだけ。URL は平文で保存される":
        "Also save window state (Firefox tab URLs, terminal working directories). Only when chosen. URLs are saved in plain text",
    "Firefox を新しい窓で開き、URL をタブとして並べる":
        "Open Firefox in a new window and arrange URLs as tabs",
    "開く URL（最初の 1 つで窓を開き、残りはタブ）":
        "URLs to open (the first opens the window, the rest become tabs)",
    "端末（Ptyxis）を、作業ディレクトリごとのタブつきで新しく開く":
        "Open a terminal (Ptyxis) anew, with a tab per working directory",
    "作業ディレクトリ":
        "DIRECTORY",
    "タブごとの作業ディレクトリ。省くと今のディレクトリ":
        "Working directory of each tab. Defaults to the current directory",
    "選んだ窓（先頭 ! でアプリ）を、いまの窓と同じ位置・大きさにして前面に出す":
        "Give the chosen window (or, with a leading !, an app) the same position and size as the current window, and bring it to the front",
    "窓の指定（クラス・題名の一部）か !コマンド。省くと小窓で選ぶ":
        "Window spec (class, part of the title) or !command. If omitted, pick in a dialog",
    "置き先（番号のタイル・前面の窓・空きスペース）に、選んだ窓を重ねる（窓を省くと小窓。←→ で置き先を動かせる）":
        "Stack the chosen window on a destination (a numbered tile, the focused window, free space) (omit the window for a dialog; the arrow keys move the destination)",
    "置き先にあった元の窓を最小化する":
        "Minimize the window that was in the destination",
    "はじめの置き先。タイルの番号（0 は前面の窓の位置）か free（いちばん広い空きスペース）":
        "Initial destination: a tile number (0 is the focused window's position) or free (the largest free space)",
    "置く窓（クラス・題名の一部、@left など）か !コマンド。省くと小窓で選ぶ":
        "Window to place (class, part of the title, @left etc.) or !command. If omitted, pick in a dialog",
    "同じ位置に重なった窓（層）を、次・前へ切り替える（list なら小窓で選ぶ）":
        "Switch windows stacked at the same position (layers) to the next or previous (list picks in a dialog)",
    "タイルの番号（0 は前面の窓のいるタイル）、または動作。どちらの順でもよい":
        "Tile number (0 is the tile of the focused window), or the action. Either order works",
    "next（既定）・prev・list（小窓で選ぶ）、またはタイルの番号":
        "next (default), prev, list (pick in a dialog), or a tile number",
    "窓のグループ（名前つき・保存つき。1 つの枠を共有し、タブのように切り替える）":
        "Window groups (named, persistent; they share one frame and switch like tabs)",
    "list（既定）・new 名前 [窓…]・define 名前 窓の指定…・add 名前 [窓…]・remove [窓…]・delete 名前・next|prev|show|select [名前]・place 名前 [タイル]・from-stack [タイル] [名前]":
        "list (default), new NAME [WINDOW...], define NAME WINDOW-SPEC..., add NAME [WINDOW...], remove [WINDOW...], delete NAME, next|prev|show|select [NAME], place NAME [TILE], from-stack [TILE] [NAME]",
    "動作の引数（名前・窓の指定・タイルの番号）。名前を省くと、前面の窓の属するグループ":
        "Arguments of the action (name, window specs, tile number). Without a name, the group of the focused window",
    "ショートカットの宣言的な設定（export で割り当てをファイルに書き出し、apply でファイルを GNOME に反映。list で一覧）":
        "Declarative shortcut settings (export writes the assignments to a file, apply applies the file to GNOME, list lists them)",
    "list（既定）・export・apply":
        "list (default), export, apply",
    "shortcuts.toml のパス（apply の既定は ~/.config/win/shortcuts.toml。export は省くと標準出力）":
        "Path of shortcuts.toml (apply defaults to ~/.config/win/shortcuts.toml; export writes to stdout if omitted)",
    "apply: 反映せず、変える内容だけ表示":
        "apply: show what would change without applying",
    "apply: ファイルにない win-* の項目を消す（それ以外は消さない）":
        "apply: remove win-* entries that are not in the file (other entries are kept)",
    "前面の窓を、別のモニタへ送る（位置と大きさの割合を保つ。next・prev・primary・モニタ名）":
        "Send the focused window to another monitor (keeping the proportions of its position and size; next, prev, primary or a monitor name)",
    "next（既定）・prev・primary・モニタの接続名（eDP-1 など）":
        "next (default), prev, primary, or a monitor connector name (e.g. eDP-1)",
    "送る窓（省くと前面の窓）":
        "Window to send (the focused window if omitted)",
    "直前の操作（layout・place・here・group・set・send）を元に戻す（list で記録の一覧）":
        "Undo the last operation (layout, place, here, group, set, send) (list shows the records)",
    "list で、元に戻せる記録の一覧":
        "list shows the records that can be undone",
    "使用の集計（直近の日数）。on・off で記録を入れ・切り、reset で消す":
        "Usage summary (recent days). on and off toggle recording; reset deletes it",
    "日数（既定 30）・on・off・reset・path":
        "days (default 30), on, off, reset, path",
    "デスクトップ（ワークスペース）の表示・切り替え（N・next・prev・list。切り替えには拡張 win-helper@local が要る）":
        "Show or switch desktops (workspaces) (N, next, prev, list; switching needs the extension win-helper@local)",
    "デスクトップの番号（1 から）・next・prev・list。省くと、いまのデスクトップを表示":
        "Desktop number (from 1), next, prev, list. If omitted, shows the current desktop",
    "窓の一覧を小さく出して選び、前面に出す（j/k・矢印・Enter）":
        "Show a small window list to pick from and bring the choice to the front (j/k, arrows, Enter)",
    "前面に出さず、選んだ窓の ID だけを表示":
        "Print only the ID of the chosen window, without raising it",
    "窓を分割配置する":
        "Tile windows",
    "型の名前（win layouts）か式（例: 'v(1,h(1,1))'。略記は , ＝左右・/＝上下・( )・重み:式、例 1,2:1/1/1,1）。省くと小窓で型を選ぶ":
        "Layout name (win layouts) or expression (e.g. 'v(1,h(1,1))'. Short form: , = side by side, / = stacked, ( ), weight:expr, e.g. 1,2:1/1/1,1). If omitted, pick a layout in a dialog",
    "窓":
        "WINDOW",
    "タイル順の窓。- は空け、!コマンド は新しく起動":
        "Windows in tile order. - leaves a tile empty, !command launches a new one",
    "タイルごとに窓を絞り込んで選ぶ・起動する（! でアプリ、Tab で残りを自動）":
        "Pick or launch a window for each tile by filtering (! for an app, Tab fills the rest automatically)",
    "動かさず、割り当てだけ表示":
        "Do not move anything; only show the assignment",
    "タイル間の隙間（px）":
        "Gap between tiles (px)",
    "対話モードを端末の文字入力で行う（既定は絞り込みの小窓）":
        "Run the interactive mode as terminal text input (the default is the filter dialog)",
    "対話モードで、各タイルの位置に番号つきの目印の窓を出す":
        "In the interactive mode, show numbered marker windows at each tile",
    "対話モードで、タイルごとに窓の一覧を自動で出す":
        "In the interactive mode, automatically show the window list for each tile",
    "（--text 用）画面上の番号表示を出さない":
        "(for --text) do not show the numbers on screen",
    "窓を移動する":
        "Move a window",
    "窓の大きさを変える":
        "Resize a window",
    "最大化・最小化・常に手前":
        "Maximize, minimize, always on top",
    "窓を最大化する":
        "Maximize a window",
    "最大化を戻す":
        "Restore a maximized window",
    "窓を最小化する":
        "Minimize a window",
    "最小化を戻す":
        "Restore a minimized window",
    "窓を閉じる":
        "Close a window",
    "エディタ（nvim など）向けに、win の命令の補完・書式・説明を出す（LSP。標準入出力で話す）":
        "Provide completion, formatting and docs of win commands for editors such as nvim (LSP, over stdin/stdout)",
    "命令の書式と説明（拡張の命令、@ の指定も）。名前なしで一覧":
        "Syntax and description of a command (also extension commands and @ specs). Without a name, a list",
    "命令・拡張の関数・登録したコマンドやセットの名前か、@ の指定。api・commands・sets・layouts で一覧":
        "A command, extension function, registered command or set name, or an @ spec. api, commands, sets and layouts list them",
    "渡せる名前の一覧を出す（エディタの補完用）":
        "List the names that can be passed (for editor completion)",
    "拡張（Python）を書くときのヘルプ（名前は winapi の関数を先に引く。名前なしで win help api）":
        "Help for writing extensions (Python) (a name looks up winapi functions first; without a name, win help api)",
    "窓の指定: クラス・題名の一部（大文字小文字は区別しない）か、5 桁以上の ID、または @left・@prev などの位置・状態（一覧は win help）。省略したときの対象は前面の窓（ターミナルから実行すると、そのターミナル）。拡張の命令（{0} の @command）も win 名前 で呼べる。":
        "Window spec: class or part of the title (case-insensitive), an ID of 5 or more digits, or a position or state such as @left or @prev (see win help). If omitted, the target is the focused window (when run from a terminal, that terminal). Extension commands (@command in {0}) can also be called as win NAME.",
    "キャンセル":
        "Cancel",
    "設定する":
        "Assign",
    "解除する":
        "Clear",
    "使用中のキーも押して調べる…":
        "Press a key to check whether it is in use...",
    "win の命令":
        "win command",
    "シェルコマンド":
        "shell command",
    "新しい拡張":
        "New extension",
    "削除しました":
        "Deleted",
    "セット":
        "Sets",
    "コマンド":
        "Commands",
    "今の窓の並びを保存":
        "Save the current window arrangement",
    "保存":
        "Save",
    "削除":
        "Delete",
    "複製して編集":
        "Duplicate and edit",
    "＋ 新しい型":
        "+ New layout",
    "win の設定":
        "win settings",
    "ショートカット":
        "Shortcuts",
    "型":
        "Layouts",
    "割り当てたいキーを、実際に押してください（Esc で取消）":
        "Press the key you want to assign (Esc to cancel)",
    "キーを文字で入力（例: <Super><Alt>m）":
        "Type the key (e.g. <Super><Alt>m)",
    "日本語キーから選ぶ":
        "Choose from Japanese keys",
    "ほかと競合していても設定する":
        "Assign even if it conflicts with another",
    "GNOME の確認（ショートカットの無効化の許可）が出ます。許可すると、すでに使われているキーも押して確かめられます":
        "GNOME will ask for permission (to disable shortcuts). If you allow it, you can press keys that are already in use to check them",
    "キーを解除しました":
        "Key cleared",
    "変更":
        "Change",
    "キーは、ここで一元管理します（GNOME の「カスタムショートカット」と同じ場所に書きます）。変更はすぐ保存され、反映まで数秒かかることがあります。":
        "Keys are managed here (they are written to the same place as GNOME's \"Custom Shortcuts\"). Changes are saved immediately and may take a few seconds to take effect.",
    "⚠ この命令は拡張に見つかりません（消すか、拡張を直してください）":
        "⚠ This command was not found in the extensions (delete it, or fix the extension)",
    "その他の自作ショートカット":
        "Other custom shortcuts",
    "win 以外で、自分で登録したものです。":
        "Shortcuts for things other than win that you registered yourself.",
    "＋ 追加":
        "+ Add",
    "名前":
        "Name",
    "コマンド（例: /usr/bin/ibus engine mozc-on）":
        "Command (e.g. /usr/bin/ibus engine mozc-on)",
    "ショートカットを編集":
        "Edit shortcut",
    "ショートカットを追加":
        "Add shortcut",
    "よく使う操作に名前をつけて登録します。`win run 名前` で呼べて、入力欄（win prompt）の補完にも出ます。窓の並びは「セット」ページで保存します。キーは「ショートカット」ページで付けます。":
        "Register a name for an operation you use often. Call it with `win run NAME`; it also appears in the completion of the input box (win prompt). Save window arrangements on the \"Sets\" page. Assign keys on the \"Shortcuts\" page.",
    "登録したコマンド":
        "Registered commands",
    "＋ 新しいコマンド":
        "+ New command",
    "拡張（Python）":
        "Extensions (Python)",
    "命令の名前（英字・数字・_。例: swap）":
        "Command name (letters, digits, _; e.g. swap)",
    "作って開く":
        "Create and open",
    "保存したセット":
        "Saved sets",
    "種類":
        "Kind",
    "名前を入力してください":
        "Enter a name",
    "保存しました":
        "Saved",
    "実行しました":
        "Done",
    "名前（例: 作業用）":
        "Name (e.g. work)",
    "いま表に出ている窓（この画面にあるもの）を、型と窓の列（例: layout v(1,2,1) firefox? ...）として保存します。ピクセルは保存しないので、画面の大きさが変わっても使えます。窓がなければ起動します。`win set 名前` で呼べます。":
        "Saves the windows currently on screen (the ones on this screen) as a layout and a window list (e.g. layout v(1,2,1) firefox? ...). Pixels are not saved, so it still works if the screen size changes. Windows that are not running are launched. Call it with `win set NAME`.",
    "Firefox のタブも保存する":
        "Also save Firefox tabs",
    "開いているタブの URL を保存し、窓がなければそのタブで開き直します。URL は平文で保存されます":
        "Saves the URLs of the open tabs and, if the window is gone, reopens it with those tabs. URLs are saved in plain text",
    "端末の作業ディレクトリも保存する":
        "Also save terminal working directories",
    "タブごとの作業ディレクトリを保存し、窓がなければそこで開き直します":
        "Saves the working directory of each tab and, if the window is gone, reopens it there",
    "状態も保存する（必要なときだけ）":
        "Also save state (only when needed)",
    "特定の作業を繰り返すときのための設定です。汎用の並びでは、オフのままにしてください（開く場所が固定されます）。":
        "For repeating a specific task. Leave it off for general arrangements (the places to open would be fixed).",
    "窓を並べる「型」です。`v(…)` は左右に、`h(…)` は上下に分けます。数は割合で、`2:v(1,1)` のように、割合つきで中をさらに分けられます。略記もあり、`,` で左右、`/` で上下、`( )` でまとめ、`2:` で割合です（例: `1,2:1/1/1,1` = v(1,2:h(1,1,1),1)。引用符は要りません）。組み込みの型は、複製して編集できます。":
        "A \"layout\" arranges windows. `v(...)` splits side by side, `h(...)` splits top and bottom. Numbers are proportions, and you can split further with weights like `2:v(1,1)`. There is also a short form: `,` for side by side, `/` for top and bottom, `( )` to group, `2:` for a weight (e.g. `1,2:1/1/1,1` = v(1,2:h(1,1,1),1); no quotes needed). Built-in layouts can be duplicated and edited.",
    "自作":
        "custom",
    "組み込み":
        "built-in",
    "式（例: h(1,2:v(1,1),1)　略記: 1,2:1/1/1,1）":
        "Expression (e.g. h(1,2:v(1,1),1) short form: 1,2:1/1/1,1)",
    "型の一覧と編集":
        "Layouts: list and edit",
    "配置の設定":
        "Layout settings",
    "タイルどうしの隙間と、作業領域の余白（画面の端から窓を置かない幅）。単位は px。":
        "The gap between tiles, and the margins of the work area (the width at the screen edges where no window is placed). Units are px.",
    "タイルどうしの隙間":
        "Gap between tiles",
    "上の余白（上部バーの高さ。主モニタだけに適用）":
        "Top margin (height of the top bar; applies to the primary monitor only)",
    "下の余白":
        "Bottom margin",
    "左の余白":
        "Left margin",
    "右の余白":
        "Right margin",
    "配置の設定を保存しました":
        "Layout settings saved",
    "キーを解除":
        "Clear key",
    "名前とコマンドを編集":
        "Edit name and command",
    "n 番目のタイルの窓へ（1〜9）":
        "Window of tile n (1-9)",
    "名前とコマンドの両方を入力してください":
        "Enter both a name and a command",
    "次へ（キーを設定）":
        "Next (set the key)",
    "フォルダを開く":
        "Open folder",
    "再読み込み":
        "Reload",
    "＋ 新しい拡張":
        "+ New extension",
    "英字・数字・_ で、数字以外から始まる名前にしてください":
        "Use letters, digits and _, and do not start with a digit",
    " にあります":
        " is at ",
    "「{0}」を実行しました":
        "Ran \"{0}\"",
    "＋ 手で書く":
        "+ Write by hand",
    "今の窓の並びを保存…":
        "Save the current window arrangement...",
    "「{0}」を適用しました":
        "Applied \"{0}\"",
    "命令を打つと候補が出ます（Tab で確定、↑↓で選択、Esc で閉じる、Ctrl+Space で候補を出す）。":
        "Candidates appear as you type a command (Tab to accept, ↑↓ to select, Esc to close, Ctrl+Space to show candidates).",
    "内容を入力してください":
        "Enter the content",
    "保存済みの並びは、保存後に「実行」で試せます":
        "After saving, you can try a saved arrangement with \"Run\"",
    "試す":
        "Try",
    "内容":
        "Content",
    "（選ばない）":
        "(none)",
    "すでに使われています: ":
        "Already in use: ",
    "キーの形式が読めません（例: <Super><Alt>m）":
        "Cannot read the key format (e.g. <Super><Alt>m)",
    "{0} に設定しました（反映まで数秒かかることがあります）":
        "Set to {0} (it may take a few seconds to take effect)",
    "拡張":
        "Extension",
    "実行":
        "Run",
    "編集":
        "Edit",
    "（まだありません。右上のボタンから作れます）":
        "(None yet. Create one with the button at the top right)",
    "{0} に .py を置き、関数に @command を付けると win の命令になります（win 名前 で呼べて、入力欄の補完・登録したコマンド・ショートカットでも使えます）。書き方は同じ場所の winapi.pyi と、win help にあります。":
        "Put a .py in {0} and add @command to a function to make it a win command (callable as win NAME, and usable from the input box completion, registered commands and shortcuts). See winapi.pyi in the same place, and win help, for how to write one.",
    "定義を開く（端末の nvim）":
        "Open the definition (nvim in a terminal)",
    "開く":
        "Open",
    "（拡張はまだありません）":
        "(No extensions yet)",
    "{0}/名前.py を作り、端末の nvim で開きます。保存した後、この画面の「再読み込み」で一覧に出ます。":
        "Creates {0}/NAME.py and opens it in nvim in a terminal. After saving, press \"Reload\" on this screen to list it.",
    "{0} を作りました。保存したら「再読み込み」を押してください":
        "Created {0}. Press \"Reload\" after saving",
    "拡張のソースを開くには、ptyxis と nvim が要ります。ファイルは ":
        "Opening an extension's source needs ptyxis and nvim. The file is at ",
    "窓の並びに名前をつけて保存したものです。`win set 名前`、または `win set`（絞り込みの小窓）で呼べます。保存先は {0} です。キーは「ショートカット」ページで付けます。":
        "A saved window arrangement under a name. Call it with `win set NAME`, or `win set` (a filter dialog). It is saved in {0}. Assign keys on the \"Shortcuts\" page.",
    "適用":
        "Apply",
    "（まだありません。右上の「今の窓の並びを保存…」から作れます）":
        "(None yet. Create one with \"Save the current window arrangement...\" at the top right)",
    "win の命令（複数行可）":
        "win commands (multiple lines allowed)",
    "シェルコマンド（複数行可）":
        "Shell command (multiple lines allowed)",
    "シェルで実行されます（複数行はそのまま 1 つのスクリプトになります）。win の命令を呼ぶときは頭に win を付けます。":
        "Run by the shell (multiple lines become a single script as they are). To call a win command, put win at the start.",
    "「{0}」はすでにあります":
        "\"{0}\" already exists",
    "保存せずに、いま実行します":
        "Run it now, without saving",
    "{0}を編集":
        "Edit {0}",
    "新しい{0}":
        "New {0}",
    "上書きしますか？":
        "Overwrite?",
    "上書き":
        "Overwrite",
    "型「{0}」を保存しました":
        "Saved layout \"{0}\"",
    "型「{0}」を削除しました":
        "Deleted layout \"{0}\"",
    "このショートカットを削除しますか？":
        "Delete this shortcut?",
    "9 個のうち {0} 個にキーが付いています":
        "{0} of 9 have keys assigned",
    "いま実行する":
        "Run now",
    "引数を省いて、いま実行する":
        "Run now, without the arguments",
    "読み込めませんでした: {0}":
        "Could not load: {0}",
    "「{0}」は win の組み込みの命令と同じ名前です":
        "\"{0}\" is the same name as a built-in win command",
    "「{0}」はすでにあります（{1}）":
        "\"{0}\" already exists ({1})",
    "{0} はすでにあります":
        "{0} already exists",
    "いま適用する":
        "Apply now",
    "窓の並び {0} 枚を保存しています（作り直すには「今の窓の並びを保存」を、同じ名前で）。":
        "Saves {0} windows' arrangement (to rebuild it, use \"Save the current window arrangement\" with the same name).",
    "win の命令を、1 行に 1 つ書きます。上から順に実行し、失敗したらそこで止まります。# で始まる行は無視されます。":
        "Write one win command per line. They run from the top, and stop at the first failure. Lines starting with # are ignored.",
    "「{0}」を保存しました（窓 {1} 枚）":
        "Saved \"{0}\" ({1} windows)",
    "　注意: ":
        " Note: ",
    "（上書き）":
        " (overwrite)",
    "タイル {0} 枚":
        "{0} tiles",
    "追加しました":
        "Added",
    "コマンドを削除しますか？":
        "Delete the command?",
    "拡張を読み直しました":
        "Reloaded the extensions",
    "セットを削除しますか？":
        "Delete the set?",
    "ふつうは最初の layout 行が並びで、一覧のプレビューにもその行が使われます。":
        "Usually the first layout line is the arrangement, and the list preview uses that line.",
    "「{0}」はすでにあります。":
        "\"{0}\" already exists.",
    "「{0}」を上書きしました（窓 {1} 枚）":
        "Overwrote \"{0}\" ({1} windows)",
    "「{0}」を削除します。":
        "This deletes \"{0}\".",
    "「{0}」と、それに付けたキーを削除します。":
        "This deletes \"{0}\" and the key assigned to it.",
    "前面の窓が見つかりません（-w で窓を指定してください）":
        "No focused window found (specify a window with -w)",
    "前面の窓":
        "the focused window",
    "前面の窓の次に手前にある窓（たいてい直前に使っていた窓）":
        "the window next in front after the focused window (usually the one used just before)",
    "前面の窓の左にある窓（nav と同じ判定）":
        "the window to the left of the focused window (same judgment as nav)",
    "前面の窓の右にある窓":
        "the window to the right of the focused window",
    "前面の窓の上にある窓":
        "the window above the focused window",
    "前面の窓の下にある窓":
        "the window below the focused window",
    "見えている窓のうち、いちばん大きい窓":
        "the largest of the visible windows",
    "見えている窓のうち、いちばん小さい窓":
        "the smallest of the visible windows",
    "そのモニタでいちばん手前の窓（@monitor:primary・@monitor:eDP-1 など。@monitor:other は、前面の窓がいるのとは別のモニタ）":
        "the frontmost window on that monitor (@monitor:primary, @monitor:eDP-1, etc. @monitor:other is a monitor other than the one the focused window is on)",
    "いまの並び（窓の位置から逆算）の N 番目のタイルの窓（@slot:1 など。番号は layout の窓の列と同じ順。@slot:0 は前面の窓）":
        "the window of the Nth tile of the current arrangement (worked out from the window positions) (@slot:1 etc.; numbered in the same order as the windows of layout; @slot:0 is the focused window)",
    "【複数】見えている窓すべて（前面に近い順）":
        "[multiple] all visible windows (nearest the front first)",
    "【複数】前面の窓以外の、見えている窓すべて":
        "[multiple] all visible windows other than the focused one",
    "【複数】このワークスペースの窓すべて（最小化も含む）":
        "[multiple] all windows of this workspace (including minimized ones)",
    "【複数】そのクラスの窓すべて（@class:firefox など。大文字小文字は区別しない）":
        "[multiple] all windows of that class (@class:firefox etc.; case-insensitive)",
    "名前のグループの、手前のメンバー（@group:作業 など）。layout の窓の列では、グループ全体を 1 つのタイルに置く":
        "the front member of the named group (@group:work etc.). In the window list of layout, the whole group is placed in one tile",
    "その場で選ぶ（layout -i と同じ小窓。先頭 ! でアプリを起動して、その窓。Esc で命令ごと取り消す）":
        "pick on the spot (the same dialog as layout -i; a leading ! launches an app and uses its window; Esc cancels the whole command)",
    "@pick: 選ぶのを取り消しました":
        "@pick: selection cancelled",
    "知らない指定です: {0}（使えるのは {1}）":
        "Unknown spec: {0} (available: {1})",
    "窓が見つかりません: {0}":
        "Window not found: {0}",
    "モニタが見つかりません: {0}（使えるのは primary, {1}）":
        "Monitor not found: {0} (available: primary, {1})",
    "GNOME Shell に接続できません: {0}":
        "Cannot connect to GNOME Shell: {0}",
    "Window Calls の {0} が失敗しました（拡張が無効かもしれません）: {1}":
        "Window Calls {0} failed (the extension may be disabled): {1}",
    "@slot: の後は番号です（@slot:1 など）: {0}":
        "A number must follow @slot: (e.g. @slot:1): {0}",
    "デスクトップの切り替えには、拡張 win-helper@local が要ります（~/.local/share/gnome-shell/extensions/win-helper@local。有効にしたあと、再ログインして読み込ませてください）":
        "Switching desktops needs the extension win-helper@local (~/.local/share/gnome-shell/extensions/win-helper@local. After enabling it, log out and in again to load it)",
    "デスクトップ {0} がありません（1〜{1}）":
        "There is no desktop {0} (1-{1})",
    "win-helper の {0} が失敗しました: {1}":
        "win-helper {0} failed: {1}",
    "↑↓ 選択 ・ Enter 決定 ・ Esc 取り消す":
        "↑↓ select · Enter confirm · Esc cancel",
    "文字で絞り込み":
        "Type to filter",
    "はい":
        "Yes",
    "いいえ":
        "No",
    "Enter 決定 ・ Esc 取り消す":
        "Enter confirm · Esc cancel",
    "窓を選ぶ":
        "Choose a window",
    "↑↓ 選択 ・ Enter 決定 ・ Esc いいえ":
        "↑↓ select · Enter confirm · Esc no",
    "←↑↓→ 動かす ・ Enter 決定 ・ Esc 取り消す":
        "←↑↓→ move · Enter confirm · Esc cancel",
    "ここに決める":
        "Place here",
    " ・ Esc 取り消す":
        " · Esc cancel",
    "文字で絞り込み　先頭に！でアプリを探して新規起動":
        "Type to filter a leading ! searches for an app and launches it",
    "↑↓ 選択 ・ Enter 決定":
        "↑↓ select · Enter confirm",
    " ・ 先頭 ! でアプリを探して新しく起動":
        " · a leading ! searches for an app and launches it",
    "知らない設定: {0}":
        "Unknown setting: {0}",
    "起動しています…":
        "Starting...",
    "\"\"\"win の拡張用の関数群（型の定義）。win が書き出すファイルなので、編集しても上書きされます。\n\n拡張は、このディレクトリに .py を置いて書きます。@command を付けた関数が win の命令になり、\nwin prompt・`win 名前`・ショートカット・登録したコマンドから呼べます。\n\"\"\"\nfrom typing import Callable, Iterator, TypeVar, overload\n\n_F = TypeVar(\"_F\", bound=Callable[..., object])\n\n\nclass WinError(Exception):\n    \"\"\"win の失敗。raise WinError(\"説明\") で命令を止めると、説明が入力欄や通知に出る。\"\"\"\n\n\nclass Window:\n    \"\"\"窓 1 枚。at()・find()・windows()・focused() などで手に入る。\"\"\"\n    @property\n    def id(self) -> int:\n        \"\"\"窓の ID（窓の指定の文字列としても使える）。\"\"\"\n    @property\n    def cls(self) -> str:\n        \"\"\"クラス名（例 firefox、org.gnome.Ptyxis）。\"\"\"\n    @property\n    def title(self) -> str:\n        \"\"\"題名。\"\"\"\n    @property\n    def desktop(self) -> int:\n        \"\"\"この窓があるデスクトップの番号（1 から）。代入すると、その窓をそのデスクトップへ移す（Window Calls だけで動く）。\"\"\"\n    @desktop.setter\n    def desktop(self, n: int) -> None: ...\n    @property\n    def rect(self) -> tuple[int, int, int, int]:\n        \"\"\"位置と大きさ (x, y, 幅, 高さ)。代入すると窓が動く（最大化は解く）。例 w.rect = (0, 32, 960, 1048)\"\"\"\n    @rect.setter\n    def rect(self, r: tuple[int, int, int, int]) -> None: ...\n    @property\n    def maximized(self) -> bool:\n        \"\"\"最大化しているか。\"\"\"\n    @property\n    def minimized(self) -> bool:\n        \"\"\"最小化しているか。\"\"\"\n    def move(self, x: int, y: int) -> None:\n        \"\"\"左上を (x, y) に動かす（大きさはそのまま）。\"\"\"\n    def resize(self, width: int, height: int) -> None:\n        \"\"\"大きさを変える（左上はそのまま）。\"\"\"\n    def focus(self) -> None:\n        \"\"\"前面に出す（最小化していれば戻す）。\"\"\"\n    def max(self) -> None:\n        \"\"\"最大化する。\"\"\"\n    def unmax(self) -> None:\n        \"\"\"最大化を戻す。\"\"\"\n    def min(self) -> None:\n        \"\"\"最小化する。\"\"\"\n    def unmin(self) -> None:\n        \"\"\"最小化を戻す。\"\"\"\n    def above(self) -> None:\n        \"\"\"常に手前にする。\"\"\"\n    def unabove(self) -> None:\n        \"\"\"常に手前をやめる。\"\"\"\n    def close(self) -> None:\n        \"\"\"閉じる。\"\"\"\n\n\n@overload\ndef command(fn: _F) -> _F: ...\n@overload\ndef command(*, name: str | None = None, group: str | None = None) -> Callable[[_F], _F]: ...\ndef command(fn=None, *, name=None, group=None):\n    \"\"\"関数を win の命令にする印。引数の型の注釈（Window・int・float・str・bool）で、打った語を変換する。\n\n    group を書くと、設定のショートカット画面でその目的別のグループに入る（\"窓を選ぶ・移る\"・\"窓を並べる・置く\"・\n    \"保存した並び（セット）\"・\"コマンド\"・\"その他の操作\"。省くと「その他の操作」）。\n    Window の引数には、クラス・題名の一部、ID、@left・@prev などを打てる。既定値に sel(\"@left\") と\n    書くと、省いたときにその窓になる。bool の引数は --名前 で True。\n    int | Window にすると、数字は整数（例 タイルの番号 → at(f\"@slot:{n}\")）、ほかは窓として受け取る。\n    説明文の 1 行目が一覧に出る説明、「引数名: 説明」の行が引数の説明になる。\n    \"\"\"\ndef sel(spec: str) -> Window:\n    \"\"\"命令の引数の既定値に書く窓の指定（例 def swap(a: Window = sel(\"@left\")): …）。呼ばれたときに窓にする。\"\"\"\n\ndef at(sel: str) -> Window:\n    \"\"\"窓の指定（クラス・題名の一部、ID、@left・@prev・@largest・@slot:1・@monitor:primary など）に当たる窓 1 枚。なければ WinError。\n    タイルの番号 n なら at(f\"@slot:{n}\")（0 は前面の窓）。\"\"\"\ndef find(sel: str) -> list[Window]:\n    \"\"\"窓の指定に当たる窓すべて（前面に近い順）。@visible・@others・@all・@class:firefox は複数の窓に当たる。なければ空。\"\"\"\ndef focused() -> Window:\n    \"\"\"前面の窓。\"\"\"\ndef windows() -> list[Window]:\n    \"\"\"今のワークスペースで最小化されていない窓（前面に近い順）。\"\"\"\ndef slot_of(w: Window) -> int | None:\n    \"\"\"いまの並び（窓の位置から逆算）で、w が何番目のタイルにあるか（1 から。@slot:n の n）。並びの中になければ None。\n    （@slot:0 は前面の窓を指すが、slot_of は 0 を返さない）\"\"\"\ndef slots() -> list[Window]:\n    \"\"\"いまの並び（窓の位置から逆算）の窓を、番号順に（slots()[0] が @slot:1）。\"\"\"\ndef resolve(spec: str) -> Window | None:\n    \"\"\"layout の窓の列と同じ書き方を窓にする。- は None（空ける）、!コマンド は起動した窓、\n    クラス名? はその窓（なければ起動）、ほかは at() と同じ。\"\"\"\ndef pick(title: str = \"窓を選ぶ\", slot: int | None = None, launch: bool = True, exclude: list[Window] = [],\n         rect: tuple[int, int, int, int] | None = None) -> Window:\n    \"\"\"layout -i と同じ小窓で、窓をその場で選ぶ（先頭 ! でアプリを起動して、その窓）。取り消したら WinError。\n    小窓の地図にはいまの並びが出る。slot=n なら n 番目のタイルを強調する。launch=False なら起動はさせない。\n    exclude の窓は一覧に出さない（2 つめを選ぶときに 1 つめを除く、など）。rect を渡すと、\n    まだ窓のない場所（分けたばかりのタイルなど）を地図に足して強調する。引数を省いたら選ばせる例:\n    def place(n: int, w: Window | None = None): w = w or pick(f\"タイル {n} に置く窓\", slot=n)\"\"\"\n\nclass Item:\n    \"\"\"一覧の 1 行。value は選ばれたときに返ってくる値（任意）。\"\"\"\n    label: str\n    sub: str\n    icon: str\n    value: object\n    def __init__(self, label: str, sub: str = \"\", icon: str = \"\", value: object = None) -> None: ...\n\nclass Map:\n    \"\"\"ミニ地図。rects は作業領域に対する割合の (x, y, 幅, 高さ) のリスト（tiles() の結果を、作業領域で割った値）。\n    labels は各タイルの文字、current は強調するタイルの添字（-1 で強調なし）、free は点線にするタイルの真偽のリスト、\n    monitor は、その作業領域があるモニタの添字（複数のモニタを並べて描くとき）。\"\"\"\n    rects: list[tuple[float, float, float, float]]\n    labels: list[str] | None\n    current: int\n    free: list[bool] | None\n    monitor: int | None\n    def __init__(self, rects: list[tuple[float, float, float, float]], labels: list[str] | None = None, current: int = -1,\n                 free: list[bool] | None = None, monitor: int | None = None) -> None: ...\n\nclass Event:\n    \"\"\"Dialog から返ってくる出来事。kind は \"select\"（行を決めた。item・index・via=\"enter\" か \"tab\"）・\"key\"（key）・\"text\"（text）・\n    \"highlight\"（選択が動いた。item・index。highlight=True のとき）・\"launched\"（! でアプリを起動した。window がその窓）・\"cancel\"。\"\"\"\n    kind: str\n    item: Item | None\n    index: int | None\n    via: str | None\n    key: str | None\n    text: str | None\n    window: Window | None\n\nclass Dialog:\n    \"\"\"対話型の小窓。with で開き、events() で出来事を 1 つずつ受け取り、出来事に応じて行・地図・通知を更新する（小窓は描画だけ、状態は拡張が持つ）。\n    出来事を受け取ったあと、次を待つ前に、更新した内容が小窓へ渡る。キーは keys に挙げたものだけが \"key\" の出来事になる。例（地図の上で置き先を選ぶ）:\n    with Dialog(\"置き先を選ぶ\", entry=False, keys=(\"Left\", \"Right\")) as d:\n        d.rows([Item(\"ここに決める\")]); d.map(Map(rects, current=i))\n        for ev in d.events():\n            if ev.kind == \"key\": i += 1 if ev.key == \"Right\" else -1; d.map(Map(rects, current=i))\n            elif ev.kind == \"select\": return i\n            elif ev.kind == \"cancel\": return None\"\"\"\n    title: str\n    hint: str\n    placeholder: str\n    def __init__(self, title: str = \"\", *, hint: str = \"\", placeholder: str = \"文字で絞り込み\", filter: bool = True,\n                 entry: bool = True, ask: bool = False, show_list: bool = True, launch: bool = False, highlight: bool = False,\n                 keys: tuple[str, ...] = (), keep_selection: bool = False, empty: str = \"\", chip: str = \"\", window_title: str = \"win\", vim: bool = False,\n                 numbers: bool = False) -> None:\n        \"\"\"title: 題名。hint: 下の案内文。placeholder: 入力欄の説明。filter: 入力で行を絞り込む。entry: 入力欄を出す。\n        ask: 文字を入力する画面（Enter で \"text\" の出来事）。show_list: 行の一覧を出す。launch: 先頭 ! でアプリを起動できる（\"launched\"）。\n        highlight: 選択が動くたびに \"highlight\" の出来事を返す。keys: 受け取りたいキー（\"Left\"・\"Right\"・\"Up\"・\"Down\"・\"Ctrl+s\" など）。\n        keep_selection: 出来事のあと、選択中の行の位置を保つ。empty: 行が 1 つもないときの文。chip: 入力欄の左の印。\n        window_title: 小窓の上の題名。vim: 入力欄のない一覧のキー（j/k・g/G・l で決定・h/q で取消・1〜9 で直接）を使う。\n        numbers: 先頭の 9 行に番号を付ける（vim の 1〜9 と組み合わせる）。\"\"\"\n    def rows(self, items: list[Item]) -> None:\n        \"\"\"一覧の行を差し替える。\"\"\"\n    def map(self, m: Map | None) -> None:\n        \"\"\"ミニ地図を差し替える（None で隠す）。\"\"\"\n    def notice(self, text: str) -> None:\n        \"\"\"赤字の通知を出す（\"\" で消す）。\"\"\"\n    def keys(self, *names: str) -> None:\n        \"\"\"親へ渡してほしいキーを差し替える。\"\"\"\n    def text(self, value: str) -> None:\n        \"\"\"入力欄の文字を置き換える（次に小窓へ渡すとき 1 回だけ）。\"\"\"\n    def events(self) -> Iterator[Event]:\n        \"\"\"小窓を開いて、出来事を 1 つずつ返す。取り消す（Esc）と \"cancel\" の出来事を返して終わる。\"\"\"\n    def __enter__(self) -> Dialog: ...\n    def __exit__(self, *exc: object) -> bool: ...\n\ndef window_items(exclude: list[Window] = []) -> list[Item]:\n    \"\"\"今のワークスペースで最小化されていない窓を、一覧の行にする（前面に近い順。value は Window）。exclude の窓は除く。\"\"\"\ndef choose(title: str, items: list[Item], *, preview: Callable[[Item], Map] | None = None, placeholder: str = \"文字で絞り込み\",\n           hint: str = \"\", filter: bool = True) -> Item | None:\n    \"\"\"一覧から 1 つ選ぶ。選んだ Item、Esc なら None。preview(item) -> Map を渡すと、選択が動くたびにミニ地図を出す。\n    例 x = choose(\"型を選ぶ\", [Item(n, e) for n, e in layouts().items()])\"\"\"\ndef confirm(title: str, text: str = \"\", *, yes: str = \"はい\", no: str = \"いいえ\") -> bool:\n    \"\"\"はい・いいえを選ぶ。はいなら True（Esc は False）。\"\"\"\ndef ask(title: str, *, placeholder: str = \"\", initial: str = \"\", hint: str = \"\") -> str | None:\n    \"\"\"1 行の文字を入力する。入力した文字、Esc なら None。\"\"\"\ndef pick_tile(title: str, rects: list[tuple[float, float, float, float]], *, labels: list[str] | None = None, current: int = 0,\n              free: list[bool] | None = None, monitor: int | None = None) -> int | None:\n    \"\"\"ミニ地図の上でタイルを選ぶ（矢印キーで、その向きの隣のタイルへ）。選んだタイルの添字、Esc なら None。\"\"\"\ndef pick_window(title: str = \"窓を選ぶ\", *, launch: bool = True, exclude: list[Window] = [], map: Map | None = None) -> Window | None:\n    \"\"\"窓を 1 枚選ぶ（launch なら、先頭 ! でアプリを起動してその窓）。選んだ窓、Esc なら None（pick と違い、例外にしない）。\n    map を渡すと、ミニ地図も出す。\"\"\"\n\ndef stack(n: int = 0) -> list[Window]:\n    \"\"\"n 番目のタイル（0 は前面の窓のいるタイル）に重なっている窓（層）を、巡回の順（ID の昇順）に返す。同じ位置（枠の 4 辺が 8px 以内）にある、\n    最小化されていない窓が層。手前の層は、重なり順がいちばん上のもの。層が 1 枚だけなら、要素 1 つのリスト。\"\"\"\ndef cycle(n: int = 0, d: int = 1) -> Window:\n    \"\"\"n 番目のタイルの重なりで、いま手前の層から d 層（負なら前へ）ずらした窓を前面に出して返す。層は一巡する。重なりがなければ WinError。\n    例 cycle(0)  # 前面の窓のいるタイルで、次の層を表示する\"\"\"\nclass Group:\n    \"\"\"窓のグループ（名前つき・保存つき。~/.local/state/win/groups.json）。メンバーは 1 つの枠を共有し、タブのように切り替わる。\n    1 つの窓は高々 1 つのグループに入る。閉じた窓は、自動でメンバーから外れる。例（手前の窓のグループを次のメンバーへ）:\n    g = group_of(focused())\n    if g: g.next()\"\"\"\n    name: str\n    @property\n    def members(self) -> list[Window]:\n        \"\"\"メンバー（巡回の順）。\"\"\"\n    @property\n    def active(self) -> Window | None:\n        \"\"\"いま手前のメンバー。\"\"\"\n    @property\n    def rect(self) -> tuple[int, int, int, int]:\n        \"\"\"グループの枠。手前のメンバーがいまいる枠（動かしたものに追従する）。\"\"\"\n    def add(self, *windows: Window) -> None:\n        \"\"\"窓を足し、グループの枠へ置いて、最後に足した窓を手前にする。ほかのグループにいた窓は移る。\"\"\"\n    def remove(self, *windows: Window) -> None:\n        \"\"\"窓をグループから外す。\"\"\"\n    def delete(self) -> None:\n        \"\"\"グループを消す（窓は閉じない）。\"\"\"\n    def next(self, d: int = 1) -> Window:\n        \"\"\"いま手前のメンバーから d 個（負なら前へ）ずれたメンバーを、グループの枠へ置いて前面に出して返す。メンバーは一巡する。\"\"\"\n    def show(self) -> None:\n        \"\"\"全メンバーをグループの枠へ置き（別のデスクトップ・最小化も今のデスクトップへ戻す）、手前のメンバーを前面に出す。\"\"\"\n    def place(self, rect: tuple[int, int, int, int]) -> None:\n        \"\"\"グループの枠を rect に変えて、全メンバーをそこへ置く。\"\"\"\n\ndef groups() -> list[Group]:\n    \"\"\"いまあるグループすべて。\"\"\"\ndef group(name: str, *windows: Window) -> Group:\n    \"\"\"name のグループ。windows を渡すと、その窓で新しく作る（すでにあれば足す）。なければ WinError。\n    例 group(\"作業\", at(\"firefox\"), at(\"ptyxis\")).show()\"\"\"\ndef group_of(w: Window) -> Group | None:\n    \"\"\"窓 w の属するグループ。どこにも属さなければ None。\"\"\"\ndef desktops() -> tuple[int, int]:\n    \"\"\"(いまのデスクトップの番号, デスクトップの数)。番号は 1 から。数は、動的ワークスペースでは末尾の空のものを含む。\n    拡張 win-helper@local が要る（なければ WinError）。\"\"\"\ndef switch_desktop(n: int, relative: bool = False) -> None:\n    \"\"\"n 番目（1 から）のデスクトップへ切り替える。relative=True なら、いまから n 個（負なら前へ）ずれたデスクトップへ。\n    なければ WinError。拡張 win-helper@local が要る。\"\"\"\ndef layout(expr: str, *windows: Window | str, gap: int | None = None) -> None:\n    \"\"\"型 expr（名前か式。例 \"lr\"・\"v(1,2)\"・\"1,2:1/1\"）のタイルに、windows を順に並べる。窓の指定の文字列も書ける。\n    例 layout(\"v(1,1)\", focused(), at(\"@prev\"))\"\"\"\ndef tiles(expr: str, rect: tuple[int, int, int, int] | None = None) -> list[tuple[int, int, int, int]]:\n    \"\"\"rect（省くと area()）を型 expr で分けた、各タイルの (x, y, 幅, 高さ)。タイルの間には設定の隙間を取る。\n    例 tiles(\"1/1\", w.rect) は w の場所を上下に分けた 2 つ\"\"\"\ndef layouts() -> dict[str, str]:\n    \"\"\"型の一覧 {名前: 式}。\"\"\"\ndef area() -> tuple[int, int, int, int]:\n    \"\"\"窓を置ける領域 (x, y, 幅, 高さ)。基準のモニタ（前面の窓があるモニタ）から余白を除いたもの。\"\"\"\ndef nav(direction: str) -> None:\n    \"\"\"\"next\"・\"prev\"（いまの並びの番号順）か \"left\"・\"right\"・\"up\"・\"down\" の向きの窓へフォーカスを移す。\"\"\"\n\ndef apply_set(name: str) -> None:\n    \"\"\"保存したセットを適用する（win set 名前 と同じ）。\"\"\"\ndef run_command(name: str) -> None:\n    \"\"\"登録したコマンドを実行する（win run 名前 と同じ）。拡張の命令は、Python の関数として import して呼ぶ。\"\"\"\ndef run(line: str) -> None:\n    \"\"\"win の命令を文字列で実行する（例 run(\"max -w @prev\")）。複数行なら上から順に。失敗したら WinError。\"\"\"\n\ndef launch(cmdline: str, timeout: float = 20) -> Window:\n    \"\"\"コマンドを起動し、新しく出た窓を返す（例 launch(\"gnome-text-editor\")）。出なければ WinError。\"\"\"\ndef browse(*urls: str) -> None:\n    \"\"\"Firefox を新しい窓で開き、URL をタブとして並べる。\"\"\"\ndef term(*dirs: str) -> None:\n    \"\"\"端末（Ptyxis）を、作業ディレクトリごとのタブつきで新しく開く。\"\"\"\ndef notify(text: str, title: str = \"win\") -> None:\n    \"\"\"デスクトップの通知を出す。\"\"\"\n":
        "\"\"\"Functions for win extensions (type definitions). win writes this file, so any edits are overwritten.\n\nWrite an extension by putting a .py in this directory. A function with @command becomes a win command,\ncallable from win prompt, `win NAME`, shortcuts and registered commands.\n\"\"\"\nfrom typing import Callable, Iterator, TypeVar, overload\n\n_F = TypeVar(\"_F\", bound=Callable[..., object])\n\n\nclass WinError(Exception):\n    \"\"\"A win failure. Stop a command with raise WinError(\"message\") and the message appears in the input box or a notification.\"\"\"\n\n\nclass Window:\n    \"\"\"One window. Obtained with at(), find(), windows(), focused() and so on.\"\"\"\n    @property\n    def id(self) -> int:\n        \"\"\"The window's ID (it can also be used as a window spec string).\"\"\"\n    @property\n    def cls(self) -> str:\n        \"\"\"The class name (e.g. firefox, org.gnome.Ptyxis).\"\"\"\n    @property\n    def title(self) -> str:\n        \"\"\"The title.\"\"\"\n    @property\n    def desktop(self) -> int:\n        \"\"\"The number (from 1) of the desktop this window is on. Assigning moves the window to that desktop (works with Window Calls alone).\"\"\"\n    @desktop.setter\n    def desktop(self, n: int) -> None: ...\n    @property\n    def rect(self) -> tuple[int, int, int, int]:\n        \"\"\"Position and size (x, y, width, height). Assigning moves the window (and unmaximizes it). e.g. w.rect = (0, 32, 960, 1048)\"\"\"\n    @rect.setter\n    def rect(self, r: tuple[int, int, int, int]) -> None: ...\n    @property\n    def maximized(self) -> bool:\n        \"\"\"Whether it is maximized.\"\"\"\n    @property\n    def minimized(self) -> bool:\n        \"\"\"Whether it is minimized.\"\"\"\n    def move(self, x: int, y: int) -> None:\n        \"\"\"Move the top-left corner to (x, y) (the size stays).\"\"\"\n    def resize(self, width: int, height: int) -> None:\n        \"\"\"Change the size (the top-left corner stays).\"\"\"\n    def focus(self) -> None:\n        \"\"\"Bring it to the front (restoring it if minimized).\"\"\"\n    def max(self) -> None:\n        \"\"\"Maximize.\"\"\"\n    def unmax(self) -> None:\n        \"\"\"Restore from maximized.\"\"\"\n    def min(self) -> None:\n        \"\"\"Minimize.\"\"\"\n    def unmin(self) -> None:\n        \"\"\"Restore from minimized.\"\"\"\n    def above(self) -> None:\n        \"\"\"Keep it always on top.\"\"\"\n    def unabove(self) -> None:\n        \"\"\"Stop keeping it always on top.\"\"\"\n    def close(self) -> None:\n        \"\"\"Close.\"\"\"\n\n\n@overload\ndef command(fn: _F) -> _F: ...\n@overload\ndef command(*, name: str | None = None, group: str | None = None) -> Callable[[_F], _F]: ...\ndef command(fn=None, *, name=None, group=None):\n    \"\"\"A mark that turns a function into a win command. The type annotations of the arguments (Window, int, float, str, bool) convert the typed words.\n\n    With group, it goes into that group on the settings window's shortcuts page (\"Choose and move between windows\", \"Arrange and place windows\",\n    \"Saved arrangements (sets)\", \"Command\", \"Other operations\". If omitted, \"Other operations\").\n    A Window argument accepts a class, part of a title, an ID, @left, @prev and so on. Writing sel(\"@left\")\n    as the default makes it that window when omitted. A bool argument becomes True with --name.\n    With int | Window, a number is received as an integer (e.g. a tile number -> at(f\"@slot:{n}\")) and anything else as a window.\n    The first line of the docstring is the description shown in lists; lines of \"arg: description\" describe arguments.\n    \"\"\"\ndef sel(spec: str) -> Window:\n    \"\"\"A window spec to write as the default of a command's argument (e.g. def swap(a: Window = sel(\"@left\")): ...). It becomes a window when called.\"\"\"\n\ndef at(sel: str) -> Window:\n    \"\"\"The one window matching a window spec (class, part of a title, ID, @left, @prev, @largest, @slot:1, @monitor:primary, etc.). WinError if none.\n    For a tile number n, at(f\"@slot:{n}\") (0 is the focused window).\"\"\"\ndef find(sel: str) -> list[Window]:\n    \"\"\"All windows matching a window spec (nearest the front first). @visible, @others, @all and @class:firefox match several windows. Empty if none.\"\"\"\ndef focused() -> Window:\n    \"\"\"The focused window.\"\"\"\ndef windows() -> list[Window]:\n    \"\"\"The windows of the current workspace that are not minimized (nearest the front first).\"\"\"\ndef slot_of(w: Window) -> int | None:\n    \"\"\"Which tile of the current arrangement (worked out from the window positions) w is in (from 1; the n of @slot:n). None if it is not in the arrangement.\n    (@slot:0 means the focused window, but slot_of never returns 0)\"\"\"\ndef slots() -> list[Window]:\n    \"\"\"The windows of the current arrangement (worked out from the window positions), in numbered order (slots()[0] is @slot:1).\"\"\"\ndef resolve(spec: str) -> Window | None:\n    \"\"\"Turn the same notation as the window list of layout into a window. - is None (leave empty), !command is the launched window,\n    CLASS? is that window (launched if there is none), and anything else is the same as at().\"\"\"\ndef pick(title: str = \"Choose a window\", slot: int | None = None, launch: bool = True, exclude: list[Window] = [],\n         rect: tuple[int, int, int, int] | None = None) -> Window:\n    \"\"\"Choose a window on the spot with the same dialog as layout -i (a leading ! launches an app and uses its window). WinError if cancelled.\n    The dialog's map shows the current arrangement. With slot=n, the nth tile is highlighted. With launch=False, nothing is launched.\n    Windows in exclude are left out of the list (e.g. to leave out the first when choosing a second). If rect is given,\n    a place with no window yet (such as a tile just split) is added to the map and highlighted. An example that lets the user choose when the argument is omitted:\n    def place(n: int, w: Window | None = None): w = w or pick(f\"Window for tile {n}\", slot=n)\"\"\"\n\nclass Item:\n    \"\"\"One row of a list. value is the value returned when it is chosen (anything).\"\"\"\n    label: str\n    sub: str\n    icon: str\n    value: object\n    def __init__(self, label: str, sub: str = \"\", icon: str = \"\", value: object = None) -> None: ...\n\nclass Map:\n    \"\"\"A minimap. rects is a list of (x, y, width, height) as proportions of the work area (the result of tiles(), divided by the work area).\n    labels are the texts of the tiles, current is the index of the tile to highlight (-1 for none), free is a list of booleans for the tiles drawn dotted,\n    and monitor is the index of the monitor the work area is on (when several monitors are drawn side by side).\"\"\"\n    rects: list[tuple[float, float, float, float]]\n    labels: list[str] | None\n    current: int\n    free: list[bool] | None\n    monitor: int | None\n    def __init__(self, rects: list[tuple[float, float, float, float]], labels: list[str] | None = None, current: int = -1,\n                 free: list[bool] | None = None, monitor: int | None = None) -> None: ...\n\nclass Event:\n    \"\"\"An event returned from a Dialog. kind is \"select\" (a row was chosen: item, index, via=\"enter\" or \"tab\"), \"key\" (key), \"text\" (text),\n    \"highlight\" (the selection moved: item, index; when highlight=True), \"launched\" (an app was launched with !; window is that window) or \"cancel\".\"\"\"\n    kind: str\n    item: Item | None\n    index: int | None\n    via: str | None\n    key: str | None\n    text: str | None\n    window: Window | None\n\nclass Dialog:\n    \"\"\"An interactive dialog. Open it with with, receive events one by one with events(), and update the rows, map and notice according to each event (the dialog only draws; the extension holds the state).\n    After an event is received, and before waiting for the next, the updates are sent to the dialog. Only the keys listed in keys become \"key\" events. Example (choosing a destination on a map):\n    with Dialog(\"Choose a destination\", entry=False, keys=(\"Left\", \"Right\")) as d:\n        d.rows([Item(\"Place here\")]); d.map(Map(rects, current=i))\n        for ev in d.events():\n            if ev.kind == \"key\": i += 1 if ev.key == \"Right\" else -1; d.map(Map(rects, current=i))\n            elif ev.kind == \"select\": return i\n            elif ev.kind == \"cancel\": return None\"\"\"\n    title: str\n    hint: str\n    placeholder: str\n    def __init__(self, title: str = \"\", *, hint: str = \"\", placeholder: str = \"Type to filter\", filter: bool = True,\n                 entry: bool = True, ask: bool = False, show_list: bool = True, launch: bool = False, highlight: bool = False,\n                 keys: tuple[str, ...] = (), keep_selection: bool = False, empty: str = \"\", chip: str = \"\", window_title: str = \"win\", vim: bool = False,\n                 numbers: bool = False) -> None:\n        \"\"\"title: the title. hint: the guide text at the bottom. placeholder: the description of the input box. filter: filter the rows by what is typed. entry: show the input box.\n        ask: a screen for typing text (Enter gives a \"text\" event). show_list: show the list of rows. launch: a leading ! can launch an app (\"launched\").\n        highlight: return a \"highlight\" event each time the selection moves. keys: the keys to receive (\"Left\", \"Right\", \"Up\", \"Down\", \"Ctrl+s\", etc.).\n        keep_selection: keep the position of the selected row after an event. empty: the text when there are no rows. chip: the mark at the left of the input box.\n        window_title: the title above the dialog. vim: use the keys of a list without an input box (j/k, g/G, l to confirm, h/q to cancel, 1-9 directly).\n        numbers: number the first 9 rows (combine with vim's 1-9).\"\"\"\n    def rows(self, items: list[Item]) -> None:\n        \"\"\"Replace the rows of the list.\"\"\"\n    def map(self, m: Map | None) -> None:\n        \"\"\"Replace the minimap (None hides it).\"\"\"\n    def notice(self, text: str) -> None:\n        \"\"\"Show a notice in red (\"\" clears it).\"\"\"\n    def keys(self, *names: str) -> None:\n        \"\"\"Replace the keys to be passed to the parent.\"\"\"\n    def text(self, value: str) -> None:\n        \"\"\"Replace the text of the input box (once, the next time it is sent to the dialog).\"\"\"\n    def events(self) -> Iterator[Event]:\n        \"\"\"Open the dialog and return events one by one. Cancelling (Esc) returns a \"cancel\" event and ends.\"\"\"\n    def __enter__(self) -> Dialog: ...\n    def __exit__(self, *exc: object) -> bool: ...\n\ndef window_items(exclude: list[Window] = []) -> list[Item]:\n    \"\"\"Turn the windows of the current workspace that are not minimized into list rows (nearest the front first; value is the Window). Windows in exclude are left out.\"\"\"\ndef choose(title: str, items: list[Item], *, preview: Callable[[Item], Map] | None = None, placeholder: str = \"Type to filter\",\n           hint: str = \"\", filter: bool = True) -> Item | None:\n    \"\"\"Choose one from a list. The chosen Item, or None for Esc. If preview(item) -> Map is given, a minimap is shown each time the selection moves.\n    e.g. x = choose(\"Choose a layout\", [Item(n, e) for n, e in layouts().items()])\"\"\"\ndef confirm(title: str, text: str = \"\", *, yes: str = \"Yes\", no: str = \"No\") -> bool:\n    \"\"\"Choose yes or no. True for yes (Esc is False).\"\"\"\ndef ask(title: str, *, placeholder: str = \"\", initial: str = \"\", hint: str = \"\") -> str | None:\n    \"\"\"Type one line of text. The typed text, or None for Esc.\"\"\"\ndef pick_tile(title: str, rects: list[tuple[float, float, float, float]], *, labels: list[str] | None = None, current: int = 0,\n              free: list[bool] | None = None, monitor: int | None = None) -> int | None:\n    \"\"\"Choose a tile on the minimap (the arrow keys go to the neighbouring tile in that direction). The index of the chosen tile, or None for Esc.\"\"\"\ndef pick_window(title: str = \"Choose a window\", *, launch: bool = True, exclude: list[Window] = [], map: Map | None = None) -> Window | None:\n    \"\"\"Choose one window (with launch, a leading ! launches an app and uses its window). The chosen window, or None for Esc (unlike pick, no exception).\n    If map is given, a minimap is shown too.\"\"\"\n\ndef stack(n: int = 0) -> list[Window]:\n    \"\"\"The windows (layers) stacked on the nth tile (0 is the tile of the focused window), in cycling order (ascending ID). Windows at the same position (all 4 edges of the frame within 8px) and\n    not minimized are layers. The front layer is the one highest in the stacking order. If there is only one layer, a list of one element.\"\"\"\ndef cycle(n: int = 0, d: int = 1) -> Window:\n    \"\"\"In the stack of the nth tile, bring to the front and return the window d layers (negative for backwards) away from the current front layer. The layers go round. WinError if there is no stack.\n    e.g. cycle(0)  # show the next layer in the tile of the focused window\"\"\"\nclass Group:\n    \"\"\"A window group (named, persistent; ~/.local/state/win/groups.json). The members share one frame and switch like tabs.\n    A window belongs to at most one group. Closed windows leave the group automatically. Example (the group of the front window, to its next member):\n    g = group_of(focused())\n    if g: g.next()\"\"\"\n    name: str\n    @property\n    def members(self) -> list[Window]:\n        \"\"\"The members (in cycling order).\"\"\"\n    @property\n    def active(self) -> Window | None:\n        \"\"\"The member at the front now.\"\"\"\n    @property\n    def rect(self) -> tuple[int, int, int, int]:\n        \"\"\"The group's frame. The frame the front member is in now (it follows when that is moved).\"\"\"\n    def add(self, *windows: Window) -> None:\n        \"\"\"Add windows, place them in the group's frame, and bring the last one added to the front. Windows that were in another group move over.\"\"\"\n    def remove(self, *windows: Window) -> None:\n        \"\"\"Remove windows from the group.\"\"\"\n    def delete(self) -> None:\n        \"\"\"Delete the group (the windows are not closed).\"\"\"\n    def next(self, d: int = 1) -> Window:\n        \"\"\"Place in the group's frame, bring to the front and return the member d away (negative for backwards) from the current front member. The members go round.\"\"\"\n    def show(self) -> None:\n        \"\"\"Place all members in the group's frame (windows on another desktop or minimized are brought back to this desktop) and bring the front member to the front.\"\"\"\n    def place(self, rect: tuple[int, int, int, int]) -> None:\n        \"\"\"Change the group's frame to rect and place all members there.\"\"\"\n\ndef groups() -> list[Group]:\n    \"\"\"All the groups that exist.\"\"\"\ndef group(name: str, *windows: Window) -> Group:\n    \"\"\"The group called name. If windows are given, a new group is made from them (or they are added if it already exists). WinError if there is none.\n    e.g. group(\"work\", at(\"firefox\"), at(\"ptyxis\")).show()\"\"\"\ndef group_of(w: Window) -> Group | None:\n    \"\"\"The group window w belongs to. None if it belongs to none.\"\"\"\ndef desktops() -> tuple[int, int]:\n    \"\"\"(the current desktop's number, the number of desktops). Numbers start at 1. With dynamic workspaces, the count includes the empty one at the end.\n    Needs the extension win-helper@local (WinError if it is missing).\"\"\"\ndef switch_desktop(n: int, relative: bool = False) -> None:\n    \"\"\"Switch to the nth desktop (from 1). With relative=True, to the desktop n away (negative for backwards) from the current one.\n    WinError if there is none. Needs the extension win-helper@local.\"\"\"\ndef layout(expr: str, *windows: Window | str, gap: int | None = None) -> None:\n    \"\"\"Arrange windows in order in the tiles of the layout expr (a name or an expression, e.g. \"lr\", \"v(1,2)\", \"1,2:1/1\"). Window spec strings are also accepted.\n    e.g. layout(\"v(1,1)\", focused(), at(\"@prev\"))\"\"\"\ndef tiles(expr: str, rect: tuple[int, int, int, int] | None = None) -> list[tuple[int, int, int, int]]:\n    \"\"\"The (x, y, width, height) of each tile when rect (area() if omitted) is divided by the layout expr. The configured gap is left between tiles.\n    e.g. tiles(\"1/1\", w.rect) gives the two halves of w's place, top and bottom\"\"\"\ndef layouts() -> dict[str, str]:\n    \"\"\"The layouts {name: expression}.\"\"\"\ndef area() -> tuple[int, int, int, int]:\n    \"\"\"The area where windows can be placed (x, y, width, height): the reference monitor (the one with the focused window) minus the margins.\"\"\"\ndef nav(direction: str) -> None:\n    \"\"\"Move the focus to the window in the direction \"next\" or \"prev\" (in the current arrangement's numbering) or \"left\", \"right\", \"up\", \"down\".\"\"\"\n\ndef apply_set(name: str) -> None:\n    \"\"\"Apply a saved set (the same as win set NAME).\"\"\"\ndef run_command(name: str) -> None:\n    \"\"\"Run a registered command (the same as win run NAME). Extension commands are imported and called as Python functions.\"\"\"\ndef run(line: str) -> None:\n    \"\"\"Run win commands given as a string (e.g. run(\"max -w @prev\")). Multiple lines run from the top. WinError on failure.\"\"\"\n\ndef launch(cmdline: str, timeout: float = 20) -> Window:\n    \"\"\"Launch a command and return the window that newly appeared (e.g. launch(\"gnome-text-editor\")). WinError if none appears.\"\"\"\ndef browse(*urls: str) -> None:\n    \"\"\"Open Firefox in a new window and arrange the URLs as tabs.\"\"\"\ndef term(*dirs: str) -> None:\n    \"\"\"Open a terminal (Ptyxis) anew, with a tab per working directory.\"\"\"\ndef notify(text: str, title: str = \"win\") -> None:\n    \"\"\"Show a desktop notification.\"\"\"\n",
    "# win の拡張。@command を付けた関数が win の命令になる（win 名前・入力欄の補完・ショートカットで呼べる）。\n#   使える関数の一覧:   win help api   （宣言と説明の全文は同じフォルダの winapi.pyi）\n#   引数の型:           Window・int・float・str・bool（打った語をこの型に変換する。bool は --名前 で True）\n#   窓の引数の既定値:   sel(\"@focused\")・sel(\"@left\")・sel(\"@prev\") など\n#   説明文:             1 行目が一覧に出る説明。「引数名: 説明」の行が引数の説明になる\n#   nvim では:          \\wh 書き方と関数の一覧・K カーソル位置の名前の説明・:WinHelp 名前\n#   保存した後、設定画面の「再読み込み」で一覧に出る。端末なら win help ですぐ確かめられる。\nfrom winapi import Window, command, sel\n\n\n@command\ndef {name}(w: Window = sel(\"@focused\")):\n    \"\"\"（ここに 1 行の説明。入力欄の候補と win help に出ます）\n    w: 対象の窓（省くと前面の窓）\n    \"\"\"\n    ...\n":
        "# A win extension. A function with @command becomes a win command (callable as win NAME, from the input box completion, and from shortcuts).\n#   Available functions:   win help api   (the full declarations and docs are in winapi.pyi in the same folder)\n#   Argument types:        Window, int, float, str, bool (the typed word is converted to the type; bool becomes True with --name)\n#   Defaults for windows:  sel(\"@focused\"), sel(\"@left\"), sel(\"@prev\"), etc.\n#   Docstring:             the first line is the description shown in the list; lines of \"arg: description\" describe arguments\n#   In nvim:               \\wh how to write and the function list; K docs of the name under the cursor; :WinHelp NAME\n#   After saving, \"Reload\" in the settings window lists it. In a terminal, you can check at once with win help.\nfrom winapi import Window, command, sel\n\n\n@command\ndef {name}(w: Window = sel(\"@focused\")):\n    \"\"\"(One-line description here. It appears in the input box candidates and in win help)\n    w: target window (the focused window if omitted)\n    \"\"\"\n    ...\n",
    "from winapi import Window, command, sel, layout, focused, find\n\n\n@command\ndef pair(other: Window = sel(\"@prev\")):\n    \"\"\"前面の窓と other を左右に並べる\n    other: 右に置く窓（省くと直前の窓）\n    \"\"\"\n    layout(\"lr\", focused(), other)\n\n\n@command\ndef minall():\n    \"\"\"前面以外の窓をすべて最小化する\"\"\"\n    for w in find(\"@others\"):\n        w.min()":
        "from winapi import Window, command, sel, layout, focused, find\n\n\n@command\ndef pair(other: Window = sel(\"@prev\")):\n    \"\"\"Arrange the focused window and other side by side\n    other: the window to place on the right (the previous window if omitted)\n    \"\"\"\n    layout(\"lr\", focused(), other)\n\n\n@command\ndef minall():\n    \"\"\"Minimize all windows except the focused one\"\"\"\n    for w in find(\"@others\"):\n        w.min()",
    "整数":
        "integer",
    "数":
        "number",
    "文字列":
        "string",
    "オン/オフ":
        "on/off",
    "win の拡張用の関数群。":
        "Functions for win extensions.",
    "@command　または　@command(name=\"別名\")":
        "@command or @command(name=\"alias\")",
    "命令を作る":
        "Define commands",
    "窓を探す・選ぶ（Window を返す）":
        "Find and choose windows (return a Window)",
    "窓 1 枚の情報と操作（w は at() などで得た Window）":
        "Information and operations of one window (w is a Window obtained from at() etc.)",
    "並べる・フォーカスを移す":
        "Arrange and move the focus",
    "登録したもの・win の命令を呼ぶ":
        "Call registered things and win commands",
    "起動・通知":
        "Launch and notify",
    "重なった窓（層）":
        "Stacked windows (layers)",
    "デスクトップ（ワークスペース）":
        "Desktops (workspaces)",
    "窓のグループ（名前つき・保存つき）":
        "Window groups (named, persistent)",
    "対話型の小窓（1 回で選ぶ）":
        "Interactive dialogs (choose once)",
    "対話型の小窓（やり取りを回す）":
        "Interactive dialogs (run an exchange)",
    "  ・@command を付けた関数が win の命令になる（win 名前・入力欄・ショートカット・登録したコマンドで呼べる）":
        "  - A function with @command becomes a win command (callable as win NAME, from the input box, shortcuts and registered commands)",
    "  ・引数の型の注釈（Window・int・float・str・bool）で、打った語を変換する。窓の既定値は sel(\"@left\") のように書く":
        "  - Type annotations of arguments (Window, int, float, str, bool) convert the typed words. Write a default for a window like sel(\"@left\")",
    "  ・int | Window にすると、数字は整数（タイルの番号など）、ほかは窓として受け取る":
        "  - With int | Window, a number is received as an integer (a tile number etc.) and anything else as a window",
    "  ・省いたらその場で選ばせるには、既定値を sel(\"@pick\") にするか、Window | None にして pick() を呼ぶ":
        "  - To let the user pick on the spot when omitted, make the default sel(\"@pick\"), or use Window | None and call pick()",
    "  ・説明文の 1 行目が一覧に出る説明。「引数名: 説明」の行が引数の説明":
        "  - The first line of the docstring is the description shown in lists. Lines of \"arg: description\" describe arguments",
    "  ・ほかの拡張の関数は、ふつうに import して呼べる（例 from swap import exchange）":
        "  - Functions of other extensions can be imported and called as usual (e.g. from swap import exchange)",
    "\n■ 窓の指定（at・find・sel・layout に書く文字列）":
        "\n■ Window specs (strings to write in at, find, sel, layout)",
    "  クラス・題名の一部（例 \"firefox\"）、ID、または:":
        "  class or part of the title (e.g. \"firefox\"), an ID, or:",
    "\n■ 例":
        "\n■ Examples",
    "組み込みの命令（詳しくは win help 名前）":
        "Built-in commands (see win help NAME for details)",
    "\nほかの一覧: win help api（拡張で使える関数）・commands（登録したコマンド）・sets（セット）・layouts（型）":
        "\nOther lists: win help api (functions for extensions), commands (registered commands), sets (sets), layouts (layouts)",
    "\n位置・状態での窓の指定（窓を書ける所ならどこでも。【複数】は当たる窓すべてにかかる）":
        "\nWindow specs by position or state (usable wherever a window can be written; [multiple] applies to every matching window)",
    "ここ":
        "here",
    "選ぶのを取り消しました":
        "Selection cancelled",
    "{0}:{1}: 文法エラー: {2}":
        "{0}:{1}: syntax error: {2}",
    "win の拡張（Python）で使えるもの。from winapi import 名前 で使う。定義の全文: {0}":
        "What can be used in win extensions (Python). Use with from winapi import NAME. Full definitions: {0}",
    "セットが見つかりません: {0}（一覧は win help sets）":
        "Set not found: {0} (list them with win help sets)",
    "セット「{0}」を適用できませんでした":
        "Could not apply set \"{0}\"",
    "コマンドが見つかりません: {0}（一覧は win help commands）":
        "Command not found: {0} (list them with win help commands)",
    "コマンド「{0}」が失敗しました":
        "Command \"{0}\" failed",
    "  （説明なし）":
        "  (no description)",
    "  （まだありません）":
        "  (none yet)",
    "（説明なし）":
        "(no description)",
    "知らない命令・名前です: {0}（一覧は win help）":
        "Unknown command or name: {0} (list them with win help)",
    "\n拡張の命令（{0}。詳しくは win help 名前、拡張で使える関数は win help api）":
        "\nExtension commands ({0}. See win help NAME for details; functions usable in extensions: win help api)",
    "\n読み込めなかった拡張: {0}\n  {1}":
        "\nExtensions that could not be loaded: {0}\n  {1}",
    "失敗しました: {0}":
        "Failed: {0}",
    "窓が見つからず、起動コマンドも分かりません: {0}":
        "Window not found, and its launch command is unknown: {0}",
    "{0}: 引数が多すぎます: {1}（書式: {2}）":
        "{0}: too many arguments: {1} (syntax: {2})",
    "{0}: {1} は{2}で書いてください: {3}":
        "{0}: write {1} as {2}: {3}",
    "def {0}　（拡張の命令。{1}:{2}）":
        "def {0} (extension command. {1}:{2})",
    "  ほかの拡張からは from {0} import {1} で呼べる":
        "  From other extensions it can be called with from {0} import {1}",
    "（一覧は win help api、定義は {0}）":
        "(list: win help api, definitions: {0})",
    "登録したコマンド（{0}。win run 名前 で実行、中身は win help 名前）":
        "Registered commands ({0}. Run with win run NAME; contents with win help NAME)",
    "セット（{0}。win set 名前 で適用、中身は win help 名前）":
        "Sets ({0}. Apply with win set NAME; contents with win help NAME)",
    "型（{0} と組み込み。layout 名前 で使う。式を直接書いてもよい）":
        "Layouts ({0} and built-in ones. Use with layout NAME. You can also write an expression directly)",
    "「{0}」は win の組み込みの命令と同じ名前なので、使えません":
        "\"{0}\" has the same name as a built-in win command, so it cannot be used",
    "定義: {0}:{1}":
        "Defined at: {0}:{1}",
    "{0}: 知らないオプションです: {1}（書式: {2}）":
        "{0}: unknown option: {1} (syntax: {2})",
    "「{0}」は Python の標準などの部品と同じ名前なので、読み込めません（名前を変えてください）":
        "\"{0}\" has the same name as a Python standard module, so it cannot be loaded (rename it)",
    "{0}: {1} の値がありません":
        "{0}: no value for {1}",
    "{0}: {1} がありません（書式: {2}）":
        "{0}: {1} is missing (syntax: {2})",
    "{0}: --{1} がありません（書式: {2}）":
        "{0}: --{1} is missing (syntax: {2})",
    "グループの枠が分かりません（先にメンバーを置いてください）":
        "The group's frame is unknown (place its members first)",
    "前面の窓はグループに入っていません（グループの名前を指定してください）":
        "The focused window is not in a group (specify the group's name)",
    "窓がありません":
        "There are no windows",
    "その窓は、このグループのメンバーではありません":
        "That window is not a member of this group",
    "希望の大きさにならず {0}x{1} です（最小サイズなど）":
        "The size is not as requested but {0}x{1} (minimum size etc.)",
    "タイル{0}":
        "Tile {0}",
    "グループがありません: {0}（一覧は win group）":
        "No such group: {0} (list them with win group)",
    "グループはすでにあります: {0}（足すなら win group add）":
        "The group already exists: {0} (to add to it, use win group add)",
    "グループ {0} のメンバーは 1 枚だけです":
        "Group {0} has only one member",
    "文字で絞り込み　先頭に ! でアプリを探して新規起動":
        "Type to filter a leading ! searches for an app and launches it",
    "↑↓ 選択 ・ Enter 決定 ・ Tab 決定して残りを自動 ・ Ctrl+S 空ける ・ Ctrl+B 戻る ・ Esc 終了":
        "↑↓ select · Enter confirm · Tab confirm and fill the rest · Ctrl+S leave empty · Ctrl+B back · Esc quit",
    "型の名前で絞り込み（式も打てます: 1,2,2・1/1・v(1,h(1,1)) など）":
        "Filter by layout name (you can also type an expression: 1,2,2, 1/1, v(1,h(1,1)), etc.)",
    "型を省くときは、窓の指定や -n は使えません":
        "When the layout is omitted, window specs and -n cannot be used",
    "型を選ぶ":
        "Choose a layout",
    "窓を並べる":
        "Arrange windows",
    "開いている窓":
        "Open windows",
    "同じ配置を再現するコマンド:\n  win ":
        "Command to reproduce the same arrangement:\n  win ",
    "{0}　{1}枚":
        "{0}  ×{1}",
    " ・ Enter 決定してタイルごとに選ぶ ・ Tab 決定して前面の窓で自動配置 ・ Esc 閉じる":
        " · Enter choose per tile · Tab auto-arrange with the front windows · Esc close",
    "タイル {0} の窓は希望の大きさにならず {1}x{2} です（最小サイズなど）":
        "The window of tile {0} is not the requested size but {1}x{2} (minimum size etc.)",
    "その窓はもう閉じられました":
        "That window has already been closed",
    "式として使う: {0}":
        "Use as an expression: {0}",
    "（並べる先: {0}）":
        " (arranging on: {0})",
    "↑↓ 選択（ミニ地図が変わる）":
        "↑↓ select (the minimap changes)",
    "タイル {0} / {1}　{2}":
        "Tile {0} / {1} {2}",
    " ・ ←→ 並べる先のモニタ":
        " · ←→ monitor",
    "使えない文字があります":
        "Contains characters that cannot be used",
    "数か ( が必要です":
        "A number or ( is required",
    "対応しない ) があります":
        "There is an unmatched )",
    "末尾の「,」の後に要素が必要です":
        "An element is required after the trailing \",\"",
    "空です":
        "Empty",
    ") が必要です":
        ") is required",
    "余分な文字":
        "Extra characters",
    "full か v( h( が必要":
        "full, v( or h( is required",
    ") が必要":
        ") is required",
    "型の式（略記）が読めません（{0}）: {1!r}":
        "Cannot read the layout expression (short form) ({0}): {1!r}",
    "「重み:数」は使えません。重みは「重み:式」の形です":
        "\"weight:number\" cannot be used. A weight is written as \"weight:expression\"",
    "型の式が読めません（{0}）: {1!r} の {2} 文字目":
        "Cannot read the layout expression ({0}): character {2} of {1!r}",
    "「,」の前に要素がありません":
        "No element before \",\"",
    "「数:」の後には ( か数の並びが必要です":
        "( or a list of numbers is required after \"number:\"",
    "\n\n定義: `{0}:{1}`":
        "\n\nDefined at: `{0}:{1}`",
    "引用符が閉じていません: {0}":
        "Unclosed quote: {0}",
    "知らない命令です: {0}（一覧は win help）":
        "Unknown command: {0} (list them with win help)",
    "型 `{0}` = `{1}`":
        "Layout `{0}` = `{1}`",
    "当たる窓:\n":
        "Matching windows:\n",
    "↑↓ 選択 ・ ←→ 置き先を動かす（空きスペースにも） ・ Enter 決定（置き先と同じ位置・大きさで前面へ） ・ 先頭 ! でアプリ ・ Esc 閉じる":
        "↑↓ select · ←→ move the destination (free space too) · Enter place there · ! launches an app · Esc close",
    "  （最小化）":
        "  (minimized)",
    "書式: win stack [next|prev|list] [タイルの番号]（番号は 0 なら前面の窓のいるタイル）":
        "Syntax: win stack [next|prev|list] [tile number] (0 is the tile of the focused window)",
    "ここに持ってくる":
        "Bring here",
    "空き":
        "free",
    "空きスペースがありません":
        "There is no free space",
    "タイル {0} の重なり（{1} 層）":
        "Stack of tile {0} ({1} layers)",
    "グループはありません（作るには win group new 名前 [窓…]）":
        "There are no groups (to create one: win group new NAME [WINDOW...])",
    "空きスペースに持ってくる":
        "Bring to the free space",
    "タイル {0}: 層 {1}/{2}  {3}":
        "Tile {0}: layer {1}/{2}  {3}",
    "窓の指定が要ります（win group define 名前 窓の指定…）":
        "Window specs are required (win group define NAME WINDOW-SPEC...)",
    "タイルの番号か 0（前面の窓のいるタイル）を指定してください: {0}":
        "Specify a tile number or 0 (the tile of the focused window): {0}",
    "{0}枚":
        "{0} windows",
    "グループの名前を指定してください（win group {0} 名前）":
        "Specify the group's name (win group {0} NAME)",
    "グループ {0} を作りました（{1} 枚）":
        "Created group {0} ({1} windows)",
    "グループ {0} に {1} 枚を足しました":
        "Added {1} windows to group {0}",
    "グループ {0} を定義しました（{1} 枚）":
        "Defined group {0} ({1} windows)",
    "タイル {0}（{1}）に持ってくる":
        "Bring to tile {0} ({1})",
    "その向きに置き先はありません":
        "There is no destination in that direction",
    "置き先は、タイルの番号（0 は前面の窓）か free です: {0}":
        "The destination is a tile number (0 is the focused window) or free: {0}",
    "  {0} 枚":
        "  {0} windows",
    "{0} 枚をグループから外しました":
        "Removed {0} windows from the group",
    "グループ {0}":
        "Group {0}",
    "グループ {0} を消しました（窓は閉じません）":
        "Deleted group {0} (the windows are not closed)",
    "（枠 {0},{1} {2}x{3}）":
        "(frame {0},{1} {2}x{3})",
    "グループ {0}: {1}/{2}  {3}":
        "Group {0}: {1}/{2}  {3}",
    "グループ {0}（{1} 枚）":
        "Group {0} ({1} windows)",
    "重なりからグループ {0} を作りました":
        "Created group {0} from the stack",
    "知らない動作です: {0}":
        "Unknown action: {0}",
    "j/k ↑↓ 移動 ・ Enter/l 決定 ・ 1–9 直接 ・ Esc/q/h 取消":
        "j/k ↑↓ move · Enter/l confirm · 1–9 direct · Esc/q/h cancel",
    "セットを選ぶ":
        "Choose a set",
    "セットの名前で絞り込み…":
        "Filter by set name...",
    "適用先: {0}":
        "Apply to: {0}",
    " ・ Enter で適用 ・ Esc で閉じる":
        " · Enter to apply · Esc to close",
    "入力で絞り込み ・ ↑↓ で選ぶ":
        "Type to filter · ↑↓ to choose",
    " ・ ←→ でモニタを選ぶ":
        " · ←→ to choose a monitor",
    "このタイルに入れる窓":
        "Window for this tile",
    "コマンドを入力して新しく起動…":
        "Type a command to launch a new one...",
    "このタイルは空けておく":
        "Leave this tile empty",
    "前のタイルへ戻る":
        "Back to the previous tile",
    "起動するコマンド > ":
        "Command to launch > ",
    "タイル {0}/{1} > ":
        "Tile {0}/{1} > ",
    "起動するコマンドが空です":
        "The command to launch is empty",
    "（空）":
        "(empty)",
    "{0} 秒待っても新しい窓が現れませんでした: {1}":
        "No new window appeared after waiting {0} seconds: {1}",
    "タイル {0}: x={1} y={2} {3}x{4}  ← {5}":
        "Tile {0}: x={1} y={2} {3}x{4}  <- {5}",
    "  注意: タイル {0} の窓は希望の大きさにならず {1}x{2}@({3},{4}) です（最小サイズなど）":
        "  Note: the window of tile {0} is not the requested size but {1}x{2}@({3},{4}) (minimum size etc.)",
    "apps.toml の [app.{0}] new_window は、文字列のリストにしてください":
        "In apps.toml, [app.{0}] new_window must be a list of strings",
    "起動できません: {0}: {1}":
        "Cannot launch: {0}: {1}",
    "タイルは {0} 枚ですが、窓の指定が {1} 個あります":
        "There are {0} tiles but {1} window specs",
    "起動: {0}":
        "Launch: {0}",
    "{0}\n  {1} はすでに起動中です。起動中のアプリは、新しい窓を作らず既存の窓を前面に出すだけのことがあります（新しい窓を作る引数が要るか確かめてください。例: ptyxis --new-window）":
        "{0}\n  {1} is already running. A running app may only raise its existing window instead of opening a new one (check whether it needs an argument for a new window, e.g. ptyxis --new-window)",
    "タイル {0}: 窓が見つかりません: {1}":
        "Tile {0}: window not found: {1}",
    "  注意: タイル {0}: {1}":
        "  Note: tile {0}: {1}",
    "グループ {0} は、タイル {1} とタイル {2} の両方には置けません":
        "Group {0} cannot be placed in both tile {1} and tile {2}",
    "タイル {0}: 窓が見つからず、起動コマンドも分かりません: {1}":
        "Tile {0}: window not found, and its launch command is unknown: {1}",
    "タイル {0}: {1}":
        "Tile {0}: {1}",
    "選んだ窓を今の窓と同じ位置・大きさにして前面へ":
        "Give the chosen window the same position and size as the current window, and bring it to the front",
    "選んだ窓を、置き先（番号のタイル・空き）に重ねる":
        "Stack the chosen window on a destination (a numbered tile, free space)",
    "重なった窓の層を切り替える":
        "Switch the layers of stacked windows",
    "窓のグループ":
        "Window groups",
    "使用の集計":
        "Usage summary",
    "窓を別のモニタへ送る":
        "Send a window to another monitor",
    "ショートカットの設定の書き出し・反映":
        "Export and apply shortcut settings",
    "直前の操作を元に戻す":
        "Undo the last operation",
    "デスクトップを切り替える":
        "Switch desktops",
    "上下左右の窓へ":
        "To the window up/down/left/right",
    "窓の一覧から選ぶ":
        "Choose from the window list",
    "窓の一覧を表示":
        "Show the window list",
    "型の一覧を表示":
        "Show the layout list",
    "大きさを変える":
        "Resize",
    "登録したコマンド・保存した並びを実行":
        "Run a registered command or saved arrangement",
    "いまの窓の並びを名前をつけて保存":
        "Save the current window arrangement under a name",
    "保存した並び（セット）を選んで適用":
        "Choose and apply a saved arrangement (set)",
    "端末を作業ディレクトリのタブつきで開く":
        "Open a terminal with a tab per working directory",
    "Firefox を URL のタブつきで開く":
        "Open Firefox with a tab per URL",
    "設定の画面を開く":
        "Open the settings window",
    "命令の書式と説明を表示":
        "Show the syntax and description of a command",
    "ここでは prompt は使えません":
        "prompt cannot be used here",
    "拡張で使える関数の一覧":
        "List of functions usable in extensions",
    "登録したコマンドの一覧":
        "List of registered commands",
    "セットの一覧":
        "List of sets",
    "型の一覧":
        "List of layouts",
    "【複数】このクラスの窓すべて":
        "[multiple] all windows of this class",
    "読み込めなかった拡張: {0}: {1}":
        "Extensions that could not be loaded: {0}: {1}",
    "例: layout quad / focus firefox / nav right":
        "e.g. layout quad / focus firefox / nav right",
    "Tab 補完 ・ ↑↓ 候補 ・ Ctrl+↑↓ 履歴 ・ Enter 実行 ・ Esc 閉じる":
        "Tab complete · ↑↓ candidates · Ctrl+↑↓ history · Enter run · Esc close",
    "失敗しました（終了コード {0}）":
        "Failed (exit code {0})",
    "窓の操作":
        "Window operations",
    "画面の情報を取れません: {0}":
        "Cannot get the screen information: {0}",
    "モニタが見つかりません: {0}（使えるのは primary, current, {1}）":
        "Monitor not found: {0} (available: primary, current, {1})",
    "窓 {0} 枚（旧形式）":
        "{0} windows (old format)",
    "セットがありません（win save 名前 で、いまの窓の並びを保存できます）":
        "There are no sets (save the current arrangement with win save NAME)",
    "登録されたコマンドはありません（win config で作れます。窓の並びは win save でセットに）":
        "There are no registered commands (create them with win config. Save window arrangements as sets with win save)",
    "知らない種類です: {0}":
        "Unknown kind: {0}",
    "  ＋状態":
        "  + state",
    "コマンドが見つかりません: {0}（一覧は win run、セットは win set）":
        "Command not found: {0} (list them with win run; sets with win set)",
    "セットが見つかりません: {0}（一覧は win set）":
        "Set not found: {0} (list them with win set)",
    "「{0}」はセットではありません（win run {1} で実行できます）":
        "\"{0}\" is not a set (it can be run with win run {1})",
    "窓を選ぶ・移る":
        "Choose and move between windows",
    "窓を並べる・置く":
        "Arrange and place windows",
    "保存した並び（セット）":
        "Saved arrangements (sets)",
    "その他の操作":
        "Other operations",
    "変換":
        "Henkan",
    "無変換":
        "Muhenkan",
    "半角/全角":
        "Hankaku/Zenkaku",
    "ひらがな/カタカナ":
        "Hiragana/Katakana",
    "Mozc オンの端末などで届かないことがあります。確認済みで届く形は、Ctrl・Alt・Super のうち 2 つ以上と文字キーの組み合わせ（Shift なし）です。":
        "It may not reach terminals and the like with Mozc on. Forms confirmed to reach are a letter key with two or more of Ctrl, Alt and Super (without Shift).",
    "窓を選んで前面に出す、フォーカスを移す操作です。":
        "Operations to choose a window and bring it to the front, and to move the focus.",
    "窓を型で並べる、置き先に重ねる操作です。":
        "Operations to arrange windows by a layout, and to stack them onto a destination.",
    "「セット」ページで保存した窓の並びを呼びます。":
        "Calls the window arrangements saved on the \"Sets\" page.",
    "「コマンド」ページで作ったコマンドを呼びます。":
        "Calls the commands created on the \"Commands\" page.",
    "上のどれにも入らない、win の操作と拡張の命令です。":
        "win operations and extension commands that fit none of the above.",
    "窓を選んで前面に出す":
        "Choose a window and bring it to the front",
    "コマンドを入力して窓を操作":
        "Type a command to operate windows",
    "前の窓へ（左手）":
        "To the previous window (left hand)",
    "次の窓へ（左手）":
        "To the next window (left hand)",
    "直前の窓へ（交互に切り替える）":
        "To the previous window (switch back and forth)",
    "反対側のモニタの窓へ":
        "To a window on the opposite monitor",
    "重なった窓の、前の層を表示":
        "Show the previous layer of stacked windows",
    "グループの、前のメンバーを表示":
        "Show the previous member of the group",
    "窓を、別のモニタへ送る":
        "Send the window to another monitor",
    "重なった窓の、次の層を表示":
        "Show the next layer of stacked windows",
    "重なった窓の層を、一覧から選ぶ":
        "Choose a layer of stacked windows from a list",
    "グループの、次のメンバーを表示":
        "Show the next member of the group",
    "グループのメンバーを、一覧から選ぶ":
        "Choose a member of the group from a list",
    "型を選んで窓を並べる":
        "Choose a layout and arrange windows",
    "選んだ窓を今の窓と同じ形にする":
        "Give the chosen window the same shape as the current one",
    "次の窓へ（いまの並びの番号順）":
        "To the next window (in the current arrangement's numbering)",
    "前の窓へ（いまの並びの番号順）":
        "To the previous window (in the current arrangement's numbering)",
    "win の設定を開く":
        "Open the win settings",
    "# win のショートカット（GNOME のカスタムショートカット）。`win shortcuts apply` で GNOME に反映する。":
        "# win shortcuts (GNOME custom shortcuts). Apply them to GNOME with `win shortcuts apply`.",
    "# command の先頭の `win` は、反映のとき、導入した win の実体に置き換わる。":
        "# A leading `win` in command is replaced with the installed win when applying.",
    "（未割り当て）":
        "(unassigned)",
    "キーの形式が読めません":
        "Cannot read the key format",
    "拡張 ":
        "extension ",
    "{0} 番目のタイルの窓へ":
        "To the window of tile {0}",
    "ショートカットの設定がありません: {0}（作るには win shortcuts export）":
        "No shortcut settings: {0} (to create them: win shortcuts export)",
    "ショートカットの設定を読めません: {0}: {1}":
        "Cannot read the shortcut settings: {0}: {1}",
    "{0} 番目の項目に slug・binding・command が要ります: {1}":
        "Entry {0} needs slug, binding and command: {1}",
    "slug が重複しています: {0}":
        "Duplicate slug: {0}",
    "追加: {0}  {1}  {2}":
        "add: {0}  {1}  {2}",
    "自作: {0}":
        "custom: {0}",
    "更新: {0}  ":
        "update: {0}  ",
    "・":
        ", ",
    "削除: {0}":
        "remove: {0}",
    "止めています":
        "off",
    "記録中":
        "recording",
    "記録を止めました（再開は win stats on）":
        "Recording stopped (resume with win stats on)",
    "記録を再開しました":
        "Recording resumed",
    "記録を消しました":
        "Records deleted",
    "モニタが 1 枚だけです":
        "There is only one monitor",
    "\n作業領域の余白: {0}  タイル間の隙間: {1}px  設定: {2}":
        "\nWork area margins: {0}  Gap between tiles: {1}px  Settings: {2}",
    "デスクトップ {0}/{1}":
        "Desktop {0}/{1}",
    "直近 {0} 日: {1} 回（{2}）":
        "Last {0} days: {1} runs ({2})",
    "合計":
        "total",
    "キー":
        "key",
    "手入力":
        "typed",
    "日数":
        "days",
    "元に戻せる操作はありません":
        "There is nothing to undo",
    "{0:<10} {1:<24} タイル {2} 枚":
        "{0:<10} {1:<24} {2} tiles",
    "直近 {0} 日の記録はありません（{1}。記録の場所: {2}）":
        "No records in the last {0} days ({1}. Records are at: {2})",
    "{0}: {1} 件（ファイル: {2}）":
        "{0}: {1} ({2})",
    "変更の予定":
        "planned changes",
    "デスクトップ {0}{1}: {2} 枚  {3}":
        "Desktop {0}{1}: {2} windows  {3}",
    "（いま）":
        "(current)",
    "日数（整数）か on・off・reset・path を指定してください: {0}":
        "Specify a number of days (an integer), or on, off, reset or path: {0}",
    "書き出しました: {0}（{1} 件）":
        "Wrote: {0} ({1} entries)",
    "（反映しない）":
        "(not applied) ",
    "すでに {0} にあります":
        "Already on {0}",
    "{0}{1}  {2}（{3} 枚）":
        "{0}{1}  {2} ({3} windows)",
    "元に戻しました: {0}（{1} 枚":
        "Undone: {0} ({1} windows",
    "、閉じていた {0} 枚は戻せません":
        ", {0} closed windows cannot be restored",
    "デスクトップの番号（1 から）か next・prev・list を指定してください: {0}":
        "Specify a desktop number (from 1), or next, prev or list: {0}",
    "モニタが見つかりません: {0}（使えるのは next・prev・primary・{1}）":
        "Monitor not found: {0} (available: next, prev, primary, {1})",
    "# win config が書き換えます。手で編集してもかまいません（コメントは、保存し直すと消えます）。\n":
        "# Rewritten by win config. You may edit it by hand (comments are lost when it is saved again).\n",
    "基準にするモニタ（primary・current・eDP-1 など）。省くと、いまの窓があるモニタ":
        "Reference monitor (primary, current, eDP-1, etc.). If omitted, the monitor of the current window",
    "対象の窓（クラス・題名の一部、@left・@prev など）。省くと前面の窓":
        "Target window (class, part of the title, @left, @prev, etc.). If omitted, the focused window",
    "基準のモニタ（primary・current・eDP-1 など）。省くと、いまの窓があるモニタ":
        "Reference monitor (primary, current, eDP-1, etc.). If omitted, the monitor of the current window",
    "命令が空です":
        "The command is empty",
    "ショートカットの宣言的な設定（export・apply）":
        "Declarative shortcut settings (export, apply)",
    "前面の窓を、別のモニタへ送る（位置と大きさの割合を保つ）":
        "Send the focused window to another monitor (keeping the proportions of its position and size)",
    "直前の操作（layout・place・here・group・set・send）を元に戻す":
        "Undo the last operation (layout, place, here, group, set, send)",
    "使用の集計。on・off で記録を入れ・切り、reset で消す":
        "Usage summary. on and off toggle recording; reset deletes it",
    "デスクトップ（ワークスペース）の表示・切り替え。切り替えには拡張 win-helper@local が要る":
        "Show or switch desktops (workspaces). Switching needs the extension win-helper@local",
    "同じ位置に重なった窓（層）を、次・前へ切り替える":
        "Switch windows stacked at the same position (layers) to the next or previous",
    "置き先（番号のタイル・前面の窓・空きスペース）に、選んだ窓を重ねる":
        "Stack the chosen window on a destination (a numbered tile, the focused window, free space)",
    "フォーカスを次・前・上下左右の窓へ移す":
        "Move the focus to the next, previous, up, down, left or right window",
    "窓の一覧から選んで前面に出す":
        "Choose from the window list and bring it to the front",
    "窓の一覧を表示する":
        "Show the window list",
    "型の一覧を表示する":
        "Show the layout list",
    "登録したコマンドを実行する":
        "Run a registered command",
    "いまの窓の並びを、型と窓の列として保存する":
        "Save the current window arrangement as a layout and a window list",
    "端末をタブつきで開く":
        "Open a terminal with tabs",
    "保存した並び（セット）を適用する":
        "Apply a saved arrangement (set)",
    "TOML にできない値: {0!r}":
        "A value that cannot be written as TOML: {0!r}",
    "「{0}」は、コマンドの中では使えません（無限に呼び合うのを防ぐため）":
        "\"{0}\" cannot be used inside a command (to prevent calling each other endlessly)",
    "知らない命令です: {0}":
        "Unknown command: {0}",
    "動作":
        "action",
    "ファイル":
        "file",
    "shortcuts.toml のパス":
        "path of shortcuts.toml",
    "apply: ファイルにない win-* の項目を消す":
        "apply: remove win-* entries that are not in the file",
    "送り先":
        "destination",
    "next（既定）・prev・primary・モニタの接続名":
        "next (default), prev, primary, or a monitor connector name",
    "対象":
        "target",
    "list で記録の一覧。省くと直前の操作を戻す":
        "list shows the records. If omitted, undoes the last operation",
    "list（既定）・new・define・add・remove・delete・next・prev・show・select・place・from-stack":
        "list (default), new, define, add, remove, delete, next, prev, show, select, place, from-stack",
    "引数":
        "arguments",
    "名前・窓の指定・タイルの番号（動作による）。名前を省くと、前面の窓の属するグループ":
        "name, window specs, tile number (depending on the action). Without a name, the group of the focused window",
    "デスクトップ":
        "desktop",
    "next（次の層、既定）・prev（前の層）・list（小窓で選ぶ）。タイルの番号と、どちらの順でもよい":
        "next (next layer, default), prev (previous layer), list (pick in a dialog). Either order with the tile number works",
    "タイル":
        "tile",
    "タイルの番号（0 は前面の窓のいるタイル）":
        "tile number (0 is the tile of the focused window)",
    "置き先":
        "destination",
    "タイルの番号（0 は前面の窓の位置）か free（いちばん広い空きスペース）":
        "tile number (0 is the focused window's position) or free (the largest free space)",
    "置く窓（クラス・題名の一部）か !コマンド。省くと小窓で選ぶ。小窓では ←→ で置き先を動かせる":
        "window to place (class, part of the title) or !command. If omitted, pick in a dialog. In the dialog, ←→ move the destination",
    "窓の指定（クラス・題名の一部）か、5 桁以上の ID":
        "window spec (class, part of the title) or an ID of 5 or more digits",
    "方向":
        "direction",
    "next / prev（いまの並びの番号順）、left / right / up / down":
        "next / prev (in the current arrangement's numbering), left / right / up / down",
    "型の名前（win layouts）か式（例: v(1,h(1,1))。略記 1,2:1/1/1,1 も可）。省くと小窓で選ぶ":
        "layout name (win layouts) or expression (e.g. v(1,h(1,1)). The short form 1,2:1/1/1,1 also works). If omitted, pick in a dialog",
    "隙間":
        "gap",
    "タイルごとに窓の一覧を自動で出す":
        "automatically show the window list for each tile",
    "タイルごとに窓を絞り込んで選ぶ":
        "pick a window for each tile by filtering",
    "左端の位置（px）":
        "left edge position (px)",
    "上端の位置（px）":
        "top edge position (px)",
    "幅":
        "width",
    "幅（px）":
        "width (px)",
    "高さ":
        "height",
    "高さ（px）":
        "height (px)",
    "登録したコマンド・保存した並び":
        "registered commands and saved arrangements",
    "保存する名前（win set 名前 で呼べる）":
        "name to save as (call it with win set NAME)",
    "状態":
        "state",
    "firefox / terminal / all。タブの URL・作業ディレクトリも保存（選んだときだけ）":
        "firefox / terminal / all. Also saves tab URLs and working directories (only when chosen)",
    "タブごとの作業ディレクトリ":
        "working directory of each tab",
    "セットの名前。省くと、絞り込みの小窓が開く":
        "name of the set. If omitted, a filter dialog opens",
    "並び {0} 枚":
        "arrangement of {0} windows",
    "{0} が読めません: {1}":
        "Cannot read {0}: {1}",
    "{0} 行目: {1}":
        "Line {0}: {1}",
    "入力: 窓の番号 / 検索語（既存の窓）/ !コマンド（新しく起動）/ p 一覧から選ぶ / 空行（空けておく）/ < 戻る / q 終了":
        "Input: window number / search word (existing window) / !command (launch new) / p pick from a list / empty line (leave empty) / < back / q quit",
    "\n同じ配置を再現するコマンド:":
        "\nCommand to reproduce the same arrangement:",
    "型 {0}（{1}）: タイル {2} 枚":
        "Layout {0} ({1}): {2} tiles",
    "\n中断しました（ここまでの配置は残ります）":
        "\nInterrupted (the arrangement so far stays)",
    "アプリが見つかりません: {0}":
        "App not found: {0}",
    "アプリを新規起動":
        "Launch an app anew",
    "（このターミナル）":
        "(this terminal)",
    "選ぶ":
        "choose",
    "コマンドとして実行: {0}":
        "Run as a command: {0}",
    "一致する項目がありません":
        "No matching items",
    "  見つかりません: {0}":
        "  Not found: {0}",
    "  {0} 件に一致しました。番号で選んでください:":
        "  {0} matches. Choose by number:",
    "元に戻せる操作がありません":
        "There is nothing to undo",
}

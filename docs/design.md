# win の設計メモ（2026-11-21 時点）

GNOME（Wayland）の窓を、コマンドと小窓で操作する自作の道具。本体は Python のパッケージ（`lib/win/win/`）、起動役は `bin/win`。

## 1. 全体の構成

```
bin/win                 起動役（実体の位置から lib/win を探して import し、main() を呼ぶだけ）
lib/win/win/            本体（25 のモジュール）
tests/                  snapshot.py（出力の前後比較）・names.py（未定義・未使用の名前）・trace.py（窓の動きの記録）・helper_test.py（拡張の D-Bus の約束の試験）・resetter.py（置いた直後に大きさを戻す試験用の窓）・fixtures/
docs/                   design.md（この文書）・interactive-design.md（対話型の小窓）
extension/              GNOME Shell 拡張 win-helper@local（デスクトップの取得・切り替えの D-Bus）と install.sh
~/.config/win/          利用者の設定: commands.toml・sets.toml・layouts.toml（任意）・ext/（拡張の Python）
```

`~/.local/bin/win` は `bin/win` へのリンク。子プロセス（小窓）も `WIN_BIN`（この起動役）で起こす。

### モジュール（依存は下から上。下のモジュールは上を読み込まない）

| 層 | モジュール | 役割 |
|---|---|---|
| 基礎 | `common` | 定数・標準ライブラリの読み込み・`WinError` |
|  | `screen` | `Screen`（基準のモニタ）・作業領域・設定（layouts.toml）の読み込み・D-Bus で画面情報 |
|  | `layouts` | 型の式（full / v(...) / h(...)・略記）の解析とタイルの計算 |
|  | `shortcuts` | GNOME のカスタムショートカット（dconf）の読み書き・標準の操作の一覧 |
|  | `dbus` | Window Calls の D-Bus・窓の一覧・窓の指定（`@left`・`@slot:N` など） |
|  | `desktop` | デスクトップ（ワークスペース）の取得・切り替え（拡張 win-helper@local の D-Bus を呼ぶ） |
| 保存・配置 | `store` | commands.toml・sets.toml の読み書き・コマンド書式の検査・アプリの起動コマンド |
|  | `pickwin` | 窓の一覧の行の表示名・小窓の位置合わせ |
|  | `placement` | 型による配置（`win layout`） |
|  | `simple` / `textui` / `nav` | list・focus・move・size・state・close／端末の対話の部品／上下左右のフォーカス移動 |
| 状態・セット | `sets` | セット（保存した窓の並び）・プレビューの材料・モニタの一覧 |
|  | `prompt` | コマンド入力の小窓（`win prompt`）と補完 |
|  | `appstate` | いまの並びの逆算（タイルの順）・Firefox/端末の状態・`win save` |
|  | `groups` | 窓のグループ（名前つき・保存つき）の保存と操作 |
| 対話型の小窓 | `tilepick` | 汎用の小窓の描画側（`_tilepick`、GTK）と、絞り込み・アプリ一覧・端末版の対話 |
|  | `dialog` | `Dialog`（親側の部品）と、1 回で選ぶ関数（`choose` など） |
|  | `pickers` | 窓・セットを選ぶ小窓（`win pick`・`win set`・拡張の `pick()`） |
|  | `layoutflow` | `win layout` の対話（型の選択からタイルごとの選択まで） |
| 拡張・入口 | `ext` | 拡張（`~/.config/win/ext/*.py`）と `winapi` |
|  | `lsp` / `configwin` | エディタ向けの補完（`win lsp`）／設定の窓（`win config`） |
|  | `overlay` / `cli` | 置き先に窓を重ねる（`win place`・`win here`）／コマンド行の入口（`main`・`build_parser`） |

- 逆向きの依存（下のモジュールが上のモジュールの関数を使う箇所）は、使う関数の中での遅延インポートにしてある（`# 逆向きの依存` の印つき、約 20 か所）。モジュール直下（定数・クラス本体・デコレータ）の参照は、必ず下向き。
- `win.名前` で、すべてのモジュールの名前を引ける（`__init__` が集める。試験・古い呼び出し方のため）。

## 2. アクション（名前のついた操作）

利用者から見ると、実装の入れ物が違っても同じ「操作」。

| 種類 | 置き場所 | 例 |
|---|---|---|
| 組み込み | `cli.build_parser`（各モジュールの `cmd_*`） | `place`・`layout`・`set`・`pick`・`nav` |
| 拡張 | `~/.config/win/ext/*.py` の `@command` | `swap`・`merge`・`split` |
| コマンド | `commands.toml` | 登録した win の命令・シェルコマンド |
| セット | `sets.toml` | 保存した窓の並び |

- 設定の窓のショートカット画面は、**種類ではなく目的別**（窓を選ぶ・移る／窓を並べる・置く／保存した並び／コマンド／その他）に並べ、種類は行の左の印で示す。拡張は `@command(group="…")` で入るグループを選べる。
- **組み込みにする**: 小窓・画面・並びの逆算など win の内部部品に直接依存するもの、ほかの操作の土台（`place`・`layout`・`set`・`pick`・`nav`・`focus`）。
- **拡張にする**: `winapi` の公開関数だけで書ける「組み合わせ」（`swap`・`merge`・`split`）。
- **別名にする**: 既存の操作の引数を決めただけのものは、独立した実装を持たない（`here` は `place 0`）。
- 組み込みと同じ名前の拡張は、読み込み時にエラー（組み込みが優先）。

## 3. 基準のモニタ（Screen）

不変の `Screen`（論理領域・主モニタか・接続名）。作業領域は `screen.work_area(cfg)`。
- `find_screen(choice)` は状態を変えない。既定の `Screen` はこの実行に 1 つ（コマンド行の `-m`。`default_screen()` / `use_screen()`、起動時に `resolve_monitor` が決める）。
- 小窓の中でモニタを切り替えるときは、既定を書き換えず、新しい `Screen` を作って関数に渡す（`place_move` は新しい `Screen` を返す。`win layout` の型の選択は `args.monitor` で持ち回る）。
- `current_tiles`・`slot_map`・`free_rects`・`place_targets`・`monitors_for_preview` は、`screen` を省くと既定を使う。

## 4. 置き先（place）

`win place [N|free] [窓] [--min]`。置き先は、N（1 以上）＝いまの並びの N 番目のタイル、0＝前面の窓のタイル（並びの外ならその窓の場所）、free＝いちばん広い空きスペース。
- 空きスペース: 基準モニタの作業領域から、最小化されていない窓の枠を引いた残りの極大長方形（広さ 5% 以上・各辺 10% 以上）を、広い順に最大 6 つ（`free_rects`）。
- 小窓では、左右矢印で置き先を動かせる。端を越えると隣のモニタへ移る。

## 4.1 重なった窓（stack）

同じ位置に重なった窓を、タイルごとの「層」として扱う（`place` は置き先の窓を残して上に重ねるので、重なりは自然にできる）。
- **認識**: `appstate.tile_stacks`。いまの並び（`current_tiles`）の各タイルについて、枠の 4 辺が `STACK_TOL`（8px）以内の、最小化されていない窓を層にする。手前の層は、重なり順がいちばん上のもの。すべてが他の窓に覆われて見えない重なりは、並びに現れないので含めない。
- **巡回**: 層は ID の昇順で一巡する（Activate だけだと、上の 2 枚を行き来するだけになるため、順を固定する）。保存するものはない。
- **下の層の扱い**: 覆うだけ（最小化しない）。タイルの逆算・窓の一覧は、すでに覆われた窓を無視するので、そのまま動く。
- `win stack [N] [next|prev|list]`（N=0 は前面の窓のいるタイル）。`list` は `choose` の小窓（地図に各タイルの層の数、手前の層が先頭）。ショートカットの標準の割り当て先は `win-stack-next`・`win-stack-list`。拡張からは `stack(n)`（層の一覧）・`cycle(n, d)`（d 層ずらして前面へ）。

## 4.1.1 窓のグループ（group）

名前つき・保存つきの窓の集まり（`groups.py`、保存先 `~/.local/state/win/groups.json`。`WIN_GROUPS` で差し替え可）。重なり（4.1）が「同じ位置にたまたまある窓」なのに対し、グループは「明示した、順序つきのメンバー」。
- **枠を共有する**: グループは 1 つの枠（位置・大きさ）を持つ。次のメンバーを、その枠へ置いて（別のデスクトップ・最小化・最大化は、今のデスクトップへ戻し・解いて）から前面に出す。メンバーがもともと重なっている必要はない。
- **枠は手前のメンバーに追従する**: 手前のメンバーを動かしたら、次の切り替えはその位置へ出る。
- **メンバー**: 窓の ID と順序（巡回の順）。1 つの窓は高々 1 つのグループに入る（別のグループへ足すと移る）。閉じた窓は読み込み時に取り除き、空になったグループは消す。
- `win group [list|new 名前 [窓…]|add 名前 [窓…]|remove [窓…]|delete 名前|next|prev|show|select [名前]|place 名前 [タイル]|from-stack [タイル] [名前]]`。名前を省くと、前面の窓の属するグループ（ショートカットに向く）。`show` は全メンバーを枠へ置く（置く処理は窓ごとに並行）。`select` は小窓（手前のメンバーが先頭）。`from-stack` は重なり（4.1）をグループにする。標準のショートカット項目は `win-group-next`・`win-group-select`。
- 拡張から: `group(名前, 窓…)`・`groups()`・`group_of(窓)` と `Group`（`members`・`active`・`rect`・`add`・`remove`・`delete`・`next`・`show`・`place`）。
- **注意（環境の仕様）**: この環境は `workspaces-only-on-primary`（ワークスペースは主モニタにだけ適用）が true なので、副モニタ（eDP-1）にある窓は、すべてのデスクトップに出ていて、`MoveToWorkspace` が効かない。デスクトップをまたぐ動き（`Window.desktop`・グループの `show`）は、主モニタの窓が対象。

## 4.2 デスクトップ（ワークスペース）

- **窓のデスクトップ**: `List` の `workspace`（0 から）と、`MoveToWorkspace`（Window Calls）で足りる。`Window.desktop`（1 から。代入すると、その窓を移す）は拡張なしで動く。`win desktop list` も、窓の一覧から数えるので、拡張なしで動く。
- **切り替え**: Window Calls にも GNOME Shell の `Eval`（無効）にもないので、自作の Shell 拡張 `win-helper@local` が D-Bus（`org.local.WinHelper`: `Workspaces`・`Switch`・`SwitchRelative`）で公開する。`raise-claude@local` と同じ作り。win 側は `desktop.py`（`desktops()`・`switch_desktop(n)`・`switch_relative(d)`）、コマンドは `win desktop [N|next|prev|list]`、拡張からは `desktops()`・`switch_desktop(n, relative)`。拡張がなければ、導入の案内つきの `WinError`。
- **導入**: `extension/install.sh`（~/.local/share/gnome-shell/extensions/ へ複写）。Wayland では、読み込みに再ログインが要る。`enabled-extensions` には追記済み（取り消し: `gnome-extensions disable win-helper@local`）。
- **確認の範囲**:
  - D-Bus の約束は、`extension.js` の `import` の 1 行を差し替えた写しを gjs で動かし（Shell の代わりに模擬の `global`）、win 側から呼んで確認した（`tests/helper_test.py`。本物の拡張と重ならないよう、模擬は `org.local.WinHelperTest` の名前で動き、win 側は `WIN_HELPER_NAME` でそこへ向ける）。
  - **再ログイン後に、実機で確認した**（2026-11-21）: 拡張が読み込まれ（`gnome-extensions info` が ACTIVE）、`win desktop`（表示）・`2`・`1`・`next`・`prev`・範囲外・不正な指定が、期待どおりに動いた。
- **List の `workspace` の癖**: 副モニタの窓（全デスクトップに出ている）は、`workspace` が「いまのデスクトップ」に追従する。`win desktop list` で、副モニタの窓は、いまいるデスクトップに数えられる。
- 方針: 動的ワークスペースでは、末尾に空のデスクトップが 1 つあるので、`count` はそれを含む。切り替えは端で一巡しない。

## 5. 対話型の小窓

すべての小窓は、**描画だけの汎用の子プロセス**（`_tilepick`）と、**状態を持つ親の `Dialog`** の組。詳細は `docs/interactive-design.md`。

| 小窓 | 親の関数 | モジュール |
|---|---|---|
| `win place`・`win here` | `gui_place` | `overlay` |
| `win set` | `pick_set` | `pickers` |
| `win pick`・端末版の窓一覧 | `pick_rows` | `pickers` |
| 拡張の `pick()`・`@pick` の窓の指定 | `pick_window_map` | `pickers` |
| `win layout` | `gui_layout_flow`・`gui_interactive` | `layoutflow` |
| 拡張から | `Dialog`・`choose`・`confirm`・`ask`・`pick_tile`・`pick_window` | `dialog`（`winapi`） |

例外: コマンド入力（`win prompt` の `_prompt`・`_nvprompt`）・設定の窓（`win config`、同じプロセス）・番号の目印の窓（`_tile`）は、別の作り。

## 6. 試験

- `python3 tests/snapshot.py > before.txt`（変更前）→ `after.txt`（変更後）→ `diff`。ヘルプ・型の一覧・LSP の応答・純粋関数の結果を記録する（窓も設定も動かさない。設定は `tests/fixtures` の写し）。
- `python3 tests/names.py lib/win/win/*.py`: 未定義の名前（NameError になりうる参照）と、使っていないインポートを探す。
- 小窓は実機で確かめる。キーを送る前に、前面が小窓か毎回確かめる（外れると、キーが別の窓に入る）。

## 6.1 窓の位置の扱い（Window Calls の癖）

- **枠の基準で動かす**: 位置・大きさの確認は `GetFrameRect`（枠）。動かすのは `MoveResize`（枠の基準）か `Move` を使う。`Resize` は使わない — 窓の影の余白（CSD の窓で 25px ほど）ぶん、同じ大きさでも枠を左上へずらす（`win size` はこれで位置がずれていた。いまは `MoveResize` で位置を保つ）。
- **起動した窓はすぐ動かす**: 新しい窓は、アプリが決めた位置（別のモニタのことも）にまず出る。見え続ける時間を短くするため、`wait_new_window` は現れたらすぐ返し（待ちは 0.08 秒だけ）、`place_settled` が確かめ直す。`win place` で小窓から `!` で起動した窓は、小窓を閉じる前に置く。
- Firefox（起動中のセッションに `--new-window`）で確認済み: 既定位置に見えるのは 70〜90ms、その後 1 回で目的地へ移り、戻しはない。最小幅（639px）より狭いタイルを求めても、位置は揺れず最小サイズ（639x960）で安定し、注意文が出る。
- 新規プロファイルの Firefox（`-no-remote -profile` で別インスタンス。約 1 秒で現れる）も同じ: 既定位置に見えるのは約 0.1 秒、その後 1 回で目的地へ移り、40 秒間戻しはない。前回の大きさを復元して、置いた直後に自分で大きさを戻すことがある（1 回だけ観測。タイミング依存）。
- アプリが置いた直後に位置や大きさを戻す場合は、`place_settled` が待つあいだ 0.05 秒ごとに見て、いったん合ったのに動かされたらすぐ置き直す。誤った大きさが見える時間は約 140ms から約 30ms（`tests/resetter.py`: 開いて 0.25 秒後に自分で 500x400 へ戻す試験用の窓、で再現して実測）。
- 窓の動きは `tests/trace.py` で数字にできる（約 20ms ごとの位置・重なり順・フォーカスの変化。既存の窓の位置は `--all` のときだけ調べる — 問い合わせの負荷で測定が遅れるため）。表示上の不具合（点滅・別のモニタをまたぐ・行き来）を疑うときに使う。

## 6.2 速さ・軽さ（実測、2026-11-20）

- **普通のコマンド**（`win list` など）は約 80ms。Python 8ms、`gi` の読み込み約 50ms（うち `asyncio` が約 23ms）、こちらのコード約 11〜20ms。下限は PyGObject 自体で、こちらで削れる所はほぼない。`asyncio` を読ませずに `gi` を使う案は、`gi` が `asyncio.InvalidStateError` を要求するため動かない。`GioUnix` の読み込みは 1ms 程度で、削る意味がない。
- **小窓**（子プロセス）は、起動から窓が現れるまで約 230ms（`gi` 約 38ms、Gtk・Adw 約 25ms、残りは GTK の起動と窓の生成）、メモリは約 140MB。こちらのコードの読み込みは 11ms ほど。
- 試して効果がなかったもの: 小窓の子プロセスを、材料（並びの逆算・窓の一覧）を集める前に起こして並行させる案。元の流れでも、重い窓の一覧の取得は子の起動後に行っていたので重なっており、残る直列の部分は 25ms ほどで、出現時間（0.32〜0.34 秒）は変わらなかった。元に戻した。
- 効果があったもの: `win layout` で既存の窓を並べるときの、置いたあとの定着待ち（窓ごとに 0.3 秒以上）を、窓ごとに並行にした（起動だけは 1 つずつ）。2 枚で 1.27 秒 → 0.96 秒、4 枚で 1.91 秒 → 0.95 秒。位置は 8 回の繰り返しで毎回一致した。
- `win set`: 現在の形式（`type = "win"`、`layout ...` の行）は、上の `layout` の並行化がそのまま効く。旧形式（`type = "arrange"`、`run_arrangement`）も、置く処理を窓ごとに並行にし、前面化だけ保存順（下 → 上）に後でまとめて行うようにした（重なり順を再現するため）。4 枚で 1.43 秒 → 0.44 秒（3 回とも同じ）。起動・最大化・見つからない窓の通知も確認した。

## 7. 既知の課題

- 遅延インポート（約 20 か所）を減らすには、使う部品（窓の可視判定・タイル逆算・小窓の起動）を下の層へ移す。
- 実機で確かめていないこと:
  - `Dialog` の `keep_selection`。
  - 端末版の対話（`layout -i -t`）に `--preview`（番号の目印の窓）を付けた場合。
  - 並行化（`layout`・旧形式の `set`）で、窓が数十枚ある場合と、別ワークスペースの窓を含む場合。
  - Firefox の保存した大きさの復元は、タイミング依存で、毎回は再現しない（`tests/resetter.py` の代役の窓で確認した）。
  - 最大化した窓は、置き先のモニタへは移らない（最大化はその窓がいるモニタのまま。従来からの動き）。

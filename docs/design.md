# win の設計メモ

## 「アクション」という考え方

win で呼べる名前つきの操作（アクション）は、実装の入れ物が違っても、利用者には同じものとして見える。

| 種類 | 置き場所 | 例 |
|---|---|---|
| 組み込み | `lib/win/win.py` の `add_parser` | `place`・`layout`・`set`・`pick`・`nav` |
| 拡張 | `~/.config/win/ext/*.py` の `@command` | `swap`・`merge`・`split` |
| コマンド | `~/.config/win/commands.toml` | 登録した win の命令やシェルコマンド |
| セット | `~/.config/win/sets.toml` | 保存した窓の並び |

設定の窓のショートカット画面は、**種類ではなく目的別**に並べる（窓を選ぶ・移る／窓を並べる・置く／保存した並び／コマンド／その他）。
種類は、行の左の小さな印（組み込み・拡張・コマンド・セット）で示す。
拡張は `@command(group="窓を並べる・置く")` のように、入るグループを選べる（省くと「その他の操作」）。

## 組み込みか拡張かの基準

- **拡張にする**: `winapi` の公開関数（`at`・`slots`・`pick`・`layout` など）だけで書ける「組み合わせ」。例: `swap`・`merge`・`split`。
- **組み込みにする**: win の内部部品（小窓・画面・並びの逆算）に直接依存するもの、ほかの操作の土台になるもの。例: `place`・`layout`・`set`・`pick`・`nav`・`focus`。
- **別名にする**: 既存の操作の引数を決めただけのものは、独立した実装を持たない。`here` は `place 0` の別名。
- 組み込みと同じ名前の拡張は、読み込み時にエラーになる（組み込みが優先）。

## 置き先（place）

`win place [N|free] [窓] [--min]`。置き先は次のいずれか。
- N（1 以上）: いまの並びの N 番目のタイル。
- 0: 前面の窓のタイル（並びの外にあれば、その窓の場所）。
- free: いちばん広い空きスペース。

空きスペースは、基準モニタの作業領域から、最小化されていない窓の枠を引いた残りの極大長方形（広さ 5% 以上・各辺 10% 以上）を、広い順に最大 6 つ。
小窓では、左右矢印で置き先を動かせる。端を越えると隣のモニタへ移る（基準のモニタを切り替えて、並びを逆算し直す）。

## 基準のモニタ（Screen）

基準のモニタは不変の `Screen`（論理領域・主モニタか・接続名）で表す。作業領域は `screen.work_area(cfg)`。
- 探す: `find_screen(choice)`（状態を変えない）。
- 既定: コマンド行の `-m` に当たる、この実行の既定の `Screen` が 1 つ（`default_screen()` / `use_screen()`）。`resolve_monitor` は起動時に 1 回これを決める。
- 小窓の中でモニタを切り替えるときは、既定を書き換えず、新しい `Screen` を作って関数に渡す（`place_move` は新しい `Screen` を返す。`gui_layout_flow` は `args.monitor` で持ち回る）。
- `current_tiles`・`slot_map`・`free_rects`・`place_targets`・`monitors_for_preview` は、`screen` を省くと既定を使う。

## パッケージの構成（lib/win/win/）

`~/.local/bin/win` は `bin/win`（起動役）へのリンクで、起動役は自分の実体の位置から `lib/win/` を見つけて `import win` する。
本体は 20 のモジュール。依存は下から上へ向かい、下のモジュールは上のモジュールを読み込まない。

| 層（下 → 上） | モジュール |
|---|---|
| 基礎 | `common`（定数・標準ライブラリ）、`screen`（Screen・作業領域・設定の読み込み）、`layouts`（型の式・タイルの計算）、`shortcuts`（GNOME のカスタムショートカット）、`dbus`（Window Calls・窓の指定） |
| 保存・配置 | `store`（commands.toml・sets.toml）、`pickwin`（窓の一覧の小窓）、`placement`（win layout）、`simple`（list・focus・move・size・state・close）、`textui`、`nav` |
| 状態・セット | `sets`、`prompt`（コマンド入力の小窓・補完）、`appstate`（いまの並びの逆算・Firefox/端末の状態） |
| 小窓・拡張 | `tilepick`（絞り込みの小窓）、`ext`（拡張と winapi）、`lsp` |
| 画面・入口 | `configwin`（設定の窓）、`overlay`（place・here）、`cli`（main・build_parser） |

- 逆向きの依存（下のモジュールが上のモジュールの関数を使う 18 か所）は、使う関数の中での遅延インポートにしてある（`# 逆向きの依存` の印つき）。モジュール直下（定数・クラス本体・デコレータ）の参照は、必ず下向き。
- 遅延インポートの一覧: `find_screen`→`dbus`、`at_window(s)`→`nav`・`appstate`・`tilepick`、`cmd_layout`→`tilepick`、`run_entry`・`run_inline`→`cli`、`run_arrangement`→`overlay`、`builtin_commands`→`cli` など。減らすには、これらの関数が使う部品（窓の可視判定・タイル逆算・小窓の起動）を、下の層へ移すか、関数を引数で受け取る形にする。
- `win.名前` で、すべてのモジュールの名前を引ける（`__init__` が集める。試験・古い呼び出し方のため）。

## 試験

- `python3 tests/snapshot.py > before.txt`（変更前）→ `after.txt`（変更後）→ `diff`。ヘルプ・型の一覧・LSP の応答・純粋関数の結果を記録する（窓も設定も動かさない。設定は `tests/fixtures` の写し）。
- `python3 tests/names.py lib/win/win/*.py`: 未定義の名前（NameError になりうる参照）を探す。
- 小窓は実機で確かめる（キーを送る前に、前面が小窓か毎回確かめる）。

## 既知の課題（今後）

- 対話型の小窓の作りが、用途ごとに別々（`tilepick`・`setpick`・`pick`・`prompt`・`config`）。拡張から使える共通の部品にしたい（検討中）。

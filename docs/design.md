# win の設計メモ（2026-11-20 時点）

GNOME（Wayland）の窓を、コマンドと小窓で操作する自作の道具。本体は Python のパッケージ（`lib/win/win/`）、起動役は `bin/win`。

## 1. 全体の構成

```
bin/win                 起動役（実体の位置から lib/win を探して import し、main() を呼ぶだけ）
lib/win/win/            本体（23 のモジュール）
tests/                  snapshot.py（出力の前後比較）・names.py（未定義・未使用の名前）・fixtures/
docs/                   design.md（この文書）・interactive-design.md（対話型の小窓）
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
| 保存・配置 | `store` | commands.toml・sets.toml の読み書き・コマンド書式の検査・アプリの起動コマンド |
|  | `pickwin` | 窓の一覧の行の表示名・小窓の位置合わせ |
|  | `placement` | 型による配置（`win layout`） |
|  | `simple` / `textui` / `nav` | list・focus・move・size・state・close／端末の対話の部品／上下左右のフォーカス移動 |
| 状態・セット | `sets` | セット（保存した窓の並び）・プレビューの材料・モニタの一覧 |
|  | `prompt` | コマンド入力の小窓（`win prompt`）と補完 |
|  | `appstate` | いまの並びの逆算（タイルの順）・Firefox/端末の状態・`win save` |
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

## 7. 既知の課題

- 端末版の対話（`layout -i -t`）が使う `line_from_picker` は、`pick_rows` に切り替えたが、実機では動かしていない。
- 遅延インポート（約 20 か所）を減らすには、使う部品（窓の可視判定・タイル逆算・小窓の起動）を下の層へ移す。
- `keep_selection`（`Dialog`）は、実機で確かめていない。

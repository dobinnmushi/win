# 対話型の小窓の設計

## 1. いまの呼び出し（2026-11-20 時点）

| 小窓 | 子プロセス | 親の関数 | 親子のやり取り | 呼ぶ所 |
|---|---|---|---|---|
| 絞り込みの小窓 | `_tilepick`（`tilepick.run_tilepick`） | `gui_layout_flow`（型を選ぶ）・`gui_interactive`（タイルごと）・`pick_interactive`（窓 1 枚）・`gui_place`（here/place） | 1 行 1 JSON の双方向。親→子: `layouts`・`tile`・`busy`・`quit`。子→親: `layout`・`win`・`app`・`cmd`・`skip`・`back`・`target`・`none`・`cancel` | `win layout`・`win here`・`win place`・拡張の `pick()` |
| セットの小窓 | `_setpick`（`sets.run_setpick`） | `pick_set` | 起動時に JSON を 1 回渡し、結果を 1 行返す | `win set` |
| 窓の一覧 | `_pick`（`pickwin.run_pick`） | `pick_window` | 起動時に渡して、結果を返す | `win pick` |
| コマンド入力 | `_prompt`・`_nvprompt` | `cmd_prompt` | 結果の行 | `win prompt` |
| 番号の目印 | `_tile`（`textui.run_tile`） | `start_placeholders` | なし（親が閉じる） | `layout -i` の予告表示 |
| 設定の窓 | （同じプロセス） | `run_config` | — | `win config` |

## 2. 分かったこと

- 「行の一覧＋絞り込み＋ミニ地図」という画面は、実質 1 つの部品（`_tilepick`）なのに、メッセージが「型を選ぶ」と「タイルごと」の 2 つの段階に固定されている。用途が増えるたびに、メッセージの項目を足してきた（`title`・`hint`・`placeholder`・`labels`・`movable`・`mon`・`free`・`apps`・`notice`）。
- セットの小窓と窓の一覧は、別の作りで、同じ見た目の部品を二重に持っている。
- 拡張が使える対話型は `pick(title, slot, launch, exclude, rect)` の 1 つだけ。次のことができない。
  - 窓以外の選択肢（型・セット・モニタ・任意の一覧）を選ぶ。
  - 地図の上でタイルや空きを選ぶ。
  - キー（←→ など）で状態を動かす（`place` の置き先の移動は、組み込みだけが持っている）。
  - 確認・文字入力。
  - どのキー（Enter か Tab か）で決めたかを知る。

## 3. 拡張から調整できるようにしたいこと

- 見た目: 題名・案内文・入力欄の説明・通知（エラー）・行（名前・補足・アイコン・印）・ミニ地図（タイル・ラベル・強調・点線・モニタの枠）。
- 入力: 絞り込みの有無、先頭 `!` でのアプリ起動の可否、単一か複数の選択、初めに選ばれている行。
- キー: 決定の種類（Enter か Tab か）、追加で受け取るキー（←→・Ctrl+S など）、既定のキーの無効化。
- 流れ: 1 回で終わる選択か、状態を更新し続けるやり取りか。待ち表示（busy）、エラーを出して開いたままにする。

## 4. 案: 2 段の部品

小窓を、**描画だけを受け持つ汎用の部品**にして、**状態の管理は親（拡張の Python）の側**に置く。

### 4.1 簡便な関数（1 回で終わる）

```python
from winapi import ui

w = ui.pick_window("入れ替える窓", launch=False, exclude=[a])        # いまの pick の一般化（pick は別名で残す）
i = ui.pick_tile("置き先", tiles=ui.slots_map(), current=2)           # 地図の上でタイル・空きを選ぶ（矢印で動かす）
x = ui.choose("型を選ぶ", [ui.Item("lr", sub="v(1,1)")], preview=lambda it: ui.Map(...))
ok = ui.confirm("実行しますか")
s = ui.ask("名前", placeholder="…")
```

### 4.2 やり取りを回す部品（状態が変わり続ける）

```python
with ui.dialog(title="置き先を選ぶ", hint="←→ で置き先を動かす") as d:
    d.rows(items)                    # 行を差し替える
    d.map(ui.Map(rects, labels, current=i, free=flags, monitor=m))   # 地図を差し替える
    d.notice("その向きに置き先はありません")
    d.keys("Left", "Right")          # 受け取りたいキー
    for ev in d.events():            # ev: Select(item, via="enter"|"tab")・Key("Left")・Text(s)・Cancel
        ...
```

`win place` を、この部品の上で書き直す。組み込みの `place` が、拡張と同じ部品の最初の利用者になる（拡張に見せない特別扱いをなくす）。

### 4.3 描画の部品（子プロセス）

- 親→子は `show`（題名・案内・入力欄の説明・行・地図・通知・受け取るキー・絞り込み・アプリ起動を、1 つの宣言で渡す）と `busy`・`quit` だけにする。
- 子→親は `select`・`key`・`text`・`cancel`。
- `_setpick`・`_pick` は、行＋プレビューの宣言に置き換えられる。入力欄の `_prompt` は別の部品のまま残す。

## 5. 進め方（案）

1. 描画の部品のメッセージを `show` に統一する（内部。見た目は変えない）。
2. 簡便な関数（4.1）を `winapi` に足す（`pick` は残す）。
3. やり取りの部品（4.2）を足す。
4. `place`・`here`、続いて `set`・`pick` を、その上に乗せ換える。
5. `winapi.pyi`・拡張のひな形・`win help api`・LSP の補完を更新する。

## 6. 決めたいこと

- 4.1 と 4.2 の両方を足すか、4.2 だけにして 4.1 はその上の薄い関数として作るか。
- 乗せ換えの範囲（`place` だけか、`set`・`pick` も）。
- イベントの受け取りを、拡張の関数の中で同期的に回す（上の例）か、キーごとにコールバックを登録するか。

## 7. 実装の状況（2026-11-20）

すべての小窓（`place`・`here`・`set`・`pick`・`layout`・拡張の `pick()`）を、`Dialog` の上に乗せ換えた。決めたこと: 簡便な関数と `Dialog` の両方／イベントは関数の中で同期的に回す。

**描画の部品（`_tilepick`）のプロトコル**
- 親→子: `show`（全体を描き直して入力を待つ）・`patch`（渡した項目だけ更新。返信を待たない通知への応答）・`busy`・`quit`。旧い `layouts`・`tile` のメッセージと、専用の段階・モニタ切り替え・タイル移動のコードは削除した。
- 子→親: 返信を待つもの — `select`（`via` が enter か tab）・`key`・`text`・`app`/`cmd`（`!` の起動）・`none`（行がないまま Tab）・`cancel`。待たない通知 — `highlight`（選択が動いた）・`edit`（入力欄の文字が変わった）。

**Dialog の設定**: `filter`・`entry`・`ask`・`show_list`・`launch`・`highlight`・`keys`・`keep_selection`・`empty`・`chip`・`window_title`・`vim`・`numbers`・`watch`。`options()` であとから変えられる（`win layout` は、型の選択からタイルごとの選択へ、同じ小窓で設定を切り替える）。
- `watch`: 入力が変わるたびに `edit` の出来事が来る。親が `rows()` を渡し直すと、絞り込みを親が行える（型の式を打つ）。
- `vim`・`numbers`: 入力欄のない一覧のキー（j/k・g/G・l・h/q・1〜9）と行番号（`win pick`）。
- 行がないまま Tab → `item` が None の `select`（via="tab"）。`!` で起動したとき → `launched`（window と、その起動コマンド `text`）。

**確認（実機）**: `place`・`here`（左右・モニタ越え・`!calculator`）、`set`（地図・左右・適用）、`pick --id`（j/k・数字・q）、`layout`（型の選択・式 `1,2`・左右・`lr` → Ctrl+S → `!calculator`・再現コマンド・Tab の 2 経路）、`layout lr -i`（Ctrl+S・Ctrl+B）、拡張の `choose`・`confirm`・`ask`・`pick_tile`・`Dialog`・`pick()`。

**未確認**: `keep_selection`、端末版の対話で `--preview`（番号の目印の窓）を付けた場合。端末版の対話の一覧（`line_from_picker`）は、疑似端末で `layout lr -i -t` を動かして確認した（`p`・`--pick`・窓の番号の選択・空ける・戻る・取消）。`layout` の Tab（型の選択画面での自動配置と、タイルごとの選択での「決めて残りを自動」）は、実機で確認した（試験前に全窓の位置を記録し、枠の基準の `place_settled` で復元）。

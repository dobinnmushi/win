from winapi import WinError, at, command, pick, resolve, tiles


@command(group="窓を並べる・置く")
def split(n: int, expr: str, *windows: str):
    """n 番目のタイルを、型 expr で分ける（元の窓は 1 つめに残し、2 つめ以降は windows か、その場で選ぶ）
    n: 分けるタイルの番号（0 は前面の窓）
    expr: 分け方（例 1/1 は上下、1,1 は左右、1,2 は 1:2 の左右）
    windows: 2 つめ以降に置く窓（layout と同じ書き方。- で空ける、!コマンド で起動。省くとその場で選び、Esc で空ける）
    """
    t = at(f"@slot:{n}")
    parts = tiles(expr, t.rect)
    if len(parts) < 2:
        raise WinError(f"「{expr}」では分かれません（1/1 や 1,1 のように 2 つ以上に分けてください）")
    if len(windows) > len(parts) - 1:
        raise WinError(f"分けた後の 2 つめ以降は {len(parts) - 1} 個ですが、窓の指定が {len(windows)} 個あります")
    t.rect = parts[0]
    for k, r in enumerate(parts[1:], 2):
        if k - 2 < len(windows):
            w = resolve(windows[k - 2])
        else:
            try:
                w = pick(f"分けた {k} つめに置く窓（Esc で空ける）", rect=r)
            except WinError:
                continue
        if w is None:
            continue
        w.rect = r
        w.focus()

from winapi import Window, at, command, pick, slot_of


def exchange(a: Window, b: Window):
    a.rect, b.rect = b.rect, a.rect


def window_of(x: int | Window) -> Window:
    """番号ならいまの並びのその番目のタイルの窓、窓ならそのまま。"""
    return at(f"@slot:{x}") if isinstance(x, int) else x


@command(group="窓を並べる・置く")
def swap(a: int | Window | None = None, b: int | Window | None = None):
    """2 つの窓の位置と大きさを入れ替える（番号はいまの並びのタイル、0 は前面の窓。省いた分はその場で順に選ぶ）
    a: 1 つめ（タイルの番号か窓。0 は前面の窓）
    b: 2 つめ（タイルの番号か窓。0 は前面の窓）
    """
    first = window_of(a) if a is not None else pick("入れ替える 1 つめの窓", launch=False)
    second = window_of(b) if b is not None else pick(
        f"「{first.title[:30]}」と入れ替える窓", slot=slot_of(first), launch=False, exclude=[first])
    if first != second:
        exchange(first, second)

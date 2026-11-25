import builtins

from winapi import Window, WinError, at, command, slots

TOL = 8  # 窓の端のずれ（最小サイズなど）として許す幅（px）


def overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(0, w - TOL) * max(0, h - TOL)


def inside(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return (a[0] >= b[0] - TOL and a[1] >= b[1] - TOL
            and a[0] + a[2] <= b[0] + b[2] + TOL and a[1] + a[3] <= b[1] + b[3] + TOL)


@command(group="窓を並べる・置く")
def merge(i: int, *others: int, min: bool = False):
    """i 番目のタイルの窓を、i と others を覆う最小の長方形に広げる（覆われた窓は後ろに残す。--min で最小化）
    i: 広げる窓のタイルの番号（0 は前面の窓）
    others: 覆うタイルの番号
    min: 覆われた窓を最小化する
    """
    if not others:
        raise WinError("覆うタイルの番号を 1 つ以上書いてください（例 merge 2 3）")
    base = at(f"@slot:{i}")
    rects = [base.rect] + [at(f"@slot:{k}").rect for k in others]
    # 引数 min（--min）が組み込みの min を隠すので、builtins から呼ぶ
    x0, y0 = builtins.min(r[0] for r in rects), builtins.min(r[1] for r in rects)
    x1, y1 = max(r[0] + r[2] for r in rects), max(r[1] + r[3] for r in rects)
    box = (x0, y0, x1 - x0, y1 - y0)
    covered: list[Window] = []
    for k, w in enumerate(slots(), 1):
        if w == base:
            continue
        r = w.rect
        if inside(r, box):
            covered.append(w)
        elif overlap(r, box):
            raise WinError(f"タイル {k} を途中で切ってしまうので、{k} も含めてください")
    base.rect = box
    base.focus()
    if min:
        for w in covered:
            w.min()

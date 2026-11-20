"""型（full / v(...) / h(...)）の式と、タイルの計算。"""

import re

from .common import WinError


SHORT_LAYOUT_RE = re.compile(r"[\d\s:/(),.]+")


def is_shorthand_layout(text):
    """略記の式か（数字・空白・: / ( ) . だけでできている）。"""
    return bool(SHORT_LAYOUT_RE.fullmatch(text)) and any(c.isdigit() for c in text)


def shorthand_to_long(text):
    """型の略記を、v(…)/h(…) の式に直す。
    `,`（または空白）＝左右に並べる（v）、/＝上下に重ねる（h）、( ) でまとめる、重み:式 で割合。/ は , より強く結びつく。
    例: `1,2,1` = v(1,2,1)、`1,2:1/1/1,1` = v(1,2:h(1,1,1),1)、`(1,1/1)/1/(1,1)` = h(v(1,h(1,1)),1,v(1,1))。
    `数:` の後が数の並び（a/b/c）なら、並び全体への重み。かっこの式への重みは `数:(…)`。"""
    def err(msg):
        raise WinError(f"型の式（略記）が読めません（{msg}）: {text!r}")

    toks = re.findall(r"\d+(?:\.\d+)?|[:/(),]|\s+|.", text)
    toks = ["SP" if t.isspace() else t for t in toks]
    if any(len(t) == 1 and not (t.isdigit() or t in ":/(),") for t in toks if t != "SP"):
        err("使えない文字があります")
    st = {"i": 0}

    def tok(k=0):
        j = st["i"] + k
        return toks[j] if j < len(toks) else None

    def isnum(t):
        return t is not None and t not in ("SP", ":", "/", "(", ")", ",")

    def build(items):
        if len(items) == 1:
            return items[0][1]
        return ("split", "v", items)

    def parse_cols():
        items, comma = [], False                         # comma: 直前が , で、次の要素を待っている
        while True:
            while tok() == "SP":
                st["i"] += 1
            if tok() == ",":
                if not items or comma:
                    err("「,」の前に要素がありません")
                comma = True
                st["i"] += 1
                continue
            if tok() is None or tok() == ")":
                break
            items.append(parse_item())
            comma = False
        if comma:
            err("末尾の「,」の後に要素が必要です")
        if not items:
            err("空です")
        return items

    def parse_item():
        pre = None
        if isnum(tok()) and tok(1) == ":" and isnum(tok(2)):         # 数:数/数… ＝ 並び全体への重み
            pre = float(tok())
            st["i"] += 2
        chain = [parse_elem()]
        while tok() == "/":
            st["i"] += 1
            chain.append(parse_elem())
        if len(chain) == 1:
            if pre is not None:
                err("「重み:数」は使えません。重みは「重み:式」の形です")
            return chain[0]
        return (1.0 if pre is None else pre, ("split", "h", chain))

    def parse_elem():
        t = tok()
        if isnum(t):
            if tok(1) == ":":
                if tok(2) != "(":
                    err("「数:」の後には ( か数の並びが必要です")
                st["i"] += 2
                return (float(t), parse_group())
            st["i"] += 1
            return (float(t), None)
        if t == "(":
            return (1.0, parse_group())
        err("数か ( が必要です")

    def parse_group():
        st["i"] += 1                                                  # (
        node = build(parse_cols())
        if tok() != ")":
            err(") が必要です")
        st["i"] += 1
        return node

    def emit(node):
        if node is None:
            return "full"
        _, d, items = node
        args = []
        for w, n in items:
            args.append(f"{w:g}" if n is None else (emit(n) if w == 1 else f"{w:g}:{emit(n)}"))
        return f"{d}({','.join(args)})"

    node = build(parse_cols())
    if st["i"] < len(toks):
        err("対応しない ) があります")
    return emit(node)


class LayoutParser:
    """full | v(arg,...) | h(arg,...)。arg は 数 | 式 | 数:式。略記（`1 2 1` など）も読める（shorthand_to_long）。"""

    def __init__(self, text):
        self.s = shorthand_to_long(text) if is_shorthand_layout(text) else text
        self.i = 0

    def err(self, msg):
        raise WinError(f"型の式が読めません（{msg}）: {self.s!r} の {self.i} 文字目")

    def ws(self):
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def parse(self):
        node = self.expr()
        self.ws()
        if self.i != len(self.s):
            self.err("余分な文字")
        return node

    def expr(self):
        self.ws()
        if self.s.startswith("full", self.i):
            self.i += 4
            return ("leaf",)
        m = re.compile(r"([vh])\s*\(").match(self.s, self.i)
        if not m:
            self.err("full か v( h( が必要")
        self.i = m.end()
        args = [self.arg()]
        while True:
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1
                args.append(self.arg())
            else:
                break
        if self.i >= len(self.s) or self.s[self.i] != ")":
            self.err(") が必要")
        self.i += 1
        return ("split", m.group(1), args)

    def arg(self):
        self.ws()
        m = re.compile(r"\d+(?:\.\d+)?").match(self.s, self.i)
        if m:
            weight = float(m.group())
            self.i = m.end()
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ":":
                self.i += 1
                return weight, self.expr()
            return weight, ("leaf",)
        return 1.0, self.expr()


def leaf_rects(node, rect):
    """木を、葉の矩形 (x0, y0, x1, y1) のリストにする（左→右・上→下の順）。"""
    x0, y0, x1, y1 = rect
    if node[0] == "leaf":
        return [rect]
    _, direction, args = node
    total = sum(w for w, _ in args)
    span = (x1 - x0) if direction == "v" else (y1 - y0)
    out, cum, prev = [], 0.0, 0
    for weight, child in args:
        cum += weight
        pos = round(span * cum / total)
        if direction == "v":
            out += leaf_rects(child, (x0 + prev, y0, x0 + pos, y1))
        else:
            out += leaf_rects(child, (x0, y0 + prev, x1, y0 + pos))
        prev = pos
    return out


def compute_rects(expr, area, gap):
    ax, ay, aw, ah = area
    rects = leaf_rects(LayoutParser(expr).parse(), (ax, ay, ax + aw, ay + ah))
    out = []
    for x0, y0, x1, y1 in rects:
        lo, hi = gap // 2, gap - gap // 2
        if x0 > ax: x0 += hi
        if y0 > ay: y0 += hi
        if x1 < ax + aw: x1 -= lo
        if y1 < ay + ah: y1 -= lo
        out.append((x0, y0, x1 - x0, y1 - y0))
    return out


def resolve_layout(cfg, text):
    return cfg["layouts"].get(text, text)

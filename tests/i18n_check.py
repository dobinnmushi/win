"""画面の文字列の翻訳の検査。ソースの tr("日本語") の鍵と、英語の対応表（lib/win/win/i18n_en.py）が合っているかを調べる。
  ・対応表のない鍵（日本語のまま出る文字列）  ・ソースにない古い対応  ・書式の穴（{0} など）が日英で違うもの  ・英語に日本語が混ざったもの
使い方: python3 tests/i18n_check.py   （問題があれば 1 を返す）"""
import ast
import glob
import os
import re
import string
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib", "win", "win")
JP = re.compile(r"[぀-ヿ一-鿿]")
# 訳さないと決めた鍵の頭の部分（nvim の入力欄の Lua・区切りの記号）
UNTRANSLATED = ("-- win prompt（nvim の入力欄）", " ・ ")
# 書式に使わず、そのまま書き出す文書（波括弧が文字として入っている）
NOT_FORMATS = ('"""win の拡張用の関数群（型の定義）',)


def source_keys():
    keys = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "*.py"))):
        if f.endswith(("i18n.py", "i18n_en.py")):
            continue
        for n in ast.walk(ast.parse(open(f, encoding="utf-8").read())):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "tr" and n.args
                    and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
                keys.setdefault(n.args[0].value, os.path.basename(f))
    return keys


def fields(s):
    return sorted((name, conv) for _lit, name, _spec, conv in string.Formatter().parse(s) if name is not None)


def main():
    sys.path.insert(0, os.path.join(ROOT, ".."))
    from win.i18n_en import EN
    keys = source_keys()
    problems = []
    for k, f in keys.items():
        if k not in EN and not k.startswith(UNTRANSLATED):
            problems.append(f"訳がない（{f}）: {k[:50]!r}")
    for k in EN:
        if k not in keys:
            problems.append(f"ソースにない古い対応: {k[:50]!r}")
    for k, en in EN.items():
        if JP.search(en):
            problems.append(f"英語に日本語が混ざっている: {en[:50]!r}")
        if k.startswith(NOT_FORMATS):
            continue
        try:
            if fields(k) != fields(en):
                problems.append(f"書式の穴が違う: {k[:40]!r} ↔ {en[:40]!r}")
        except ValueError as e:
            problems.append(f"書式エラー（{e}）: {en[:40]!r}")
    print(f"鍵 {len(keys)} 個、英語の対応 {len(EN)} 個、問題 {len(problems)} 件")
    for p in problems:
        print("  ", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

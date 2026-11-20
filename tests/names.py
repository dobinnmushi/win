#!/usr/bin/env python3
"""未定義の名前（NameError になりうる参照）を探す。標準の symtable で、各関数・クラスの中の「グローバル参照」が、
そのモジュールの定義・インポート・組み込みのどれにも当たらないものを出す。

  python3 tests/names.py lib/win/*.py
"""
import builtins
import symtable
import sys

BUILTIN = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__package__", "__spec__", "__path__"}
bad = 0
for path in sys.argv[1:]:
    src = open(path, encoding="utf-8").read()
    top = symtable.symtable(src, path, "exec")
    defined = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}
    # `from x import *` があると、定義を静的には決められない（その場合は * の相手を defined に足して渡す）
    extra = {n for n in sys.argv[0:0]}

    def walk(t):
        global bad
        for s in t.get_symbols():
            n = s.get_name()
            if t is not top and s.is_global() and s.is_referenced() and n not in defined and n not in BUILTIN:
                print(f"{path}: {t.get_name()}() が未定義の名前を参照: {n}")
                bad += 1
            if t is top and s.is_referenced() and not s.is_assigned() and not s.is_imported() and not s.is_namespace() \
                    and n not in BUILTIN and n not in defined:
                print(f"{path}: モジュール直下が未定義の名前を参照: {n}")
                bad += 1
        for c in t.get_children():
            walk(c)
    walk(top)
unused = 0
for path in sys.argv[1:]:
    if path.endswith(("__init__.py", "common.py")):                  # common は、他のモジュールへ渡す名前を定義する所
        continue
    top = symtable.symtable(open(path, encoding="utf-8").read(), path, "exec")
    used = set()

    def refs(t):
        for s in t.get_symbols():
            if s.is_referenced() or (t is not top and s.is_global() and s.is_referenced()):
                used.add(s.get_name())
        for c in t.get_children():
            refs(c)
    refs(top)
    for s in top.get_symbols():
        if s.is_imported() and s.get_name() not in used:
            print(f"{path}: 使っていないインポート: {s.get_name()}")
            unused += 1
print("未使用のインポート:", unused)
print("未定義の参照:", bad)
sys.exit(1 if bad else 0)

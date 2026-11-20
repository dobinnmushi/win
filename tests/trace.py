#!/usr/bin/env python3
"""コマンドを動かしている間、窓の位置・大きさの変化を約 20ms ごとに記録して、軌跡（出現・移動・消滅）を出す。
表示上の不具合（点滅・別のモニタをまたぐ・行き来）を、数字で確かめるための道具。

  python3 tests/trace.py [--keys 'key right;key esc' ] [--seconds 8] -- win place 1
窓の種類（クラス）ごとに、位置が変わった時刻と値だけを出す。--keys は dotool に送るキー（前面が小窓のときだけ送る）。
"""
import argparse
import json
import subprocess
import sys
import threading
import time

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))), "lib", "win"))
import win  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--seconds", type=float, default=8)
ap.add_argument("--keys", default="")
ap.add_argument("--wait", type=float, default=3, help="キーを送り始めるまでの秒数")
ap.add_argument("--all", action="store_true", help="既存の窓の動きも出す")
ap.add_argument("cmd", nargs="+")
args = ap.parse_args()

wc = win.WindowCalls()
before = {w["id"] for w in json.loads(wc.call("List")[0])}
log, stop = [], False
t0 = time.time()


def poll():
    last = {}
    while not stop:
        try:
            lst = json.loads(wc.call("List")[0])
        except Exception:
            continue
        ids = set()
        for w in lst:
            if w.get("window_type") != 0:
                continue
            ids.add(w["id"])
            if w["id"] in before and not args.all and w.get("wm_class") != "local.win.tilepick":
                continue                                   # 負荷で測定が遅れないよう、既存の窓の位置は --all のときだけ調べる
            try:
                r = tuple(wc.rect(w["id"]))
            except Exception:
                continue
            key = (w.get("wm_class"), w["id"])
            if last.get(key) != r:
                log.append((time.time() - t0, w.get("wm_class"), w["id"], "出現" if key not in last else "変化", r))
                last[key] = r
        order = tuple(w["id"] for w in lst if w.get("window_type") == 0)          # 重なり順（下→上）
        foc = next((w.get("wm_class") for w in lst if w.get("focus")), None)
        if last.get("order") != order:
            log.append((time.time() - t0, "(重なり順)", 0, "変化", tuple(str(i)[-3:] for i in order)))
            last["order"] = order
        if last.get("focus") != foc:
            log.append((time.time() - t0, "(フォーカス)", 0, "変化", foc))
            last["focus"] = foc
        for key in [k for k in last if isinstance(k, tuple) and k[1] not in ids]:
            log.append((time.time() - t0, key[0], key[1], "消滅", last.pop(key)))
        time.sleep(0.02)


th = threading.Thread(target=poll)
th.start()
p = subprocess.Popen(args.cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def front():
    try:
        return next(w["wm_class"] for w in json.loads(wc.call("List")[0]) if w.get("focus"))
    except StopIteration:
        return None


time.sleep(args.wait)
for k in [x.strip() for x in args.keys.split(";") if x.strip()]:
    if front() == "local.win.tilepick":
        subprocess.run(["dotool"], input=k + "\n", text=True)
    else:
        print(f"!! 前面が {front()}: キー {k} を送らず中止")
        break
    time.sleep(1.0)
try:
    p.wait(max(0.5, args.seconds - (time.time() - t0)))
except subprocess.TimeoutExpired:
    p.terminate()
stop = True
th.join()
out = p.stdout.read().strip()
print(f"出力: {out!r}" if out else "出力なし")
for t, cls, wid, kind, r in log:
    new = wid not in before
    if new or kind == "変化" and (cls in ("local.win.tilepick", "org.gnome.Calculator", "local.win.tile") or cls.startswith("(") or args.all):
        print(f"{t:6.2f}s  {cls:22s} {wid}  {kind}  {r}")

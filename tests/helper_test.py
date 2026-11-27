#!/usr/bin/env python3
"""拡張 win-helper@local の D-Bus の約束を、Shell の外で確かめる。extension.js の import の 1 行を差し替えた写しを gjs で動かし
（Shell の代わりに模擬の global を渡す）、win 側の部品（desktop.py）から呼ぶ。Shell への読み込み（再ログイン後）は、これでは確かめられない。"""
import os
import re
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOCK_NAME = "org.local.WinHelperTest"                                # 本物の拡張（org.local.WinHelper）が動いていても、重ならない名前
os.environ["WIN_HELPER_NAME"] = MOCK_NAME
sys.path.insert(0, os.path.join(ROOT, "lib", "win"))
import win  # noqa: E402

EXT = os.path.join(ROOT, "extension", "win-helper@local", "extension.js")          # リポジトリ側（導入済みのものと同一かも確かめる）
INSTALLED = os.path.expanduser("~/.local/share/gnome-shell/extensions/win-helper@local/extension.js")
fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'OK ' if ok else 'NG '} {label}: {got!r}" + ("" if ok else f"（期待 {want!r}）"))


if os.path.exists(INSTALLED):
    check("導入済みの extension.js が、リポジトリの写しと同一", open(INSTALLED, encoding="utf-8").read() == open(EXT, encoding="utf-8").read(), True)

# 1. 拡張が読み込まれていないとき（サービスがない）のメッセージ
try:
    win.desktops()
    print("（試験用の名前が、すでに使われている）")
except win.WinError as e:
    check("拡張がないときのメッセージ", "win-helper@local" in str(e) and "再ログイン" in str(e), True)

# 2. 写しを作って gjs で動かす
src = open(EXT, encoding="utf-8").read()
src, n = re.subn(r"import \{Extension\} from 'resource:[^']*';", "const Extension = class {};", src)
assert n == 1, "extension.js の import の形が変わった"
for pat, repl in ((r"import Clutter from 'gi://Clutter';", "const Clutter = globalThis.mockShell.Clutter;"),
                  (r"import St from 'gi://St';", "const St = globalThis.mockShell.St;"),
                  (r"import \* as Main from 'resource:[^']*';", "const Main = globalThis.mockShell.Main;")):
    src, n = re.subn(pat, repl, src)
    assert n == 1, "extension.js の import の形が変わった: " + pat
src, n = re.subn(r"Gio\.DBus\.session, 'org\.local\.WinHelper',", f"Gio.DBus.session, '{MOCK_NAME}',", src)
assert n == 1, "extension.js の D-Bus の名前の形が変わった"
tmp = tempfile.mkdtemp(prefix="win-helper-")
copy = os.path.join(tmp, "extension.js")
open(copy, "w", encoding="utf-8").write(src)
flash_log = os.path.join(tmp, "flash.log")
env = dict(os.environ, HELPER_COPY=copy, HELPER_SECONDS="25", HELPER_FLASH_LOG=flash_log)
p = subprocess.Popen(["gjs", "-m", os.path.join(ROOT, "tests", "helper_gjs.js")], env=env, stderr=subprocess.PIPE, text=True)
try:
    for _ in range(50):
        if subprocess.run(["busctl", "--user", "status", MOCK_NAME], capture_output=True).returncode == 0:
            break
        time.sleep(0.1)
    else:
        print("NG  サービスが立ち上がらない:", p.stderr.read()[:300])
        sys.exit(1)
    check("desktops()（番号は 1 から。模擬は 0 番目=2 番、4 枚）", win.desktops(), (2, 4))
    win.switch_desktop(3)
    check("switch_desktop(3) のあと", win.desktops(), (3, 4))
    win.switch_relative(-1)
    check("switch_relative(-1) のあと", win.desktops(), (2, 4))
    win.switch_relative(2)
    check("switch_relative(2) のあと", win.desktops(), (4, 4))
    for label, call in (("switch_desktop(9)", lambda: win.switch_desktop(9)), ("switch_desktop(0)", lambda: win.switch_desktop(0)),
                        ("switch_relative(1)（端）", lambda: win.switch_relative(1))):
        try:
            call()
            check(label + " は失敗するはず", "成功", "WinError")
        except win.WinError as e:
            check(label, str(e).startswith("デスクトップ"), True)
    out = subprocess.run(["busctl", "--user", "call", MOCK_NAME, "/org/local/WinHelper", "org.local.WinHelper", "Switch", "i", "99"],
                         capture_output=True, text=True).stdout.strip()
    check("拡張の Switch(99)（範囲外）は false", out, "b false")
    # Flash（枠を光らせる）。描画そのものは Shell でしか確かめられないので、模擬の St/Main に渡した値を見る
    def flash(*args):
        return subprocess.run(["busctl", "--user", "call", MOCK_NAME, "/org/local/WinHelper", "org.local.WinHelper", "Flash", "sii", *args],
                              capture_output=True, text=True).stdout.strip()
    check("Flash（前面の窓がある）は true", flash("#62a0ea", "4", "450"), "b true")
    time.sleep(0.3)
    log = open(flash_log, encoding="utf-8").read().split("\n") if os.path.exists(flash_log) else []
    check("枠の縁取りが、前面の窓の枠・指定の色と太さで作られる", log[:1], ["widget x=100 y=200 w=800 h=600 style=border: 4px solid #62a0ea; border-radius: 12px;"])
    check("透明にして消す（長さ 450）", log[1:2], ["ease opacity=0 duration=450"])
    win.flash_focus({"flash": {"enabled": False, "color": "#fff", "width": 1, "duration": 1}})
    time.sleep(0.2)
    check("enabled = false のときは呼ばない", len(open(flash_log, encoding="utf-8").read().split("\n")), len(log))
    # コマンド（win desktop）の経路
    def cli(*args):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "win"), "desktop", *args], capture_output=True, text=True)
        return r.returncode, (r.stdout.strip() or r.stderr.strip())
    check("win desktop（表示）", cli(), (0, "デスクトップ 4/4"))
    check("win desktop 2", cli("2"), (0, "デスクトップ 2/4"))
    check("win desktop next", cli("next"), (0, "デスクトップ 3/4"))
    check("win desktop prev", cli("prev"), (0, "デスクトップ 2/4"))
    check("win desktop 9（範囲外）", cli("9")[0], 1)
    check("win desktop abc（不正）", cli("abc")[0], 1)
finally:
    p.terminate()
    p.wait(5)
print("不一致:", fails)
sys.exit(1 if fails else 0)

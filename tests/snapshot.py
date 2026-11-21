#!/usr/bin/env python3
"""副作用のない出力（ヘルプ・型の一覧・LSP の応答・純粋関数の結果）を 1 つのテキストにして標準出力へ出す。
リファクタリングの前後で出力を取って diff を見る。窓や設定は動かさない（設定は tests/fixtures の写しを使う）。

  python3 tests/snapshot.py > before.txt   # 変更前
  python3 tests/snapshot.py > after.txt    # 変更後
  diff before.txt after.txt
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIN = os.path.join(ROOT, "bin", "win")
FIX = os.path.join(ROOT, "tests", "fixtures")
TMP = tempfile.mkdtemp(prefix="win-snap-")
shutil.copytree(os.path.join(FIX, "ext"), os.path.join(TMP, "ext"))
for f in ("commands.toml", "sets.toml"):
    shutil.copy(os.path.join(FIX, f), TMP)
ENV = dict(os.environ, WIN_COMMANDS=os.path.join(TMP, "commands.toml"), WIN_SETS=os.path.join(TMP, "sets.toml"),
           WIN_EXT=os.path.join(TMP, "ext"), XDG_STATE_HOME=os.path.join(TMP, "state"))
ENV["PYTHONPATH"] = ""
ENV.setdefault("WIN_LANG", "ja")        # 出力の言語。環境に左右されないよう日本語に固定（英語の出力を見るなら WIN_LANG=en で呼ぶ）


def section(title):
    print(f"\n===== {title}")


def cli(*args):
    section("win " + " ".join(args))
    p = subprocess.run([sys.executable, WIN, *args], capture_output=True, text=True, env=ENV, timeout=60, stdin=subprocess.DEVNULL)
    print(f"[rc={p.returncode}]")
    print(p.stdout.replace(TMP, "<TMP>").rstrip())
    if p.stderr.strip():
        print("[stderr]", p.stderr.replace(TMP, "<TMP>").rstrip())


for a in (["-h"], ["help"], ["help", "api"], ["help", "commands"], ["help", "sets"], ["help", "layouts"], ["help", "place"],
          ["help", "here"], ["help", "layout"], ["help", "swap"], ["help", "merge"], ["help", "set"], ["help", "@slot:"],
          ["help", "--names"], ["help", "--py"], ["help", "--py", "--names"], ["layouts"], ["run"],
          ["place", "xyz"], ["place", "-h"], ["here", "-h"], ["layout", "-h"], ["nosuchcommand"]):
    cli(*a)


# --- LSP（標準入出力）
def lsp(requests):
    def frame(o):
        b = json.dumps(o).encode()
        return b"Content-Length: %d\r\n\r\n" % len(b) + b
    data = b"".join(frame(r) for r in requests) + frame({"jsonrpc": "2.0", "id": 99, "method": "shutdown"}) \
        + frame({"jsonrpc": "2.0", "method": "exit"})
    p = subprocess.run([sys.executable, WIN, "lsp"], input=data, capture_output=True, env=ENV, timeout=60)
    out, res = p.stdout, []
    while out:
        head, _, rest = out.partition(b"\r\n\r\n")
        n = int(head.split(b":")[1])
        res.append(json.loads(rest[:n]))
        out = rest[n:]
    return res


def lsp_case(text, line, col, method):
    uri = "file:///t.win"
    rs = lsp([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"capabilities": {}}},
              {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {"uri": uri, "text": text}}},
              {"jsonrpc": "2.0", "id": 2, "method": method,
               "params": {"textDocument": {"uri": uri}, "position": {"line": line, "character": col}}}])
    r = next((x for x in rs if x.get("id") == 2), None)
    section(f"lsp {method} {text!r} @{col}")
    res = (r or {}).get("result")
    if isinstance(res, dict) and "items" in res:
        res = sorted(i["label"] for i in res["items"] if "@" not in i["label"][:1])[:60]       # @ 以降は開いている窓に依るので省く
    print(json.dumps(res, ensure_ascii=False, sort_keys=True)[:1500])


lsp_case("pla", 0, 3, "textDocument/completion")
lsp_case("place ", 0, 6, "textDocument/completion")
lsp_case("place free", 0, 10, "textDocument/signatureHelp")
lsp_case("swap ", 0, 5, "textDocument/signatureHelp")
lsp_case("layout ", 0, 7, "textDocument/completion")
lsp_case("place", 0, 3, "textDocument/hover")

# --- 純粋関数（モジュールの中の名前を探して呼ぶ）
sys.path.insert(0, os.path.join(ROOT, "lib", "win"))
os.environ.update({k: v for k, v in ENV.items() if k.startswith("WIN_") or k == "XDG_STATE_HOME"})
import win as W  # noqa: E402


def fn(name):
    return getattr(W, name)


def show(label, f):
    try:
        r = f()
    except Exception as e:                                # 例外の型と文面も記録する
        r = f"例外 {type(e).__name__}: {e}"
    print(f"{label}: {r!r}")


section("pure")
for t in ("1,2,1", "1,2:1/1/1,1", "(1,1/1)/1/(1,1)", "1 2 1", "1/1", "a,b", "2:(1,1)"):
    show(f"shorthand_to_long({t!r})", lambda t=t: fn("shorthand_to_long")(t))
cfg = {"layouts": dict(fn("BUILTIN_LAYOUTS")), "insets": {"top": 32, "bottom": 0, "left": 0, "right": 0}, "gap": 0}
for e in ("full", "lr", "v(1,2,2:h(1,1))", "quad", "h(1,v(1,1))", "thirds", "nosuch"):
    show(f"compute_rects({e!r})", lambda e=e: fn("compute_rects")(fn("resolve_layout")(cfg, e), (0, 0, 1000, 600), 0))
show("compute_rects gap", lambda: fn("compute_rects")("v(1,1)", (0, 0, 1000, 600), 10))
for q, t in (("ff", "firefox"), ("fx", "firefox"), ("ptx", "org.gnome.Ptyxis"), ("zzz", "firefox"), ("", "x")):
    show(f"fuzzy({q!r},{t!r})", lambda q=q, t=t: fn("fuzzy")(q, t))
wins = [{"id": 1, "cls": "firefox", "title": "Mozilla Firefox", "icon": ""}, {"id": 2, "cls": "org.gnome.Ptyxis", "title": "nvim", "icon": ""}]
for q in ("", "fire", "nv", "!calc"):
    show(f"tile_candidates({q!r})", lambda q=q: fn("tile_candidates")(q, wins, [{"id": "a", "name": "Calculator", "desc": "d", "icon": ""}]))
items = [{"name": "full", "expr": "full", "n": 1, "rects": [(0, 0, 1, 1)]}, {"name": "lr", "expr": "v(1,1)", "n": 2, "rects": []}]
for q in ("", "l", "1,2", "v(1,h(1,1))"):
    show(f"layout_candidates({q!r})", lambda q=q: fn("layout_candidates")(q, items))
for line in ("layout lr firefox", "close", "layout x", "set foo", "place 1 firefox", "swap 1 2", "nosuch", "layout lr\nclose", ""):
    show(f"check_win_line({line!r})", lambda l=line: fn("check_win_line")(l))
show("win_lines", lambda: fn("win_lines")("a\n# c\n\nb  # d"))
for c in ({"type": "win", "run": "layout lr firefox"}, {"type": "shell", "run": "echo hi"}, {"type": "x"}):
    show(f"describe_command({c})", lambda c=c: fn("describe_command")(c))
show("set_summary", lambda: fn("set_summary")({"type": "win", "run": "layout v(1,2,2:h(1,1)) org.gnome.Ptyxis? firefox? slack?"}))
show("selector_for", lambda: fn("selector_for")({"id": 1, "wm_class": "firefox", "title": "a"}, [{"id": 1, "wm_class": "firefox", "title": "a"}]))
for k in ("Left", "Right", "Up", "Down"):
    show(f"move_toward({k})", lambda k=k: fn("move_toward")([(0, 0, .3, 1), (.3, 0, .3, 1), (.6, 0, .4, .5), (.6, .5, .4, .5)], 1, k))
show("move_toward 端", lambda: fn("move_toward")([(0, 0, 1, 1)], 0, "Left"))
show("Item", lambda: fn("Item")("a", "b"))
show("Map", lambda: fn("Map")([(0, 0, 1, 1)], current=0))
show("api_entries の名前", lambda: sorted(k for k in fn("api_entries")() if k in ("Dialog", "choose", "Dialog.events", "Item", "Map", "Event", "ask", "confirm", "pick_tile", "pick_window", "window_items")))
rows = [{"t": 1700000000, "c": "focus", "v": "key"}, {"t": 1700000100, "c": "focus", "v": "key"}, {"t": 1700000200, "c": "layout", "v": "typed"},
        {"t": 1700086500, "c": "focus", "v": "typed"}, {"t": 1700000300, "c": "bogus", "v": "x"}]
show("summarize（使用の集計）", lambda: fn("summarize")(rows))
shutil.rmtree(TMP, ignore_errors=True)

"""エディタ向けの補完・説明（win lsp）。"""

import json
import shlex
import sys

from .common import WinError
from .i18n import tr
from .screen import load_config
from .dbus import AT_SELECTORS, WindowCalls, normal_windows, selector_for
from .store import SIGNATURES, load_commands, load_sets, signature_parts
from .prompt import SUBCOMMANDS, suggest
from .ext import EXT, ext_signatures, ext_spec


class WinLsp:
    """win の命令（1 行に 1 つ、# はコメント）を書く文書に、補完・引数の書式・説明・誤りの印を出す LSP。標準入出力で話す。"""

    def __init__(self):
        self.docs = {}                                    # uri → 本文
        self.utf16 = True                                 # 位置の数え方（utf-32 を使えるなら Python の添字と同じ）
        self.cfg = load_config()
        self.spec = {"layouts": self.cfg["layouts"], "commands": load_commands(), "sets": load_sets(), "windows": [],
                     **ext_spec()}
        SIGNATURES.update(ext_signatures())

    # 送受信 ---------------------------------------------------------------
    def read(self):
        length = None
        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                break
            k, _, v = line.decode("ascii").partition(":")
            if k.lower() == "content-length":
                length = int(v.strip())
        return json.loads(sys.stdin.buffer.read(length).decode("utf-8")) if length else {}

    def send(self, msg):
        body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
        sys.stdout.buffer.flush()

    def serve(self):
        while True:
            msg = self.read()
            if msg is None:
                return 0
            method, mid = msg.get("method"), msg.get("id")
            try:
                result = self.handle(method, msg.get("params") or {})
            except Exception as e:                        # 1 つの要求の失敗で止まらない
                if mid is not None:
                    self.send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"}})
                continue
            if method == "exit":
                return 0
            if mid is not None and method is not None:
                self.send({"jsonrpc": "2.0", "id": mid, "result": result})

    # 位置 ------------------------------------------------------------------
    def to_index(self, text, ch):
        """LSP の文字位置 → Python の添字。"""
        if not self.utf16:
            return ch
        i = n = 0
        while i < len(text) and n < ch:
            n += 2 if ord(text[i]) > 0xFFFF else 1
            i += 1
        return i

    def to_lsp(self, text, i):
        return i if not self.utf16 else sum(2 if ord(c) > 0xFFFF else 1 for c in text[:i])

    def line_at(self, params):
        text = self.docs.get(params["textDocument"]["uri"], "")
        lines = text.split("\n")
        ln = params["position"]["line"]
        line = lines[ln] if ln < len(lines) else ""
        return ln, line, self.to_index(line, params["position"]["character"])

    @staticmethod
    def strip_win(prefix):
        return prefix[4:] if prefix.startswith("win ") else prefix

    # 要求 ------------------------------------------------------------------
    def handle(self, method, p):
        if method == "initialize":
            encs = (p.get("capabilities", {}).get("general", {}) or {}).get("positionEncodings") or []
            self.utf16 = "utf-32" not in encs
            return {"capabilities": {
                        "positionEncoding": "utf-16" if self.utf16 else "utf-32",
                        "textDocumentSync": 1,
                        "completionProvider": {"triggerCharacters": [" ", "@", "-"]},
                        "signatureHelpProvider": {"triggerCharacters": [" "], "retriggerCharacters": [" "]},
                        "hoverProvider": True},
                    "serverInfo": {"name": "win"}}
        if method in ("textDocument/didOpen", "textDocument/didChange"):
            uri = p["textDocument"]["uri"]
            self.docs[uri] = p["textDocument"]["text"] if method.endswith("didOpen") else p["contentChanges"][-1]["text"]
            self.publish(uri)
            return None
        if method == "textDocument/didClose":
            self.docs.pop(p["textDocument"]["uri"], None)
            return None
        if method == "textDocument/completion":
            return self.completion(p)
        if method == "textDocument/signatureHelp":
            return self.signature(p)
        if method == "textDocument/hover":
            return self.hover(p)
        if method == "shutdown":
            return None
        return None

    def refresh_windows(self):
        try:
            wc = WindowCalls()
            ws = normal_windows(wc)
            self.spec["windows"] = [{"sel": selector_for(w, ws), "cls": w.get("wm_class") or "",
                                     "title": (w.get("title") or "")[:60]} for w in reversed(ws)]
        except WinError:
            self.spec["windows"] = []

    def completion(self, p):
        ln, line, i = self.line_at(p)
        prefix = line[:i]
        if prefix.lstrip().startswith("#"):
            return []
        body = self.strip_win(prefix.lstrip())
        self.refresh_windows()
        cands = suggest(body, self.spec)
        start = i - len(prefix.split(" ")[-1])
        rng = {"start": {"line": ln, "character": self.to_lsp(line, start)},
               "end": {"line": ln, "character": self.to_lsp(line, i)}}
        first = len(body.split(" ")) == 1
        items = []
        for k, (ins, desc) in enumerate(cands):
            word = ins.rstrip(" ")
            try:
                label = shlex.split(word)[0] if word.startswith(("'", '"')) else word      # 表示は引用符なし、挿入は引用符つき
            except (ValueError, IndexError):
                label = word
            items.append({"label": label, "detail": desc, "kind": 3 if first else 12, "sortText": f"{k:04d}",
                          "filterText": label, "textEdit": {"range": rng, "newText": word}})
        return {"isIncomplete": True, "items": items}

    def signature(self, p):
        _ln, line, i = self.line_at(p)
        sp = signature_parts(self.strip_win(line[:i].lstrip()))
        if sp is None:
            return None
        label = f"win {sp['cmd']} " + " ".join(t for t, _l, _d in sp["items"])
        params = [{"label": t, "documentation": d} for t, _l, d in sp["items"]]
        active = next((k for k, (_t, l, _d) in enumerate(sp["items"]) if l == sp["active"]), None)
        sig = {"label": label, "documentation": sp["summary"], "parameters": params}
        if active is not None:
            sig["activeParameter"] = active
        return {"signatures": [sig], "activeSignature": 0, **({"activeParameter": active} if active is not None else {})}

    def hover(self, p):
        _ln, line, i = self.line_at(p)
        if line.lstrip().startswith("#"):
            return None
        a = line.rfind(" ", 0, i) + 1
        b = line.find(" ", i)
        word = line[a:] if b < 0 else line[a:b]
        tokens = self.strip_win(line.lstrip()).split(" ")
        if not word:
            return None
        text = None
        if word == tokens[0] and word in EXT:
            c = EXT[word]
            text = f"```\n{c.usage()}\n```\n{c.doc or tr('（説明なし）')}\n\n" + "\n".join(
                f"- `{part[1]}` {part[-1] if part[0] != 'pos' else part[2]}" for part in c.parts()) + \
                (tr("\n\n定義: `{0}:{1}`").format(c.file, c.line) if c.file else "")
        elif word == tokens[0] and word in SIGNATURES:
            parts, summary = SIGNATURES[word]
            sp = signature_parts(f"{word} ") or {"items": []}
            text = f"```\nwin {word} {' '.join(t for t, _l, _d in sp['items'])}\n```\n{summary}\n\n" + \
                   "\n".join(f"- `{t}` {d}" for t, _l, d in sp["items"])
        elif word.startswith("@"):
            text = "\n".join(f"`{s}` {d}" for s, d in AT_SELECTORS if word.lower().startswith(s.rstrip(":")) or s.startswith(word.lower()))
        elif word in self.spec["layouts"]:
            text = tr("型 `{0}` = `{1}`").format(word, self.spec['layouts'][word])
        else:
            self.refresh_windows()
            hits = [w for w in self.spec["windows"] if word.lower() in (w["cls"] + " " + w["title"]).lower()]
            if hits:
                text = tr("当たる窓:\n") + "\n".join(f"- `{w['cls']}` {w['title']}" for w in hits[:8])
        return {"contents": {"kind": "markdown", "value": text}} if text else None

    def publish(self, uri):
        diags = []
        known = {c for c, _ in SUBCOMMANDS} | set(EXT) | {"prompt"}
        for ln, line in enumerate(self.docs.get(uri, "").split("\n")):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            try:
                argv = shlex.split(s)
            except ValueError as e:
                msg = tr("引用符が閉じていません: {0}").format(e)
            else:
                argv = argv[1:] if argv and argv[0] == "win" else argv
                msg = tr("知らない命令です: {0}（一覧は win help）").format(argv[0]) if argv and argv[0] not in known else None
            if msg:
                diags.append({"range": {"start": {"line": ln, "character": 0},
                                        "end": {"line": ln, "character": self.to_lsp(line, len(line))}},
                              "severity": 1, "source": "win", "message": msg})
        self.send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                   "params": {"uri": uri, "diagnostics": diags}})


def cmd_lsp(args):
    return WinLsp().serve()

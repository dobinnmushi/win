"""使用の記録（コマンド名と、キー経由か手入力かだけ。引数は記録しない）。ショートカットの割り当てを、実際の使い方に基づいて見直すため。

1 行 1 回の実行（JSON）を ~/.local/state/win/usage.log（WIN_USAGE で差し替え可）に追記する。止めるには `win stats off`（usage.log.off を置く）。
キー経由かは、親のプロセスが systemd か（GNOME のカスタムショートカットは、systemd の下で起動される）で見分ける。
"""

import collections
import json
import os
import time

STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "win")
USAGE_FILE = os.environ.get("WIN_USAGE") or os.path.join(STATE_DIR, "usage.log")
OFF_FILE = USAGE_FILE + ".off"
SKIP = {"lsp", "stats"}        # エディタが常駐で起こすもの・この集計そのもの


def invoked_via():
    """"key"（ショートカットから）か "typed"（端末・小窓・スクリプトなどから）。"""
    try:
        with open(f"/proc/{os.getppid()}/comm", encoding="utf-8") as f:
            return "key" if f.read().strip() == "systemd" else "typed"
    except OSError:
        return "typed"


def record(cmd):
    """コマンド名 cmd の実行を 1 行追記する（失敗しても何もしない。約 0.1ms）。"""
    if cmd in SKIP or os.path.exists(OFF_FILE):
        return
    line = (json.dumps({"t": int(time.time()), "c": cmd, "v": invoked_via()}, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        try:
            fd = os.open(USAGE_FILE, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        except FileNotFoundError:
            os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
            fd = os.open(USAGE_FILE, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except OSError:
        pass


def read_usage(days=30):
    """直近 days 日の記録 [{"t", "c", "v"}]。読めない行は飛ばす。"""
    since = time.time() - days * 86400
    out = []
    try:
        with open(USAGE_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("t", 0) >= since:
                    out.append(r)
    except OSError:
        pass
    return out


def summarize(rows):
    """コマンドごとの {"total", "key", "typed", "days"（実行した日の数）} を、回数の多い順に [(コマンド, 集計)]。"""
    by = collections.defaultdict(lambda: {"total": 0, "key": 0, "typed": 0, "_days": set()})
    for r in rows:
        s = by[r.get("c", "?")]
        s["total"] += 1
        s[r.get("v") if r.get("v") in ("key", "typed") else "typed"] += 1
        s["_days"].add(time.strftime("%Y-%m-%d", time.localtime(r.get("t", 0))))
    out = [(c, {**{k: v for k, v in s.items() if k != "_days"}, "days": len(s["_days"])}) for c, s in by.items()]
    return sorted(out, key=lambda kv: (-kv[1]["total"], kv[0]))

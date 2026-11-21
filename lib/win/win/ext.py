"""拡張（~/.config/win/ext/*.py）と winapi。"""

import functools
import glob
import importlib
import inspect
import json
import os
import re
import shlex
import subprocess
import sys
import time
import traceback
import types
import typing

from .common import CONFIG, WinError
from .i18n import tr
from .screen import load_config, work_area
from .layouts import compute_rects, resolve_layout
from .dbus import AT_SELECTORS, WindowCalls, find_windows, focused, normal_windows, target, usable_windows
from .store import COMMANDS, SETS, SIGNATURES, describe_command, launch_for_class, load_commands, load_sets, win_lines
from .placement import launch, parse_window_spec, place_settled
from .sets import run_entry, set_summary
from .prompt import run_inline
from .appstate import current_tiles, cycle_stack, find_stack, tile_order
from .desktop import desktops, switch_desktop, switch_relative
from . import groups as grp
from .tilepick import slot_map
from .pickers import pick_window_map
from .dialog import Dialog, Event, Item, Map, ask, choose, confirm, pick_tile, window_items
from .dialog import pick_window as pick_window_dialog


EXT_DIR = os.environ.get("WIN_EXT") or os.path.join(os.path.dirname(COMMANDS), "ext")


EXT = {}                # 命令の名前 → ExtCommand（@command を付けた関数）


EXT_ERRORS = []         # [(ファイル, 説明)]。読み込めなかった拡張


_EXT_STATE = {"loaded": False, "mods": []}


class Window:
    """窓 1 枚。位置と大きさは rect（x, y, 幅, 高さ。論理ピクセル）で読み書きする。"""

    def __init__(self, info):
        self._info = info

    @property
    def id(self):
        return self._info["id"]

    @property
    def cls(self):
        return self._info.get("wm_class") or ""

    @property
    def title(self):
        return self._info.get("title") or ""

    @property
    def maximized(self):
        d = _wc().details(self.id)
        return bool(d.get("maximized_horizontally") and d.get("maximized_vertically"))

    @property
    def desktop(self):
        wc = _wc()
        return next((w.get("workspace", 0) for w in wc.list() if w["id"] == self.id), 0) + 1

    @desktop.setter
    def desktop(self, n):
        _wc().call("MoveToWorkspace", "uu", self.id, max(0, int(n) - 1))

    @property
    def rect(self):
        return tuple(_wc().rect(self.id))

    @rect.setter
    def rect(self, r):
        wc = _wc()
        if self.maximized:
            wc.simple("Unmaximize", self.id)
        place_settled(wc, self.id, tuple(int(v) for v in r))

    def focus(self):
        wc = _wc()
        if wc.details(self.id).get("minimized"):
            wc.simple("Unminimize", self.id)
        wc.simple("Activate", self.id)

    def max(self):
        _wc().simple("Maximize", self.id)

    def unmax(self):
        _wc().simple("Unmaximize", self.id)

    def min(self):
        _wc().simple("Minimize", self.id)

    def unmin(self):
        _wc().simple("Unminimize", self.id)

    def close(self):
        _wc().simple("Close", self.id)

    @property
    def minimized(self):
        return bool(_wc().details(self.id).get("minimized"))

    def move(self, x, y):
        _, _, w, h = self.rect                            # rect と同じ枠の座標で動かす（Move は影の分ずれる）
        _wc().move_resize(self.id, int(x), int(y), w, h)
        self._settle(lambda r: r[:2] == (int(x), int(y)))

    def resize(self, width, height):
        x, y, _, _ = self.rect
        _wc().move_resize(self.id, x, y, int(width), int(height))
        self._settle(lambda r: r[2:] == (int(width), int(height)))

    def _settle(self, done, timeout=0.6):
        """GNOME が動かし終えるまで（最大 timeout 秒）待つ。直後に rect を読んでも新しい値になるように。"""
        end = time.time() + timeout
        while time.time() < end and not done(tuple(_wc().rect(self.id))):
            time.sleep(0.03)

    def above(self):
        _wc().simple("MakeAbove", self.id)

    def unabove(self):
        _wc().simple("UnmakeAbove", self.id)

    def __eq__(self, other):
        return isinstance(other, Window) and other.id == self.id

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return f"Window({self.id}, {self.cls!r}, {self.title[:30]!r})"


_WC = {"wc": None}


def _wc():
    if _WC["wc"] is None:
        _WC["wc"] = WindowCalls()
    return _WC["wc"]


def api_at(sel):
    """窓の指定（クラス・題名の一部、ID、@left などの位置・状態）に当たる窓 1 枚。なければ WinError。"""
    return Window(target(_wc(), sel))


def api_find(sel):
    """窓の指定に当たる窓すべて（前面に近い順）。なければ空のリスト。"""
    wc = _wc()
    return [Window(w) for w in find_windows(wc, sel, normal_windows(wc)[::-1])]


def api_windows():
    """今のワークスペースで最小化されていない窓（前面に近い順）。"""
    return [Window(w) for w in usable_windows(_wc())]


def api_focused():
    """前面の窓。"""
    return Window(focused(_wc()))


def api_area():
    """窓を置ける領域 (x, y, 幅, 高さ)。基準のモニタから、上下左右の余白を除いたもの。"""
    return tuple(work_area(load_config()))


def _run_argv(argv):
    """win の命令（引数のリスト）をこのプロセスで実行する。失敗したら WinError。"""
    rc, so, se = run_inline([str(a) for a in argv])
    if so:
        print(so, end="")
    if rc:
        raise WinError(se.strip().removeprefix("win: ") or tr("失敗しました: {0}").format(' '.join(map(str, argv))))


def api_run(line):
    """win の命令を 1 行（複数行なら上から順に）実行する。失敗したら WinError。"""
    for l in win_lines(line):
        argv = shlex.split(l)
        _run_argv(argv[1:] if argv and argv[0] == "win" else argv)


def _sel_text(w):
    return str(w.id) if isinstance(w, Window) else str(w)


def api_layout(expr, *windows, gap=None):
    """型 expr のタイルに、windows を順に並べる。"""
    _run_argv(["layout", expr, *map(_sel_text, windows)] + (["--gap", gap] if gap is not None else []))


def api_apply_set(name):
    """保存したセットを適用する。"""
    sets = load_sets()
    if name not in sets:
        raise WinError(tr("セットが見つかりません: {0}（一覧は win help sets）").format(name))
    if run_entry(sets[name]):
        raise WinError(tr("セット「{0}」を適用できませんでした").format(name))


def api_run_command(name):
    """登録したコマンドを実行する。"""
    cmds = load_commands()
    if name not in cmds:
        raise WinError(tr("コマンドが見つかりません: {0}（一覧は win help commands）").format(name))
    if run_entry(cmds[name]):
        raise WinError(tr("コマンド「{0}」が失敗しました").format(name))


def api_nav(direction):
    """前面の窓から見て、その向きの窓へフォーカスを移す。"""
    _run_argv(["nav", direction])


def api_launch(cmdline, timeout=20):
    """コマンドを起動し、新しく出た窓を返す。"""
    return Window(launch(_wc(), cmdline, timeout))


def api_layouts():
    """型の一覧 {名前: 式}。"""
    return dict(load_config()["layouts"])


def api_browse(*urls):
    """Firefox を新しい窓で開き、URL をタブとして並べる。"""
    _run_argv(["browse", *urls])


def api_term(*dirs):
    """端末を、作業ディレクトリごとのタブつきで新しく開く。"""
    _run_argv(["term", *dirs])


class _Sel:
    """命令の引数の既定値にする窓の指定（呼ばれたときに窓にする）。"""

    def __init__(self, spec):
        self.spec = spec

    def __repr__(self):
        return self.spec


def api_sel(spec):
    """引数の既定値に書く窓の指定（例 a: Window = sel("@left")）。型の上では Window として扱われる。"""
    return _Sel(spec)


def api_tiles(expr, rect=None):
    """rect（省くと作業領域）を型 expr で分けた、各タイルの (x, y, 幅, 高さ)。タイルの間には設定の隙間を取る。"""
    cfg = load_config()
    return [tuple(r) for r in compute_rects(resolve_layout(cfg, expr), tuple(rect) if rect else work_area(cfg), cfg["gap"])]


def api_slots():
    """いまの並び（窓の位置から逆算）の窓を、番号順に。"""
    wc, cfg = _wc(), load_config()
    cur = current_tiles(wc, cfg)
    if cur["tree"] is None:
        return []
    return [Window(cur["by_id"][i]) for i in tile_order(cur, cfg)[1]]


def api_resolve(spec):
    """layout の窓の列と同じ書き方を窓にする: - は None（空ける）、!コマンド は起動した窓、クラス名? はなければ起動、ほかは at()。"""
    if spec in ("-", "_"):
        return None
    wc = _wc()
    if spec.startswith("!"):
        return Window(launch(wc, spec[1:]))
    base, optional, fallback = parse_window_spec(spec)
    found = find_windows(wc, base, normal_windows(wc)[::-1])
    if found:
        return Window(found[0])
    if optional:
        cmdline = fallback or launch_for_class(base)
        if not cmdline:
            raise WinError(tr("窓が見つからず、起動コマンドも分かりません: {0}").format(base))
        return Window(launch(wc, cmdline))
    raise WinError(tr("窓が見つかりません: {0}").format(spec))


class ApiDialog(Dialog):
    """拡張向けの Dialog（窓は Window で返す）。"""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("wrap", Window)
        super().__init__(*args, **kwargs)


ApiDialog.__name__ = ApiDialog.__qualname__ = "Dialog"


def api_stack(n=0):
    """n 番目のタイル（0 は前面の窓のいるタイル）に重なっている窓（層）を、巡回の順（ID の昇順）に。"""
    return [Window(w) for w in find_stack(_wc(), int(n))["layers"]]


def api_cycle(n=0, d=1):
    """n 番目のタイルの重なりで、いま手前の層から d 層ずらした窓を前面に出して返す（一巡する）。重なりがなければ WinError。"""
    return Window(cycle_stack(_wc(), int(n), int(d))[1])


def api_switch_desktop(n, relative=False):
    """n 番目（1 から）のデスクトップへ切り替える。relative なら、いまから n 個ずれたデスクトップへ。"""
    switch_relative(int(n)) if relative else switch_desktop(int(n))


class Group:
    """窓のグループ（名前つき・保存つき）。メンバーは 1 つの枠を共有し、タブのように切り替わる。"""

    def __init__(self, name):
        self.name = name

    def _data(self):
        return grp.get_group(_wc(), self.name)

    @property
    def members(self):
        wins = {w["id"]: w for w in normal_windows(_wc())}
        return [Window(wins[m["id"]]) for m in self._data()["members"] if m["id"] in wins]

    @property
    def active(self):
        g = self._data()
        return next((w for w in self.members if w.id == g.get("active")), None)

    @property
    def rect(self):
        return tuple(grp.group_rect(_wc(), self._data()))

    def add(self, *windows):
        """窓を足し、グループの枠へ置いて、最後に足した窓を手前にする（ほかのグループにいた窓は移る）。"""
        grp.add_members(_wc(), self.name, [w._info for w in windows])

    def remove(self, *windows):
        """窓をグループから外す。"""
        grp.remove_members(_wc(), [w._info for w in windows])

    def delete(self):
        """グループを消す（窓は閉じない）。"""
        grp.delete_group(_wc(), self.name)

    def next(self, d=1):
        """いま手前のメンバーから d 個ずれたメンバーを、グループの枠へ置いて前面に出して返す（一巡する）。"""
        return Window(grp.cycle_group(_wc(), self.name, d)[0])

    def show(self):
        """全メンバーをグループの枠へ置き（別のデスクトップ・最小化も戻す）、手前のメンバーを前面に出す。"""
        grp.show_group(_wc(), self.name)

    def place(self, rect):
        """グループの枠を rect に変えて、全メンバーをそこへ置く。"""
        grp.place_group(_wc(), self.name, tuple(int(v) for v in rect))


def api_groups():
    """いまあるグループすべて。"""
    return [Group(n) for n in grp.load_groups(_wc())]


def api_group(name, *windows):
    """name のグループ。windows を渡すと、その窓で新しく作る（すでにあれば足す）。なければ WinError。"""
    wc = _wc()
    if windows:
        if name in grp.load_groups(wc):
            Group(name).add(*windows)
        else:
            grp.create_group(wc, name, [w._info for w in windows])
    else:
        grp.get_group(wc, name)
    return Group(name)


def api_group_of(w):
    """窓 w の属するグループ。どこにも属さなければ None。"""
    n = grp.group_of(_wc(), w.id)
    return None if n is None else Group(n)


def api_window_items(exclude=()):
    """今のワークスペースで最小化されていない窓を、一覧の行にする（value は Window）。"""
    return window_items(_wc(), exclude, wrap=Window)


def api_pick_window(title=tr("窓を選ぶ"), *, launch=True, exclude=(), map=None):
    """窓を 1 枚選ぶ。選んだ窓、Esc なら None。"""
    return pick_window_dialog(title, launch=launch, exclude=exclude, map=map, wrap=Window)


def api_pick(title=tr("窓を選ぶ"), slot=None, launch=True, exclude=(), rect=None):
    """layout -i と同じ小窓で、窓を 1 枚その場で選ぶ（先頭 ! でアプリを起動して、その窓）。取り消したら WinError。"""
    wc, rects, labels, index = _wc(), None, None, 0
    if rect is not None:                                  # まだ窓のない場所: いまの並びの地図に、その場所を足して強調する
        rects, labels = slot_map(wc)
        rects, labels = list(rects or []), list(labels or [])
        ax, ay, aw, ah = work_area(load_config())
        x, y, w_, h_ = rect
        rects.append(((x - ax) / aw, (y - ay) / ah, w_ / aw, h_ / ah))
        labels.append(tr("ここ"))
        index = len(rects) - 1
    if slot == 0:                                         # 0 は前面の窓: そのタイルを強調する（並びの外なら強調なし）
        slot = api_slot_of(api_focused())
    if slot is not None and rect is None:
        rects, labels = slot_map(wc)
        if rects is None or not 1 <= slot <= len(rects):
            raise WinError(tr("タイル {0} がありません（いまの並びのタイルは {1} 枚）").format(slot, len(rects or [])))
        index = slot - 1
    w = pick_window_map(wc, title, rects, index, labels, allow_launch=launch, exclude={x.id for x in exclude})
    if w is None:
        raise WinError(tr("選ぶのを取り消しました"))
    return Window(w)


def api_slot_of(w):
    """いまの並びで、w が何番目のタイルにあるか（1 から）。並びの中になければ None。"""
    cfg = load_config()
    cur = current_tiles(_wc(), cfg)
    if cur["tree"] is None:
        return None
    order = tile_order(cur, cfg)[1]
    return order.index(w.id) + 1 if w.id in order else None


def api_notify(text, title="win"):
    """デスクトップの通知を出す。"""
    subprocess.run(["notify-send", "-a", "win", title, str(text)], timeout=5)


class ExtCommand:
    """@command を付けた関数。引数は関数の宣言から読む。"""

    def __init__(self, fn, name):
        self.fn, self.name = fn, name
        self.group = None                                 # ショートカット画面のグループ（@command(group=…)）
        try:
            self.sig = inspect.signature(fn, eval_str=True)
        except Exception:                                 # 注釈が評価できなければ、文字列のまま
            self.sig = inspect.signature(fn)
        doc = inspect.getdoc(fn) or ""
        lines = doc.splitlines()
        self.summary = lines[0] if lines else ""
        self.doc = doc
        self.param_docs = {}                              # 説明文の「名前: 説明」の行
        for l in lines[1:]:
            m = re.match(r"\s*(\*{0,2}\w+)\s*[:：]\s*(.+)", l)
            if m and m.group(1).lstrip("*") in self.sig.parameters:
                self.param_docs[m.group(1).lstrip("*")] = m.group(2).strip()
        try:
            self.file, self.line = inspect.getsourcefile(fn), inspect.getsourcelines(fn)[1]
        except (OSError, TypeError):
            self.file, self.line = None, 0

    def parts(self):
        """入力欄の書式表示（SIGNATURES と同じ形）の部品。"""
        out = []
        for p in self.sig.parameters.values():
            desc = _param_desc(p, self.param_docs.get(p.name))
            if p.kind == p.VAR_POSITIONAL:
                out.append(("rep", p.name, desc, True))
            elif p.kind == p.KEYWORD_ONLY or p.annotation is bool:
                if p.annotation is bool:
                    out.append(("flag", "--" + p.name.replace("_", "-"), desc))
                else:
                    out.append(("opt", "--" + p.name.replace("_", "-"), p.name, desc))
            elif p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
                out.append(("pos", p.name, desc, p.default is not p.empty))
        return out

    def py_signature(self, code=False):
        """関数の宣言の形（例 swap(a: Window = "@left", b: Window = "@right")）。code なら既定値もコードどおり（sel("@left")）。"""
        bits = []
        for p in self.sig.parameters.values():
            t = "*" * (p.kind == p.VAR_POSITIONAL) + "**" * (p.kind == p.VAR_KEYWORD) + p.name
            if p.annotation is not p.empty:
                t += f": {_type_name(p.annotation)}"
            if p.default is not p.empty:
                t += f" = {_default_text(p.default, code)}"
            bits.append(t)
        return f"{self.name}({', '.join(bits)})"

    def usage(self):
        bits = []
        for part in self.parts():
            if part[0] == "pos":
                bits.append(f"[{part[1]}]" if part[3] else part[1])
            elif part[0] == "rep":
                bits.append(f"[{part[1]} …]")
            elif part[0] == "opt":
                bits.append(f"[{part[1]} {part[2]}]")
            else:
                bits.append(f"[{part[1]}]")
        return " ".join([f"win {self.name}"] + bits)

    def call(self, tokens):
        args, kwargs = self.bind(tokens)
        return self.fn(*args, **kwargs)

    def bind(self, tokens):
        """入力の語を、関数の引数に変換して割り当てる。"""
        params = self.sig.parameters
        named, positional, i = {}, [], 0
        while i < len(tokens):
            t = tokens[i]
            if t.startswith("--") and len(t) > 2:
                pname = t[2:].replace("-", "_")
                p = params.get(pname)
                if p is None or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                    raise WinError(tr("{0}: 知らないオプションです: {1}（書式: {2}）").format(self.name, t, self.usage()))
                if p.annotation is bool:
                    named[pname] = True
                else:
                    i += 1
                    if i >= len(tokens):
                        raise WinError(tr("{0}: {1} の値がありません").format(self.name, t))
                    named[pname] = _convert(p, tokens[i], self.name)
            else:
                positional.append(t)
            i += 1
        args = []
        for p in params.values():
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.name not in named:
                if positional:
                    args.append(_convert(p, positional.pop(0), self.name))
                elif p.default is not p.empty:
                    args.append(_default(p, self.name))
                else:
                    raise WinError(tr("{0}: {1} がありません（書式: {2}）").format(self.name, p.name, self.usage()))
            elif p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
                args.append(named.pop(p.name))
            elif p.kind == p.VAR_POSITIONAL:
                args += [_convert(p, t, self.name) for t in positional]
                positional = []
            elif p.kind == p.KEYWORD_ONLY and p.name not in named:
                if p.default is p.empty:
                    raise WinError(tr("{0}: --{1} がありません（書式: {2}）").format(self.name, p.name, self.usage()))
                named[p.name] = _default(p, self.name)
        if positional:
            raise WinError(tr("{0}: 引数が多すぎます: {1}（書式: {2}）").format(self.name, ' '.join(positional), self.usage()))
        return args, named


_TYPE_LABELS = {Window: tr("窓"), int: tr("整数"), float: tr("数"), str: tr("文字列"), bool: tr("オン/オフ")}


def is_window_ann(ann):
    """引数の注釈が窓か（Window、または Window | None）。"""
    return ann is Window or (typing.get_origin(ann) in (typing.Union, types.UnionType) and Window in typing.get_args(ann))


def _type_name(ann):
    if typing.get_origin(ann) in (typing.Union, types.UnionType):
        return " | ".join("None" if a is type(None) else _type_name(a) for a in typing.get_args(ann))
    return ann if isinstance(ann, str) else getattr(ann, "__name__", None) or str(ann)


def _default_text(v, code=False):
    if isinstance(v, _Sel):
        spec = json.dumps(v.spec, ensure_ascii=False)
        return f"sel({spec})" if code else spec
    return repr(v)


def _param_desc(p, doc):
    """引数の説明: 宣言の形（名前: 型 = 既定値）と、説明文に書いた説明。"""
    t = p.name + (f": {_type_name(p.annotation)}" if p.annotation is not p.empty else "")
    if p.default is not p.empty:
        t += f" = {_default_text(p.default)}"
    return f"{t}　{doc}" if doc else t


def _convert(p, text, cmd):
    ann = p.annotation
    try:
        if is_window_ann(ann) and int in typing.get_args(ann) and text.isdigit():
            return int(text)                              # int | Window: 数字なら整数（タイルの番号など）、ほかは窓
        if is_window_ann(ann):
            return api_at(text)
        if ann is int:
            return int(text)
        if ann is float:
            return float(text)
        if ann is bool:
            return text.lower() in ("1", "true", "yes", "on")
    except ValueError:
        raise WinError(tr("{0}: {1} は{2}で書いてください: {3}").format(cmd, p.name, _TYPE_LABELS.get(ann, '値'), text))
    return text


def _default(p, cmd):
    if is_window_ann(p.annotation) and isinstance(p.default, (str, _Sel)):     # 既定値が窓の指定（sel("@left") など）なら、呼ぶときに窓にする
        return api_at(p.default.spec if isinstance(p.default, _Sel) else p.default)
    return p.default


def api_command(fn=None, *, name=None, group=None):
    """関数を win の命令として登録する印（@command、または @command(name="別名", group="グループ名")）。"""
    def register(f):
        n = name or f.__name__
        if n in builtin_commands():
            EXT_ERRORS.append((inspect.getsourcefile(f) or "?", tr("「{0}」は win の組み込みの命令と同じ名前なので、使えません").format(n)))
        else:
            EXT[n] = ExtCommand(f, n)
            EXT[n].group = group
        return f
    return register(fn) if fn is not None else register


def make_winapi():
    m = types.ModuleType("winapi", tr("win の拡張用の関数群。"))
    for k, v in {"command": api_command, "at": api_at, "find": api_find, "windows": api_windows, "focused": api_focused,
                 "area": api_area, "run": api_run, "notify": api_notify, "sel": api_sel,
                 "layout": api_layout, "apply_set": api_apply_set, "run_command": api_run_command, "nav": api_nav,
                 "launch": api_launch, "layouts": api_layouts, "browse": api_browse, "term": api_term, "pick": api_pick, "slot_of": api_slot_of,
                 "tiles": api_tiles, "slots": api_slots, "Item": Item, "Map": Map, "Event": Event, "Dialog": ApiDialog, "stack": api_stack, "cycle": api_cycle, "desktops": desktops, "switch_desktop": api_switch_desktop,
                 "Group": Group, "groups": api_groups, "group": api_group, "group_of": api_group_of,
                 "choose": choose, "confirm": confirm, "ask": ask, "pick_tile": pick_tile, "pick_window": api_pick_window,
                 "window_items": api_window_items, "resolve": api_resolve, "Window": Window, "WinError": WinError}.items():
        setattr(m, k, v)
    return m


WINAPI_STUB = tr('''\"\"\"win の拡張用の関数群（型の定義）。win が書き出すファイルなので、編集しても上書きされます。

拡張は、このディレクトリに .py を置いて書きます。@command を付けた関数が win の命令になり、
win prompt・`win 名前`・ショートカット・登録したコマンドから呼べます。
\"\"\"
from typing import Callable, Iterator, TypeVar, overload

_F = TypeVar("_F", bound=Callable[..., object])


class WinError(Exception):
    \"\"\"win の失敗。raise WinError("説明") で命令を止めると、説明が入力欄や通知に出る。\"\"\"


class Window:
    \"\"\"窓 1 枚。at()・find()・windows()・focused() などで手に入る。\"\"\"
    @property
    def id(self) -> int:
        \"\"\"窓の ID（窓の指定の文字列としても使える）。\"\"\"
    @property
    def cls(self) -> str:
        \"\"\"クラス名（例 firefox、org.gnome.Ptyxis）。\"\"\"
    @property
    def title(self) -> str:
        \"\"\"題名。\"\"\"
    @property
    def desktop(self) -> int:
        \"\"\"この窓があるデスクトップの番号（1 から）。代入すると、その窓をそのデスクトップへ移す（Window Calls だけで動く）。\"\"\"
    @desktop.setter
    def desktop(self, n: int) -> None: ...
    @property
    def rect(self) -> tuple[int, int, int, int]:
        \"\"\"位置と大きさ (x, y, 幅, 高さ)。代入すると窓が動く（最大化は解く）。例 w.rect = (0, 32, 960, 1048)\"\"\"
    @rect.setter
    def rect(self, r: tuple[int, int, int, int]) -> None: ...
    @property
    def maximized(self) -> bool:
        \"\"\"最大化しているか。\"\"\"
    @property
    def minimized(self) -> bool:
        \"\"\"最小化しているか。\"\"\"
    def move(self, x: int, y: int) -> None:
        \"\"\"左上を (x, y) に動かす（大きさはそのまま）。\"\"\"
    def resize(self, width: int, height: int) -> None:
        \"\"\"大きさを変える（左上はそのまま）。\"\"\"
    def focus(self) -> None:
        \"\"\"前面に出す（最小化していれば戻す）。\"\"\"
    def max(self) -> None:
        \"\"\"最大化する。\"\"\"
    def unmax(self) -> None:
        \"\"\"最大化を戻す。\"\"\"
    def min(self) -> None:
        \"\"\"最小化する。\"\"\"
    def unmin(self) -> None:
        \"\"\"最小化を戻す。\"\"\"
    def above(self) -> None:
        \"\"\"常に手前にする。\"\"\"
    def unabove(self) -> None:
        \"\"\"常に手前をやめる。\"\"\"
    def close(self) -> None:
        \"\"\"閉じる。\"\"\"


@overload
def command(fn: _F) -> _F: ...
@overload
def command(*, name: str | None = None, group: str | None = None) -> Callable[[_F], _F]: ...
def command(fn=None, *, name=None, group=None):
    \"\"\"関数を win の命令にする印。引数の型の注釈（Window・int・float・str・bool）で、打った語を変換する。

    group を書くと、設定のショートカット画面でその目的別のグループに入る（"窓を選ぶ・移る"・"窓を並べる・置く"・
    "保存した並び（セット）"・"コマンド"・"その他の操作"。省くと「その他の操作」）。
    Window の引数には、クラス・題名の一部、ID、@left・@prev などを打てる。既定値に sel("@left") と
    書くと、省いたときにその窓になる。bool の引数は --名前 で True。
    int | Window にすると、数字は整数（例 タイルの番号 → at(f"@slot:{n}")）、ほかは窓として受け取る。
    説明文の 1 行目が一覧に出る説明、「引数名: 説明」の行が引数の説明になる。
    \"\"\"
def sel(spec: str) -> Window:
    \"\"\"命令の引数の既定値に書く窓の指定（例 def swap(a: Window = sel("@left")): …）。呼ばれたときに窓にする。\"\"\"

def at(sel: str) -> Window:
    \"\"\"窓の指定（クラス・題名の一部、ID、@left・@prev・@largest・@slot:1・@monitor:primary など）に当たる窓 1 枚。なければ WinError。
    タイルの番号 n なら at(f"@slot:{n}")（0 は前面の窓）。\"\"\"
def find(sel: str) -> list[Window]:
    \"\"\"窓の指定に当たる窓すべて（前面に近い順）。@visible・@others・@all・@class:firefox は複数の窓に当たる。なければ空。\"\"\"
def focused() -> Window:
    \"\"\"前面の窓。\"\"\"
def windows() -> list[Window]:
    \"\"\"今のワークスペースで最小化されていない窓（前面に近い順）。\"\"\"
def slot_of(w: Window) -> int | None:
    \"\"\"いまの並び（窓の位置から逆算）で、w が何番目のタイルにあるか（1 から。@slot:n の n）。並びの中になければ None。
    （@slot:0 は前面の窓を指すが、slot_of は 0 を返さない）\"\"\"
def slots() -> list[Window]:
    \"\"\"いまの並び（窓の位置から逆算）の窓を、番号順に（slots()[0] が @slot:1）。\"\"\"
def resolve(spec: str) -> Window | None:
    \"\"\"layout の窓の列と同じ書き方を窓にする。- は None（空ける）、!コマンド は起動した窓、
    クラス名? はその窓（なければ起動）、ほかは at() と同じ。\"\"\"
def pick(title: str = "窓を選ぶ", slot: int | None = None, launch: bool = True, exclude: list[Window] = [],
         rect: tuple[int, int, int, int] | None = None) -> Window:
    \"\"\"layout -i と同じ小窓で、窓をその場で選ぶ（先頭 ! でアプリを起動して、その窓）。取り消したら WinError。
    小窓の地図にはいまの並びが出る。slot=n なら n 番目のタイルを強調する。launch=False なら起動はさせない。
    exclude の窓は一覧に出さない（2 つめを選ぶときに 1 つめを除く、など）。rect を渡すと、
    まだ窓のない場所（分けたばかりのタイルなど）を地図に足して強調する。引数を省いたら選ばせる例:
    def place(n: int, w: Window | None = None): w = w or pick(f"タイル {n} に置く窓", slot=n)\"\"\"

class Item:
    \"\"\"一覧の 1 行。value は選ばれたときに返ってくる値（任意）。\"\"\"
    label: str
    sub: str
    icon: str
    value: object
    def __init__(self, label: str, sub: str = "", icon: str = "", value: object = None) -> None: ...

class Map:
    \"\"\"ミニ地図。rects は作業領域に対する割合の (x, y, 幅, 高さ) のリスト（tiles() の結果を、作業領域で割った値）。
    labels は各タイルの文字、current は強調するタイルの添字（-1 で強調なし）、free は点線にするタイルの真偽のリスト、
    monitor は、その作業領域があるモニタの添字（複数のモニタを並べて描くとき）。\"\"\"
    rects: list[tuple[float, float, float, float]]
    labels: list[str] | None
    current: int
    free: list[bool] | None
    monitor: int | None
    def __init__(self, rects: list[tuple[float, float, float, float]], labels: list[str] | None = None, current: int = -1,
                 free: list[bool] | None = None, monitor: int | None = None) -> None: ...

class Event:
    \"\"\"Dialog から返ってくる出来事。kind は "select"（行を決めた。item・index・via="enter" か "tab"）・"key"（key）・"text"（text）・
    "highlight"（選択が動いた。item・index。highlight=True のとき）・"launched"（! でアプリを起動した。window がその窓）・"cancel"。\"\"\"
    kind: str
    item: Item | None
    index: int | None
    via: str | None
    key: str | None
    text: str | None
    window: Window | None

class Dialog:
    \"\"\"対話型の小窓。with で開き、events() で出来事を 1 つずつ受け取り、出来事に応じて行・地図・通知を更新する（小窓は描画だけ、状態は拡張が持つ）。
    出来事を受け取ったあと、次を待つ前に、更新した内容が小窓へ渡る。キーは keys に挙げたものだけが "key" の出来事になる。例（地図の上で置き先を選ぶ）:
    with Dialog("置き先を選ぶ", entry=False, keys=("Left", "Right")) as d:
        d.rows([Item("ここに決める")]); d.map(Map(rects, current=i))
        for ev in d.events():
            if ev.kind == "key": i += 1 if ev.key == "Right" else -1; d.map(Map(rects, current=i))
            elif ev.kind == "select": return i
            elif ev.kind == "cancel": return None\"\"\"
    title: str
    hint: str
    placeholder: str
    def __init__(self, title: str = "", *, hint: str = "", placeholder: str = "文字で絞り込み", filter: bool = True,
                 entry: bool = True, ask: bool = False, show_list: bool = True, launch: bool = False, highlight: bool = False,
                 keys: tuple[str, ...] = (), keep_selection: bool = False, empty: str = "", chip: str = "", window_title: str = "win", vim: bool = False,
                 numbers: bool = False) -> None:
        \"\"\"title: 題名。hint: 下の案内文。placeholder: 入力欄の説明。filter: 入力で行を絞り込む。entry: 入力欄を出す。
        ask: 文字を入力する画面（Enter で "text" の出来事）。show_list: 行の一覧を出す。launch: 先頭 ! でアプリを起動できる（"launched"）。
        highlight: 選択が動くたびに "highlight" の出来事を返す。keys: 受け取りたいキー（"Left"・"Right"・"Up"・"Down"・"Ctrl+s" など）。
        keep_selection: 出来事のあと、選択中の行の位置を保つ。empty: 行が 1 つもないときの文。chip: 入力欄の左の印。
        window_title: 小窓の上の題名。vim: 入力欄のない一覧のキー（j/k・g/G・l で決定・h/q で取消・1〜9 で直接）を使う。
        numbers: 先頭の 9 行に番号を付ける（vim の 1〜9 と組み合わせる）。\"\"\"
    def rows(self, items: list[Item]) -> None:
        \"\"\"一覧の行を差し替える。\"\"\"
    def map(self, m: Map | None) -> None:
        \"\"\"ミニ地図を差し替える（None で隠す）。\"\"\"
    def notice(self, text: str) -> None:
        \"\"\"赤字の通知を出す（"" で消す）。\"\"\"
    def keys(self, *names: str) -> None:
        \"\"\"親へ渡してほしいキーを差し替える。\"\"\"
    def text(self, value: str) -> None:
        \"\"\"入力欄の文字を置き換える（次に小窓へ渡すとき 1 回だけ）。\"\"\"
    def events(self) -> Iterator[Event]:
        \"\"\"小窓を開いて、出来事を 1 つずつ返す。取り消す（Esc）と "cancel" の出来事を返して終わる。\"\"\"
    def __enter__(self) -> Dialog: ...
    def __exit__(self, *exc: object) -> bool: ...

def window_items(exclude: list[Window] = []) -> list[Item]:
    \"\"\"今のワークスペースで最小化されていない窓を、一覧の行にする（前面に近い順。value は Window）。exclude の窓は除く。\"\"\"
def choose(title: str, items: list[Item], *, preview: Callable[[Item], Map] | None = None, placeholder: str = "文字で絞り込み",
           hint: str = "", filter: bool = True) -> Item | None:
    \"\"\"一覧から 1 つ選ぶ。選んだ Item、Esc なら None。preview(item) -> Map を渡すと、選択が動くたびにミニ地図を出す。
    例 x = choose("型を選ぶ", [Item(n, e) for n, e in layouts().items()])\"\"\"
def confirm(title: str, text: str = "", *, yes: str = "はい", no: str = "いいえ") -> bool:
    \"\"\"はい・いいえを選ぶ。はいなら True（Esc は False）。\"\"\"
def ask(title: str, *, placeholder: str = "", initial: str = "", hint: str = "") -> str | None:
    \"\"\"1 行の文字を入力する。入力した文字、Esc なら None。\"\"\"
def pick_tile(title: str, rects: list[tuple[float, float, float, float]], *, labels: list[str] | None = None, current: int = 0,
              free: list[bool] | None = None, monitor: int | None = None) -> int | None:
    \"\"\"ミニ地図の上でタイルを選ぶ（矢印キーで、その向きの隣のタイルへ）。選んだタイルの添字、Esc なら None。\"\"\"
def pick_window(title: str = "窓を選ぶ", *, launch: bool = True, exclude: list[Window] = [], map: Map | None = None) -> Window | None:
    \"\"\"窓を 1 枚選ぶ（launch なら、先頭 ! でアプリを起動してその窓）。選んだ窓、Esc なら None（pick と違い、例外にしない）。
    map を渡すと、ミニ地図も出す。\"\"\"

def stack(n: int = 0) -> list[Window]:
    \"\"\"n 番目のタイル（0 は前面の窓のいるタイル）に重なっている窓（層）を、巡回の順（ID の昇順）に返す。同じ位置（枠の 4 辺が 8px 以内）にある、
    最小化されていない窓が層。手前の層は、重なり順がいちばん上のもの。層が 1 枚だけなら、要素 1 つのリスト。\"\"\"
def cycle(n: int = 0, d: int = 1) -> Window:
    \"\"\"n 番目のタイルの重なりで、いま手前の層から d 層（負なら前へ）ずらした窓を前面に出して返す。層は一巡する。重なりがなければ WinError。
    例 cycle(0)  # 前面の窓のいるタイルで、次の層を表示する\"\"\"
class Group:
    \"\"\"窓のグループ（名前つき・保存つき。~/.local/state/win/groups.json）。メンバーは 1 つの枠を共有し、タブのように切り替わる。
    1 つの窓は高々 1 つのグループに入る。閉じた窓は、自動でメンバーから外れる。例（手前の窓のグループを次のメンバーへ）:
    g = group_of(focused())
    if g: g.next()\"\"\"
    name: str
    @property
    def members(self) -> list[Window]:
        \"\"\"メンバー（巡回の順）。\"\"\"
    @property
    def active(self) -> Window | None:
        \"\"\"いま手前のメンバー。\"\"\"
    @property
    def rect(self) -> tuple[int, int, int, int]:
        \"\"\"グループの枠。手前のメンバーがいまいる枠（動かしたものに追従する）。\"\"\"
    def add(self, *windows: Window) -> None:
        \"\"\"窓を足し、グループの枠へ置いて、最後に足した窓を手前にする。ほかのグループにいた窓は移る。\"\"\"
    def remove(self, *windows: Window) -> None:
        \"\"\"窓をグループから外す。\"\"\"
    def delete(self) -> None:
        \"\"\"グループを消す（窓は閉じない）。\"\"\"
    def next(self, d: int = 1) -> Window:
        \"\"\"いま手前のメンバーから d 個（負なら前へ）ずれたメンバーを、グループの枠へ置いて前面に出して返す。メンバーは一巡する。\"\"\"
    def show(self) -> None:
        \"\"\"全メンバーをグループの枠へ置き（別のデスクトップ・最小化も今のデスクトップへ戻す）、手前のメンバーを前面に出す。\"\"\"
    def place(self, rect: tuple[int, int, int, int]) -> None:
        \"\"\"グループの枠を rect に変えて、全メンバーをそこへ置く。\"\"\"

def groups() -> list[Group]:
    \"\"\"いまあるグループすべて。\"\"\"
def group(name: str, *windows: Window) -> Group:
    \"\"\"name のグループ。windows を渡すと、その窓で新しく作る（すでにあれば足す）。なければ WinError。
    例 group("作業", at("firefox"), at("ptyxis")).show()\"\"\"
def group_of(w: Window) -> Group | None:
    \"\"\"窓 w の属するグループ。どこにも属さなければ None。\"\"\"
def desktops() -> tuple[int, int]:
    \"\"\"(いまのデスクトップの番号, デスクトップの数)。番号は 1 から。数は、動的ワークスペースでは末尾の空のものを含む。
    拡張 win-helper@local が要る（なければ WinError）。\"\"\"
def switch_desktop(n: int, relative: bool = False) -> None:
    \"\"\"n 番目（1 から）のデスクトップへ切り替える。relative=True なら、いまから n 個（負なら前へ）ずれたデスクトップへ。
    なければ WinError。拡張 win-helper@local が要る。\"\"\"
def layout(expr: str, *windows: Window | str, gap: int | None = None) -> None:
    \"\"\"型 expr（名前か式。例 "lr"・"v(1,2)"・"1,2:1/1"）のタイルに、windows を順に並べる。窓の指定の文字列も書ける。
    例 layout("v(1,1)", focused(), at("@prev"))\"\"\"
def tiles(expr: str, rect: tuple[int, int, int, int] | None = None) -> list[tuple[int, int, int, int]]:
    \"\"\"rect（省くと area()）を型 expr で分けた、各タイルの (x, y, 幅, 高さ)。タイルの間には設定の隙間を取る。
    例 tiles("1/1", w.rect) は w の場所を上下に分けた 2 つ\"\"\"
def layouts() -> dict[str, str]:
    \"\"\"型の一覧 {名前: 式}。\"\"\"
def area() -> tuple[int, int, int, int]:
    \"\"\"窓を置ける領域 (x, y, 幅, 高さ)。基準のモニタ（前面の窓があるモニタ）から余白を除いたもの。\"\"\"
def nav(direction: str) -> None:
    \"\"\""next"・"prev"（いまの並びの番号順）か "left"・"right"・"up"・"down" の向きの窓へフォーカスを移す。\"\"\"

def apply_set(name: str) -> None:
    \"\"\"保存したセットを適用する（win set 名前 と同じ）。\"\"\"
def run_command(name: str) -> None:
    \"\"\"登録したコマンドを実行する（win run 名前 と同じ）。拡張の命令は、Python の関数として import して呼ぶ。\"\"\"
def run(line: str) -> None:
    \"\"\"win の命令を文字列で実行する（例 run("max -w @prev")）。複数行なら上から順に。失敗したら WinError。\"\"\"

def launch(cmdline: str, timeout: float = 20) -> Window:
    \"\"\"コマンドを起動し、新しく出た窓を返す（例 launch("gnome-text-editor")）。出なければ WinError。\"\"\"
def browse(*urls: str) -> None:
    \"\"\"Firefox を新しい窓で開き、URL をタブとして並べる。\"\"\"
def term(*dirs: str) -> None:
    \"\"\"端末（Ptyxis）を、作業ディレクトリごとのタブつきで新しく開く。\"\"\"
def notify(text: str, title: str = "win") -> None:
    \"\"\"デスクトップの通知を出す。\"\"\"
''')


EXT_TEMPLATE = tr('''# win の拡張。@command を付けた関数が win の命令になる（win 名前・入力欄の補完・ショートカットで呼べる）。
#   使える関数の一覧:   win help api   （宣言と説明の全文は同じフォルダの winapi.pyi）
#   引数の型:           Window・int・float・str・bool（打った語をこの型に変換する。bool は --名前 で True）
#   窓の引数の既定値:   sel("@focused")・sel("@left")・sel("@prev") など
#   説明文:             1 行目が一覧に出る説明。「引数名: 説明」の行が引数の説明になる
#   nvim では:          \\wh 書き方と関数の一覧・K カーソル位置の名前の説明・:WinHelp 名前
#   保存した後、設定画面の「再読み込み」で一覧に出る。端末なら win help ですぐ確かめられる。
from winapi import Window, command, sel


@command
def {name}(w: Window = sel("@focused")):
    """（ここに 1 行の説明。入力欄の候補と win help に出ます）
    w: 対象の窓（省くと前面の窓）
    """
    ...
''')


PYRIGHT_CONFIG = '{\n  "reportMissingModuleSource": false,\n  "reportCallInDefaultInitializer": false\n}\n'


def write_ext_support():
    """拡張のディレクトリに、型の定義（winapi.pyi）と basedpyright の設定を置く（中身が違うときだけ書く）。"""
    for fname, text in (("winapi.pyi", WINAPI_STUB), ("pyrightconfig.json", PYRIGHT_CONFIG)):
        path = os.path.join(EXT_DIR, fname)
        try:
            with open(path, encoding="utf-8") as f:
                if f.read() == text:
                    continue
        except FileNotFoundError:
            pass
        except OSError:
            continue
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass


def load_extensions():
    """拡張を 1 回だけ読み込む。読めないファイルは飛ばして EXT_ERRORS に記録する（win 本体は動かし続ける）。"""
    if _EXT_STATE["loaded"]:
        return
    _EXT_STATE["loaded"] = True
    sys.modules["winapi"] = make_winapi()
    if not os.path.isdir(EXT_DIR):
        return
    write_ext_support()
    if EXT_DIR not in sys.path:
        sys.path.append(EXT_DIR)                          # 標準の部品を先に探す（同じ名前のファイルで win 本体が壊れないように）
    sys.dont_write_bytecode = True                        # 拡張のディレクトリに __pycache__ を作らない
    for path in sorted(glob.glob(os.path.join(EXT_DIR, "*.py"))):
        stem = os.path.splitext(os.path.basename(path))[0]
        try:
            mod = importlib.import_module(stem)
            _EXT_STATE["mods"].append(stem)
            if os.path.abspath(getattr(mod, "__file__", "") or "") != os.path.abspath(path):
                EXT_ERRORS.append((path, tr("「{0}」は Python の標準などの部品と同じ名前なので、読み込めません（名前を変えてください）").format(stem)))
        except Exception as e:
            EXT_ERRORS.append((path, ext_error_text(e)))


def reload_extensions():
    """拡張を読み直す（開いたままの設定窓で、ファイルを書き換えた後に使う）。"""
    for stem in _EXT_STATE["mods"]:
        sys.modules.pop(stem, None)
    for n in EXT:
        SIGNATURES.pop(n, None)
    EXT.clear()
    EXT_ERRORS.clear()
    _EXT_STATE.update(loaded=False, mods=[])
    load_extensions()
    SIGNATURES.update(ext_signatures())


def ext_error_text(e):
    """例外を、拡張のどの行で起きたかが分かる短い説明にする。"""
    if isinstance(e, SyntaxError):
        return tr("{0}:{1}: 文法エラー: {2}").format(os.path.basename(e.filename or ''), e.lineno, e.msg)
    frames = [f for f in traceback.extract_tb(e.__traceback__) if f.filename.startswith(EXT_DIR)]
    where = f"{os.path.basename(frames[-1].filename)}:{frames[-1].lineno}: " if frames else ""
    return f"{where}{type(e).__name__}: {e}"


def _error_line(msg):
    m = re.match(r"[^:]+:(\d+):", msg)
    return int(m.group(1)) if m else 1


def run_ext(name, tokens):
    """拡張の命令を実行する。関数の中の失敗は、どの行かを添えた WinError にする。"""
    cmd = EXT[name]
    try:
        cmd.call(tokens)
    except WinError:
        raise
    except Exception as e:
        raise WinError(f"{name}: {ext_error_text(e)}")
    return 0


@functools.cache
def builtin_commands():
    from .cli import build_parser        # 逆向きの依存: 循環インポートを避けて、使うときに読み込む
    return set(build_parser()[1].choices)


def ext_spec():
    """入力欄（別プロセス）に渡す、拡張の命令の情報。"""
    load_extensions()
    info = {}
    for n, c in EXT.items():
        ps = list(c.sig.parameters.values())
        info[n] = {"summary": c.py_signature(),
                   "win": [is_window_ann(p.annotation) for p in ps if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)],
                   "rep": any(p.kind == p.VAR_POSITIONAL and is_window_ann(p.annotation) for p in ps)}
    return {"ext": info, "ext_sig": ext_signatures(), "ext_errors": [f"{os.path.basename(f)}: {m}" for f, m in EXT_ERRORS]}


def ext_signatures():
    """拡張の命令の書式（SIGNATURES と同じ形）。"""
    return {n: (c.parts(), c.py_signature() + (f"　{c.summary}" if c.summary else "")) for n, c in EXT.items()}


def api_entries():
    """winapi.pyi の宣言から {名前: (宣言の 1 行, 説明文の全文)}。Window の属性は "rect" と "Window.rect" の両方で引ける。"""
    import ast
    out = {}
    for node in ast.parse(WINAPI_STUB).body:
        if isinstance(node, ast.FunctionDef) and not any(isinstance(d, ast.Name) and d.id == "overload" for d in node.decorator_list):
            ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
            out[node.name] = (f"{node.name}({ast.unparse(node.args)}){ret}", ast.get_docstring(node) or "")
        elif isinstance(node, ast.ClassDef):
            init = next((m for m in node.body if isinstance(m, ast.FunctionDef) and m.name == "__init__"), None)
            if init is not None:                              # 作り方（引数と説明）も、クラスの説明に添える
                head = f"class {node.name}({ast.unparse(init.args)})".replace("(self, ", "(").replace("(self)", "()")
                out[node.name] = (head, "\n".join(x for x in (ast.get_docstring(node), ast.get_docstring(init)) if x))
            else:
                out[node.name] = (f"class {node.name}", ast.get_docstring(node) or "")
            for m in node.body:
                if isinstance(m, ast.FunctionDef) and not m.name.startswith("__") \
                        and not any(ast.unparse(d).endswith(".setter") for d in m.decorator_list):
                    prop = any(ast.unparse(d) == "property" for d in m.decorator_list)
                    head = f"{node.name}.{m.name}: {ast.unparse(m.returns)}" if prop else \
                        f"{node.name}.{m.name}({ast.unparse(m.args)}) -> {ast.unparse(m.returns)}".replace("(self)", "()").replace("(self, ", "(")
                    entry = (head, ast.get_docstring(m) or "")
                    out[f"{node.name}.{m.name}"] = entry
                    out.setdefault(m.name, entry)
    out["command"] = (tr('@command　または　@command(name="別名")'), out.get("command", ("", ""))[1])
    return out


def help_names(py=False):
    """win help に渡せる名前すべて（エディタの補完用）。py なら拡張を書くときの名前（winapi・拡張の命令・@ の指定）だけ。"""
    load_extensions()
    if py:
        return list(dict.fromkeys(list(api_entries()) + list(EXT) + [s for s, _ in AT_SELECTORS]))
    names = ["api", "commands", "sets", "layouts"] + list(SIGNATURES) + list(EXT) + list(api_entries())
    names += [s for s, _ in AT_SELECTORS] + list(load_commands()) + list(load_sets())
    return list(dict.fromkeys(names))


API_SECTIONS = [
    (tr("命令を作る"), ["command", "sel", "WinError"]),
    (tr("窓を探す・選ぶ（Window を返す）"), ["at", "find", "focused", "windows", "slots", "slot_of", "resolve", "pick"]),
    (tr("窓 1 枚の情報と操作（w は at() などで得た Window）"), ["Window.*"]),
    (tr("並べる・フォーカスを移す"), ["layout", "layouts", "tiles", "area", "nav"]),
    (tr("登録したもの・win の命令を呼ぶ"), ["apply_set", "run_command", "run"]),
    (tr("起動・通知"), ["launch", "browse", "term", "notify"]),
    (tr("重なった窓（層）"), ["stack", "cycle"]),
    (tr("デスクトップ（ワークスペース）"), ["desktops", "switch_desktop", "Window.desktop"]),
    (tr("窓のグループ（名前つき・保存つき）"), ["groups", "group", "group_of", "Group", "Group.members", "Group.active", "Group.rect", "Group.add",
                              "Group.remove", "Group.delete", "Group.next", "Group.show", "Group.place"]),
    (tr("対話型の小窓（1 回で選ぶ）"), ["choose", "confirm", "ask", "pick_tile", "pick_window", "window_items", "Item", "Map"]),
    (tr("対話型の小窓（やり取りを回す）"), ["Dialog", "Dialog.rows", "Dialog.map", "Dialog.notice", "Dialog.keys", "Dialog.text", "Dialog.events", "Event"]),
]


API_EXAMPLE = tr('''from winapi import Window, command, sel, layout, focused, find


@command
def pair(other: Window = sel("@prev")):
    """前面の窓と other を左右に並べる
    other: 右に置く窓（省くと直前の窓）
    """
    layout("lr", focused(), other)


@command
def minall():
    """前面以外の窓をすべて最小化する"""
    for w in find("@others"):
        w.min()''')


def print_api():
    """拡張を書くための一覧（winapi.pyi の宣言と説明文から作る）。"""
    api = api_entries()
    print(tr("win の拡張（Python）で使えるもの。from winapi import 名前 で使う。定義の全文: {0}").format(os.path.join(EXT_DIR, 'winapi.pyi')))
    print(tr("  ・@command を付けた関数が win の命令になる（win 名前・入力欄・ショートカット・登録したコマンドで呼べる）"))
    print(tr("  ・引数の型の注釈（Window・int・float・str・bool）で、打った語を変換する。窓の既定値は sel(\"@left\") のように書く"))
    print(tr("  ・int | Window にすると、数字は整数（タイルの番号など）、ほかは窓として受け取る"))
    print(tr("  ・省いたらその場で選ばせるには、既定値を sel(\"@pick\") にするか、Window | None にして pick() を呼ぶ"))
    print(tr("  ・説明文の 1 行目が一覧に出る説明。「引数名: 説明」の行が引数の説明"))
    print(tr("  ・ほかの拡張の関数は、ふつうに import して呼べる（例 from swap import exchange）"))
    for title, names in API_SECTIONS:
        print(f"\n■ {title}")
        if names == ["Window.*"]:
            names = [k for k in api if k.startswith("Window.")]
        for n in names:
            head, doc = api[n]
            print(f"  {head.replace('Window.', 'w.') if n.startswith('Window.') else head}")
            for l in doc.splitlines()[:2]:
                if l.strip():
                    print(f"      {l.strip()}")
    print(tr("\n■ 窓の指定（at・find・sel・layout に書く文字列）"))
    print(tr("  クラス・題名の一部（例 \"firefox\"）、ID、または:"))
    for sname, d in AT_SELECTORS:
        print(f"  {sname:<10} {d}")
    print(tr("\n■ 例"))
    print("\n".join("  " + l for l in API_EXAMPLE.splitlines()))
    return 0


def cmd_help(args):
    load_extensions()
    if args.names:
        print("\n".join(help_names(args.py)))
        return 0
    if args.py and args.name:                             # 拡張を書いているとき: Python の名前を先に引く
        api = api_entries()
        if args.name in api:
            head, doc = api[args.name]
            print(head)
            print("\n".join("  " + l for l in doc.splitlines()) or tr("  （説明なし）"))
            return 0
        if args.name in EXT:
            c = EXT[args.name]
            print(tr("def {0}　（拡張の命令。{1}:{2}）").format(c.py_signature(code=True), c.file, c.line))
            print("\n".join("  " + l for l in (c.doc or tr("（説明なし）")).splitlines()))
            print(tr("  ほかの拡張からは from {0} import {1} で呼べる").format(os.path.splitext(os.path.basename(c.file or 'x'))[0], c.fn.__name__))
            return 0
    if args.py and not args.name:
        return print_api()
    if args.name:
        n = args.name
        if n == "api":
            return print_api()
        api = api_entries()
        if n in api and n not in EXT and n not in SIGNATURES:
            head, doc = api[n]
            print(f"winapi: {head}")
            print("\n".join("  " + l for l in doc.splitlines()) or tr("  （説明なし）"))
            print(tr("（一覧は win help api、定義は {0}）").format(os.path.join(EXT_DIR, 'winapi.pyi')))
            return 0
        cmds, sets, layouts = load_commands(), load_sets(), load_config()["layouts"]
        if n == "commands":
            print(tr("登録したコマンド（{0}。win run 名前 で実行、中身は win help 名前）").format(COMMANDS))
            for k, c in cmds.items():
                print(f"  {k:<14} {c.get('type', 'win'):<6} {describe_command(c)}")
            if not cmds:
                print(tr("  （まだありません）"))
            return 0
        if n == "sets":
            print(tr("セット（{0}。win set 名前 で適用、中身は win help 名前）").format(SETS))
            for k, c in sets.items():
                print(f"  {k:<14} {set_summary(c)}")
            if not sets:
                print(tr("  （まだありません）"))
            return 0
        if n == "layouts":
            print(tr("型（{0} と組み込み。layout 名前 で使う。式を直接書いてもよい）").format(CONFIG))
            for k, e in layouts.items():
                print(f"  {k:<10} {e}")
            return 0
        if n in cmds or n in sets:
            for kind, pool, how in ((tr("コマンド"), cmds, "win run"), (tr("セット"), sets, "win set")):
                if n in pool:
                    c = pool[n]
                    print(f"{kind}「{n}」（{how} {shlex.quote(n)}）")
                    body = c.get("run", "") if c.get("type") != "arrange" else set_summary(c)
                    print("\n".join("  " + l for l in body.splitlines()))
            return 0
        if n in EXT:
            c = EXT[n]
            print(c.usage())
            print(f"def {c.py_signature()}")
            print(c.doc or tr("（説明なし）"))
            for part in c.parts():
                print(f"  {part[-1] if part[0] != 'pos' else part[2]}")
            if c.file:
                print(tr("定義: {0}:{1}").format(c.file, c.line))
            return 0
        if n in SIGNATURES:
            parts, summary = SIGNATURES[n]
            print(f"win {n}　{summary}")
            for part in parts:
                print(f"  {part[1]}　{part[3] if part[0] == 'opt' else part[2]}")
            return 0
        if n.startswith("@"):
            for s, d in AT_SELECTORS:
                if n.startswith(s.rstrip(":")):
                    print(f"{s}　{d}")
            return 0
        raise WinError(tr("知らない命令・名前です: {0}（一覧は win help）").format(n))
    print(tr("組み込みの命令（詳しくは win help 名前）"))
    for n, (_p, summary) in SIGNATURES.items():
        print(f"  {n:<10} {summary}")
    if EXT:
        print(tr("\n拡張の命令（{0}。詳しくは win help 名前、拡張で使える関数は win help api）").format(EXT_DIR))
        for n, c in EXT.items():
            print(f"  {c.py_signature()}　{c.summary}")
    print(tr("\nほかの一覧: win help api（拡張で使える関数）・commands（登録したコマンド）・sets（セット）・layouts（型）"))
    print(tr("\n位置・状態での窓の指定（窓を書ける所ならどこでも。【複数】は当たる窓すべてにかかる）"))
    for s, d in AT_SELECTORS:
        print(f"  {s:<10} {d}")
    for path, msg in EXT_ERRORS:
        print(tr("\n読み込めなかった拡張: {0}\n  {1}").format(path, msg), file=sys.stderr)
    return 0

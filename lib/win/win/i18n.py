"""画面の文字列の翻訳。日本語の文字列そのものを鍵にして、日本語以外の言語では英語の対応表（i18n_en）で置き換える。
言語は、環境変数 WIN_LANG（ja・en）、なければ LC_ALL・LC_MESSAGES・LANG の順で決める（ja で始まれば日本語、それ以外は英語）。
日本語のときは対応表を読み込まない（起動を遅くしない）。対応表にない文字列は、そのまま（日本語で）出る。"""
import os


def _detect():
    for name in ("WIN_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(name)
        if v:
            return "ja" if v.lower().startswith("ja") else "en"
    return "en"


LANG = _detect()

if LANG == "ja":
    def tr(s):
        return s
else:
    from .i18n_en import EN

    def tr(s):
        return EN.get(s, s)

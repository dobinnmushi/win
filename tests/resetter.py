# 試験用: 開いて 0.25 秒後に、自分で 500x400 へ大きさを戻す窓（保存した大きさを復元するアプリの代役。1 回だけ）
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

app = Gtk.Application(application_id="local.win.resettest")


def activate(a):
    w = Gtk.ApplicationWindow(application=a, title="resettest", default_width=800, default_height=600)
    w.set_child(Gtk.Label(label="resettest"))
    w.present()
    GLib.timeout_add(250, lambda: (w.set_default_size(500, 400), False)[1])
    GLib.timeout_add(8000, lambda: (a.quit(), False)[1])


app.connect("activate", activate)
app.run([])

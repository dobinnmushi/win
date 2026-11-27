import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

// win（~/projects/win）が使う D-Bus。名前 org.local.WinHelper、パス /org/local/WinHelper。
// 窓の操作は Window Calls（window-calls@domandoman.xyz）が持っているので、ここには Window Calls にないものだけを置く。
const IFACE = `<node>
  <interface name="org.local.WinHelper">
    <method name="Workspaces">
      <arg type="i" direction="out" name="current"/>
      <arg type="u" direction="out" name="count"/>
    </method>
    <method name="Switch">
      <arg type="i" direction="in" name="index"/>
      <arg type="b" direction="out"/>
    </method>
    <method name="SwitchRelative">
      <arg type="i" direction="in" name="delta"/>
      <arg type="b" direction="out"/>
    </method>
    <method name="Flash">
      <arg type="s" direction="in" name="color"/>
      <arg type="i" direction="in" name="width"/>
      <arg type="i" direction="in" name="duration"/>
      <arg type="b" direction="out"/>
    </method>
  </interface>
</node>`;

export default class WinHelper extends Extension {
    enable() {
        this._impl = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._impl.export(Gio.DBus.session, '/org/local/WinHelper');
        this._nameId = Gio.bus_own_name_on_connection(
            Gio.DBus.session, 'org.local.WinHelper',
            Gio.BusNameOwnerFlags.NONE, null, null);
    }

    disable() {
        if (this._flashTimer) {
            GLib.source_remove(this._flashTimer);
            this._flashTimer = 0;
        }
        this._flashActor?.destroy();
        this._flashActor = null;
        if (this._nameId) {
            Gio.bus_unown_name(this._nameId);
            this._nameId = 0;
        }
        this._impl?.unexport();
        this._impl = null;
    }

    // いまのデスクトップの番号（0 から）と、デスクトップの数（動的ワークスペースでは、末尾の空のものを含む）。
    Workspaces() {
        const wm = global.workspace_manager;
        return [wm.get_active_workspace_index(), wm.get_n_workspaces()];
    }

    // index（0 から）のデスクトップへ切り替える。なければ false。
    Switch(index) {
        const wm = global.workspace_manager;
        if (index < 0 || index >= wm.get_n_workspaces())
            return false;
        wm.get_workspace_by_index(index).activate(global.get_current_time());
        return true;
    }

    // いまのデスクトップから delta 個ずれたデスクトップへ切り替える（端で一巡はしない）。なければ false。
    SwitchRelative(delta) {
        return this.Switch(global.workspace_manager.get_active_workspace_index() + delta);
    }

    // いま前面の窓の枠を、color（CSS の色）・width（px）の縁取りで一瞬光らせ、duration（ミリ秒）かけて消す。
    // Activate の直後に呼ばれるので、フォーカスが移るのを少し待ってから前面の窓を読む。光らせる窓がなければ false。
    Flash(color, width, duration) {
        if (this._flashTimer)
            GLib.source_remove(this._flashTimer);
        this._flashTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 40, () => {
            this._flashTimer = 0;
            this._flash(color, width, duration);
            return GLib.SOURCE_REMOVE;
        });
        return global.display.focus_window !== null;
    }

    _flash(color, width, duration) {
        const win = global.display.focus_window;
        if (!win)
            return;
        this._flashActor?.destroy();
        const r = win.get_frame_rect();
        const full = win.maximized_horizontally && win.maximized_vertically;
        const actor = new St.Widget({
            style: `border: ${width}px solid ${color}; border-radius: ${full ? 0 : 12}px;`,
            x: r.x, y: r.y, width: r.width, height: r.height,
            reactive: false, opacity: 255,
        });
        Main.uiGroup.add_child(actor);
        this._flashActor = actor;
        actor.ease({
            opacity: 0, duration, delay: 80,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => {
                actor.destroy();
                if (this._flashActor === actor)
                    this._flashActor = null;
            },
        });
    }
}

import Gio from 'gi://Gio';
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
}

// win-helper@local の extension.js を、Shell の外（gjs）で動かして、D-Bus の約束を確かめる試験用の呼び出し役。
// 使い方: python3 tests/helper_test.py（extension.js の import の 1 行を差し替えた写しと、模擬の global を使う）
import GLib from 'gi://GLib';

const wm = {
    cur: 1, n: 4,
    get_active_workspace_index() { return this.cur; },
    get_n_workspaces() { return this.n; },
    get_workspace_by_index(i) { const me = this; return {activate(_t) { me.cur = i; }}; },
};
globalThis.global = {workspace_manager: wm, get_current_time: () => 0};
const mod = await import(`file://${GLib.getenv('HELPER_COPY')}`);
const ext = new mod.default();
ext.enable();
GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, Number(GLib.getenv('HELPER_SECONDS') ?? 20), () => { ext.disable(); loop.quit(); return false; });
const loop = new GLib.MainLoop(null, false);
loop.run();

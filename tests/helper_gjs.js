// win-helper@local の extension.js を、Shell の外（gjs）で動かして、D-Bus の約束を確かめる試験用の呼び出し役。
// 使い方: python3 tests/helper_test.py（extension.js の import の 1 行を差し替えた写しと、模擬の global を使う）
import GLib from 'gi://GLib';

const wm = {
    cur: 1, n: 4,
    get_active_workspace_index() { return this.cur; },
    get_n_workspaces() { return this.n; },
    get_workspace_by_index(i) { const me = this; return {activate(_t) { me.cur = i; }}; },
};
const logFile = GLib.getenv('HELPER_FLASH_LOG');
const log = line => GLib.file_set_contents(logFile, (GLib.file_test(logFile, GLib.FileTest.EXISTS) ? new TextDecoder().decode(GLib.file_get_contents(logFile)[1]) : '') + line + '\n');
class Widget {
    constructor(p) { this.p = p; log(`widget x=${p.x} y=${p.y} w=${p.width} h=${p.height} style=${p.style}`); }
    ease(p) { log(`ease opacity=${p.opacity} duration=${p.duration}`); p.onComplete(); }
    destroy() {}
}
globalThis.mockShell = {
    Clutter: {AnimationMode: {EASE_OUT_QUAD: 0}},
    St: {Widget},
    Main: {uiGroup: {add_child() {}}},
};
const win = {get_frame_rect: () => ({x: 100, y: 200, width: 800, height: 600}), maximized_horizontally: false, maximized_vertically: false};
globalThis.global = {workspace_manager: wm, get_current_time: () => 0, display: {focus_window: win}};
const mod = await import(`file://${GLib.getenv('HELPER_COPY')}`);
const ext = new mod.default();
ext.enable();
GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, Number(GLib.getenv('HELPER_SECONDS') ?? 20), () => { ext.disable(); loop.quit(); return false; });
const loop = new GLib.MainLoop(null, false);
loop.run();

# win design notes (as of 2026-11-21)

[日本語](../design.md) · English translation of the Japanese original; if the two differ, the Japanese is authoritative. References to `docs/*.md` below mean the Japanese originals; the English translations are in `docs/en/`.

A home-made tool that controls GNOME (Wayland) windows with commands and small dialogs. The core is a Python package (`lib/win/win/`), and the launcher is `bin/win`.

## 1. Overall structure

```
bin/win                 launcher (finds lib/win from its own real location, imports it and just calls main())
lib/win/win/            the core (27 modules)
tests/                  snapshot.py (before/after comparison of output), names.py (undefined and unused names), trace.py (records window movement), helper_test.py (tests the extension's D-Bus contract), resetter.py (a test window that resets its own size right after being placed), fixtures/
docs/                   design.md (this document), interactive-design.md (interactive dialogs), images/ (the README's images)
presets/                the standard set of shortcuts (super-alt.toml; applied with `win shortcuts apply`)
examples/               sample extensions (Python files for `~/.config/win/ext/`): swap, merge, split
README.md / README.ja.md, install.sh / uninstall.sh, LICENSE
extension/              the GNOME Shell extension win-helper@local (D-Bus for getting and switching desktops) and its install.sh
~/.config/win/          the user's settings (all optional): shortcuts.toml, commands.toml, sets.toml, apps.toml, layouts.toml, ext/ (Python extensions). They may be links
```

`~/.local/bin/win` is a link to `bin/win`. Child processes (dialogs) are also started through `WIN_BIN` (this launcher).

### Modules (dependencies go from bottom to top; a lower module never imports a higher one)

| Layer | Module | Role |
|---|---|---|
| Foundation | `common` | Constants, the standard-library imports, `WinError` |
|  | `screen` | `Screen` (the reference monitor), the work area, loading the settings (layouts.toml), screen information over D-Bus |
|  | `layouts` | Parsing layout expressions (full / v(...) / h(...) and the abbreviations) and computing tiles |
|  | `shortcuts` | Reading and writing GNOME custom shortcuts (dconf), exporting and applying shortcuts.toml, the list of standard operations (it holds no default keys) |
|  | `dbus` | Window Calls over D-Bus, the window list, window specs (`@left`, `@slot:N` and so on) |
|  | `desktop` | Getting and switching desktops (workspaces) (calls the D-Bus of the extension win-helper@local) |
|  | `i18n` | Translation `tr()` of on-screen strings (the Japanese string is the key; the `i18n_en` table is read only for languages other than Japanese) |
|  | `usage` | Usage log (only the command name and whether it came from a key or was typed) and the summary |
| Storage and placement | `store` | Reading and writing commands.toml and sets.toml, checking the command syntax, apps' launch commands |
|  | `pickwin` | Display names for rows of the window list, aligning the dialog's position |
|  | `placement` | Placement by layout (`win layout`) |
|  | `undo` | Undo (recording and restoring the state of the windows to be moved, from before they were moved) |
|  | `simple` / `textui` / `nav` | list, focus, move, size, state, close / parts for terminal interaction / directional focus movement |
| State and sets | `sets` | Sets (saved arrangements of windows), material for previews, the list of monitors |
|  | `prompt` | The command-input dialog (`win prompt`) and completion |
|  | `appstate` | Deriving the current arrangement (the order of tiles), Firefox/terminal state, `win save` |
|  | `groups` | Saving and operating window groups (named and saved) |
| Interactive dialogs | `tilepick` | The rendering side of the generic dialog (`_tilepick`, GTK), plus filtering, the app list and terminal interaction |
|  | `dialog` | `Dialog` (the parent-side part) and the functions for choosing once (`choose` and so on) |
|  | `pickers` | Dialogs for choosing windows and sets (`win pick`, `win set` and the extension's `pick()`) |
|  | `layoutflow` | The interaction of `win layout` (from choosing a layout to choosing for each tile) |
| Extensions and entry points | `ext` | Extensions (`~/.config/win/ext/*.py`) and `winapi` |
|  | `lsp` / `configwin` | Completion for editors (`win lsp`) / the settings window (`win config`) |
|  | `overlay` / `cli` | Overlaying a window on the target (`win place`, `win here`) / the command-line entry point (`main`, `build_parser`) |

- Reverse dependencies (places where a lower module uses a function of a higher module) are made lazy imports inside the function that uses them (marked with `# 逆向きの依存`, about 20 places). References at module level (constants, class bodies, decorators) always point downward.
- `win.NAME` can look up the names of all modules (`__init__` collects them; this is for tests and old calling styles).

## 2. Actions (named operations)

From the user's point of view, these are the same kind of "operation" even though the implementation containers differ.

| Kind | Where | Examples |
|---|---|---|
| Built-in | `cli.build_parser` (each module's `cmd_*`) | `place`, `layout`, `set`, `pick`, `nav` |
| Extension | `@command` in `~/.config/win/ext/*.py` | `swap`, `merge`, `split` |
| Command | `commands.toml` | Registered win commands and shell commands |
| Set | `sets.toml` | Saved arrangements of windows |

- The settings window's shortcut page is organized **by purpose, not by kind** (choose and move between windows / arrange and place windows / saved arrangements / commands / other), and the kind is shown by a mark at the left of each row. An extension can choose its group with `@command(group="…")`.
- **Make it built-in:** things that depend directly on win's internal parts (dialogs, screens, deriving the arrangement), and foundations for other operations (`place`, `layout`, `set`, `pick`, `nav`, `focus`).
- **Make it an extension:** "combinations" that can be written with only the public functions of `winapi` (`swap`, `merge`, `split`).
- **Make it an alias:** something that only fixes the arguments of an existing operation has no implementation of its own (`here` is `place 0`).
- An extension with the same name as a built-in is an error at load time (the built-in wins).

## 3. The reference monitor (Screen)

An immutable `Screen` (logical area, whether it is the primary monitor, connector name). The work area is `screen.work_area(cfg)`.
- `find_screen(choice)` does not change state. There is one default `Screen` per run (the command line's `-m`; `default_screen()` / `use_screen()`, decided at startup by `resolve_monitor`).
- When switching monitors inside a dialog, the default is not rewritten; a new `Screen` is created and passed to the functions (`place_move` returns a new `Screen`; the layout choice of `win layout` carries it along in `args.monitor`).
- `current_tiles`, `slot_map`, `free_rects`, `place_targets` and `monitors_for_preview` use the default when `screen` is omitted.

## 4. Targets (place)

`win place [N|free] [window] [--min]`. The target is N (1 or more) = the N-th tile of the current arrangement, 0 = the tile of the focused window (or that window's own place if it is outside the arrangement), free = the largest free space.
- Free space: from the reference monitor's work area, subtract the frames of the non-minimized windows; of the maximal rectangles that remain (at least 5% of the area and at least 10% on each side), up to 6 in descending size (`free_rects`).
- In a dialog, the left and right arrows move the target. Going past the end moves to the neighboring monitor.
- The frame to place into is the actual frame of the window in the target tile, clipped to the reference monitor's work area (`clip_to_area`). The derivation of the arrangement (`current_tiles`) clips overhang and decides "half" and so on, so unless the placed frame is clipped the same way, a window in the right tile that sticks out of the screen (for example after a restore following a restart) would make the placed window stick out too and not fit in half.

## 4.1 Stacked windows (stack)

Windows stacked at the same position are treated as a "layer" of each tile (`place` keeps the window at the target and stacks on top of it, so stacking arises naturally).
- **Recognition:** `appstate.tile_stacks`. For each tile of the current arrangement (`current_tiles`), the non-minimized windows whose four frame edges are within `STACK_TOL` (8px) make up the layers. The front layer is the one highest in stacking order. A stack that is completely covered by other windows and cannot be seen does not appear in the arrangement, so it is not included.
- **Cycling:** layers are cycled in ascending order of ID (with Activate alone, you would just go back and forth between the top two, so the order is fixed). Nothing is saved.
- **Handling of the lower layers:** they are only covered (not minimized). The derivation of tiles and the window list ignore windows that are already covered, so they work as they are.
- `win stack [next|prev|list] [N]` (N=0 is the tile of the focused window; `win stack N next` is also accepted. Because the shortcut item calls `win stack next`, the form that puts the action first was made — at first only the number could be written first, and pressing the key did nothing). `list` is a `choose` dialog (the map shows the number of layers of each tile, with the front layer first). The standard shortcut items are `win-stack-next` (Super+Alt+T, Henkan+T; Henkan is the Japanese Convert key) and `win-stack-list` (Super+Alt+Y, Henkan+Y), already assigned (checked on a real machine, both with real keys and through keyd). From extensions: `stack(n)` (the list of layers) and `cycle(n, d)` (shift by d layers and bring to the front).

## 4.1.1 Window groups (group)

A named, saved collection of windows (`groups.py`; saved in `~/.local/state/win/groups.json`, replaceable with `WIN_GROUPS`). Whereas stacking (4.1) is "windows that happen to be at the same place", a group has "explicit, ordered members".
- **Sharing a frame:** a group has one frame (position and size). It places the next member into that frame (a member on another desktop, minimized or maximized is brought back to the current desktop and un-minimized or un-maximized) and then brings it to the front. The members do not need to overlap beforehand.
- **The frame follows the front member:** if you move the front member, the next switch appears at that position.
- **Members:** window IDs and their order (the cycling order). A window belongs to at most one group (adding it to another group moves it). Closed windows are removed at load time, and an empty group is deleted.
- `win group [list|new NAME [window…]|add NAME [window…]|remove [window…]|delete NAME|next|prev|show|select [NAME]|place NAME [tile]|from-stack [tile] [NAME]]`. If the name is omitted, the group the focused window belongs to is used (suited to shortcuts). `show` places all members into the frame (the placing is done in parallel per window). `select` is a dialog (the front member first). `from-stack` turns a stack (4.1) into a group. The standard shortcut items are `win-group-next` (Super+Alt+G, Henkan+G) and `win-group-select` (Super+Alt+U, Henkan+U). They are assigned, and both real keys and keyd were checked on a real machine (switching the front member and choosing in the dialog).
- From extensions: `group(NAME, window…)`, `groups()`, `group_of(window)` and `Group` (`members`, `active`, `rect`, `add`, `remove`, `delete`, `next`, `show`, `place`).
- **Integration into layout and set** (commands that are not used do not get heavier; the group handling runs only when `@group:` appears):
  - `@group:NAME` (a window spec): in `layout`'s list of windows, puts the whole group in one tile (places all members into the frame and brings only the front member to the front). Members of a group are not picked up as windows for other tiles (regardless of the order of the specs). Where it is used as the spec of a single window, it means the front member.
  - `group define NAME window-spec…`: defines a group (recreating it) from window specs (`class?`, `class?command`, `!command`, `@…`; the same as layout's list of windows). It gives the same result however many times it is run. It does not place anything. Because it is defined by specs and not by window IDs, it can be reproduced as lines of a `set` even after logging in again.
  - `win save`: writes the windows that belong to a group as a `group define NAME …` line and as a `layout … @group:NAME …` list of windows. Windows that overlap as members of a group are not counted in the "not included" notice.
  - Example (a set's `run`): the two lines `group define work firefox? org.gnome.Ptyxis?` and `layout lr @group:work thunderbird?`.
  - **Multiple groups:**
    - When `layout` places multiple groups (`layout lr @group:a @group:b`; group, single, group), all members of each group are placed in parallel. A single-window spec never picks up a member of any group. Specifying the same group for two tiles is an error.
    - Writing to the storage is made one at a time inside the process (a lock). When placing in parallel, a later group's write could erase an earlier update (the frame), which was a race.
    - "Launch if absent" specs (`class?`, `class?command`) never pick up a member of any group and launch a new window if none is found (so that a group's window that does not appear in `layout` is not torn into a single tile; if there is no group at all, the storage is not read). Explicit specs without `?`, `@` specs and IDs can still point to a group's window as before.
    - Repeating `layout` of 3 groups (3 columns) and 4 groups (4 columns) 8 times with the positions scrambled, the positions of all members and the saved frames matched every time (about 0.96 seconds, constant regardless of the number of members). A round trip of saving with 4 groups → closing all → `set` was also checked. When a tile smaller than the calculator's minimum size (616px high, 360px wide) is requested, the size notice appears for groups too (it stabilizes at the minimum size).
    - `group define` does not pick up members of other groups. A `set` with several groups of the same class (`group define a calculator? calculator?` and `group define b calculator? calculator?`) can be restored from a state where everything is closed.
- **Note (a specification of this environment):** this environment has `workspaces-only-on-primary` (workspaces apply only to the primary monitor) set to true, so windows on the secondary monitor (eDP-1) appear on every desktop and `MoveToWorkspace` has no effect. Movements across desktops (`Window.desktop`, the group's `show`) apply to windows on the primary monitor.

## 4.2 Desktops (workspaces)

- **A window's desktop:** the `workspace` of `List` (from 0) and `MoveToWorkspace` (Window Calls) are enough. `Window.desktop` (from 1; assigning to it moves the window) works without the extension. `win desktop list` also counts from the window list, so it works without the extension.
- **Switching:** neither Window Calls nor GNOME Shell's `Eval` (disabled) can do it, so the home-made Shell extension `win-helper@local` exposes it over D-Bus (`org.local.WinHelper`: `Workspaces`, `Switch`, `SwitchRelative`). It is built the same way as `raise-claude@local`. On the win side it is `desktop.py` (`desktops()`, `switch_desktop(n)`, `switch_relative(d)`); the command is `win desktop [N|next|prev|list]`, and from extensions `desktops()` and `switch_desktop(n, relative)`. Without the extension, a `WinError` with installation instructions is raised.
- **Installation:** `extension/install.sh` (copies to ~/.local/share/gnome-shell/extensions/). On Wayland, logging in again is required for it to be loaded. It has already been added to `enabled-extensions` (to undo: `gnome-extensions disable win-helper@local`).
- **Scope of verification:**
  - The D-Bus contract was checked by running, under gjs, a copy with the one `import` line of `extension.js` replaced (a mock `global` in place of the Shell) and calling it from the win side (`tests/helper_test.py`. So as not to collide with the real extension, the mock runs under the name `org.local.WinHelperTest`, and the win side points to it with `WIN_HELPER_NAME`).
  - **Checked on a real machine after logging in again** (2026-11-21): the extension was loaded (`gnome-extensions info` showed ACTIVE), and `win desktop` (display), `2`, `1`, `next`, `prev`, out-of-range and invalid specs behaved as expected.
- **A quirk of the `workspace` in List:** a window on the secondary monitor (shown on every desktop) has a `workspace` that follows "the current desktop". In `win desktop list`, windows on the secondary monitor are counted in the desktop you are on.
- Policy: with dynamic workspaces there is always one empty desktop at the end, and `count` includes it. Switching does not wrap around at the ends.

## 4.3 Focus-change cue (border flash)

When a command settles the foreground on one window, that window's frame flashes briefly so you can see where focus went.
- **Applies to**: `nav`, `focus`, `pick` (without `--id`), `stack`, `group next/prev/show/select`. Commands that move many windows (`layout`, `set`, `place`) do not flash. `focus` by name flashes too (a window that comes from another workspace or from behind is easy to lose). The decision is `cli.moves_focus`, called once at the end of a command rather than at each `Activate`.
- **How**: the helper extension's D-Bus `Flash(color, width, duration)` reads the focused window 40 ms later (to let focus settle), overlays a border-only `St.Widget` on its frame and fades it out. Windows are not touched. With an old or missing extension nothing flashes and everything else works as before.
- **Setting**: `[flash]` in `layouts.toml` (`enabled = true`, `color = "#62a0ea"`, `width = 2`, `duration = 450`). `enabled = false` turns it off.
- **Verified**: the D-Bus call and its values in `tests/helper_test.py` (mock St). The actual drawing can only be checked after the extension is loaded (re-login).

## 4.4 Per-application settings

- **Per-application settings (`apps.toml`):** the arguments to add when launching an application that opens no new window without arguments can be specified with `new_window = ["--new-window"]` under `[app.LAUNCH-COMMAND-NAME]` in `~/.config/win/apps.toml` (replaceable with `WIN_APPS`). It takes precedence over the built-in defaults (ptyxis, gnome-text-editor, nautilus, Chrome), and an empty list means nothing is added. Saving Firefox tabs and a terminal's working directory is done by dedicated per-application code (`appstate.py`), not a table.

## 4.4b Display language (i18n)

- **Mechanism:** strings shown on screen are written in Japanese and wrapped in `tr("…")` (for f-strings, `tr("…{0}…").format(…)`). If the language is Japanese, `tr` returns the string as it is; otherwise it looks it up in `i18n_en.EN` (a Japanese → English dictionary). A string that is not in the dictionary is shown in Japanese (it does not fail).
- **How the language is decided:** `WIN_LANG` (ja, en); if absent, `LC_ALL`, `LC_MESSAGES`, `LANG` (Japanese if it starts with `ja`, otherwise English). It is decided once at startup. For Japanese the dictionary is not read, so startup does not get slower (measured: the median 88 ms → 94 ms is noise, the minimum 78 → 77 ms).
- **Why the key is Japanese:** because Japanese is the original text (the code looks almost the same, and the output in Japanese was confirmed to match exactly the output before the rewrite on 43 files including `-h`, `help` and `snapshot` (excluding `stats`)). The standard gettext (which needs an external tool to compile .po files) was not used.
- **Not translated:** the Lua of the nvim input box (`prompt.py`); text the user writes themselves (an extension's description, the names of sets and commands); code comments and docstrings.
- **When adding a string:** write it as `tr("Japanese")`, add the English under the same key in `i18n_en.py`, and run `python3 tests/i18n_check.py` (it checks for missing translations, stale entries, mismatched placeholders such as `{0}`, and Japanese mixed into the English).
- **Do not decide by wording:** a translation would no longer match, so do not branch on a word contained in an error message (for example, "the same name exists" is distinguished by the type `NameExistsError`).
- A note on appearance: English is longer than Japanese, so narrow columns (such as the count in the list of layouts) were shortened (`×2`).

## 4.4c Policy on the GUI and key operation (implemented up to the first stage, 2026-11-21)

The command line is the core, and the GUI (the settings window and the dialogs) is an entry for "finding and trying operations". Three points are kept.
- **Every operation can be done with the GUI alone, and keys are the second route.** No mouse-only operation is made. Each button's tooltip shows its key, and the key list (`?`) shows them all.
- **No key scheme is imposed.** Key assignments are collected in a table of "action name → keys" (`keymap.py`). The standard keys (arrows, Ctrl) and the vi-like keys (`j`, `k` and so on) are placed side by side for the same action, and both always work. There is no setting to switch (plain keys are not used while text is being typed, so they do not collide. Even if pressed by mistake, deletion shows a confirmation screen, and since settings are saved immediately, nothing is lost). An emacs scheme is not made (if requested, it is enough to add keys to the table).
- **Do not hijack text input.** Plain keys without Ctrl have no effect while an input field or a dialog is open.

The settings window (first stage, implemented. With keys sent on a real machine, I checked switching pages, moving between rows, the default action, the deletion confirmation, filtering, the key list, closing the window, and that the keys have no effect while a dialog is open. Rows on the layout page cannot yet be moved with keys; only switching pages): the list's rows get a "current row", and actions (switching pages, moving between rows, the default action, editing, deleting, new, filtering, the key list, closing) can be called with keys. (Considered and dropped: an "Operations" page listing operations that move windows. It would assume the settings window is open all the time, and it overlaps with the shortcut page. One-off operations will be handled by growing `win prompt` (Tab completion).) Aligning the key scheme of the dialogs (`pick`, `place` and so on) to the same table will be considered separately.

Rows that are cycled with `j`/`k` and so on are rearranged in the order they appear on screen, not the order they were registered (`order_rows`; the shortcut page registers them in the order before grouping, so left as it is it would disagree with the appearance).

## 4.5 New features

- **Jump to an application:** `win focus 'class?'` (`class?command` is also accepted). If a window exists, bring it to the front; if you are already in that application, go to the next window (cycling in ascending ID order); if none exists, launch it. The conventional `win focus` without `?` is unchanged (this replaces the dedicated home-made extension `raise-claude@local`. The extension has not been removed).
- **The opposite monitor:** the window spec `@monitor:other` = the frontmost window on a monitor other than the one the focused window is on (with 3 or more monitors, cycling from left to right).
- **Send to another monitor:** `win send [next|prev|primary|monitor-name] [-w window]`. It keeps the window's position and size as proportions of the monitor's work area (a maximized window stays maximized). An undo record is made only when something was actually moved.
- **Maximizing brings it to the front:** `win max` (`win state max`) also brings the maximized window to the front (so that when another window is specified with `-w`, it does not stay hidden behind after being maximized). On a real machine I confirmed that maximizing a window that was behind with `-w` brings it to the front. Un-maximizing, minimizing and un-minimizing do not bring it to the front (as before).
- **Undo:** `win undo` (`win undo list` shows the list; the latest 10). Just before `layout`, `place`, `here`, `group` (show, place, add), the old-format `set` and `send` move windows, **only the windows to be moved** have their position, minimized state, maximized state, desktop, stacking order and the frontmost window recorded (`~/.local/state/win/undo.json`, replaceable with `WIN_UNDO`). Windows launched by the operation are not closed. Windows that had been closed cannot be restored. On a real machine I confirmed that undoing `layout`, `place`, `group show` and `send` fully restores positions, stacking order and the frontmost window.
- **Usage log:** `win stats [days|on|off|reset|path]`. Only the command name and "from a key or typed" are appended, one line each (arguments are not recorded; `~/.local/state/win/usage.log`, replaceable with `WIN_USAGE`). Whether it came from a key is judged by whether the parent process is `systemd` (GNOME custom shortcuts are started under systemd). On by default. One record takes about 8 μs, and the effect on startup time is within measurement error (around +1 ms). `lsp` and `stats` itself are not counted. Calls inside a process, such as within `set`, are not counted.
- **Note:** while the screen is locked, GNOME stops extensions, so Window Calls does not respond. Tests that send keys are run only after checking that the window list can be obtained and that there is a frontmost window (so as not to send keys to the lock screen).

## 5. Interactive dialogs

Every dialog is a pair of a **generic child process that only renders** (`_tilepick`) and a **stateful parent `Dialog`**. Details are in `docs/interactive-design.md`.

| Dialog | Parent function | Module |
|---|---|---|
| `win place`, `win here` | `gui_place` | `overlay` |
| `win set` | `pick_set` | `pickers` |
| `win pick`, the terminal window list | `pick_rows` | `pickers` |
| The extension's `pick()`, the `@pick` window spec | `pick_window_map` | `pickers` |
| `win layout` | `gui_layout_flow`, `gui_interactive` | `layoutflow` |
| From extensions | `Dialog`, `choose`, `confirm`, `ask`, `pick_tile`, `pick_window` | `dialog` (`winapi`) |

Exceptions: command input (`_prompt` and `_nvprompt` of `win prompt`), the settings window (`win config`, in the same process) and the numbered marker windows (`_tile`) are built differently.

## 6. Tests

- `python3 tests/snapshot.py > before.txt` (before the change) → `after.txt` (after the change) → `diff`. It records help, the list of layouts, LSP responses and the results of pure functions (it moves no windows and touches no settings; the settings are a copy in `tests/fixtures`).
- `python3 tests/names.py lib/win/win/*.py`: finds undefined names (references that could raise NameError) and unused imports.
- Dialogs are checked on a real machine. Before sending keys, check each time that the focused window is the dialog (if it is not, the keys go into another window).

## 6.1 Handling window positions (quirks of Window Calls)

- **Move by the frame:** check the position and size with `GetFrameRect` (the frame). To move, use `MoveResize` (frame-based) or `Move`. Do not use `Resize` — it shifts the frame to the upper left by the window's shadow margin (about 25px for CSD windows) even at the same size (`win size` had its position shifted by this. It now keeps the position with `MoveResize`).
- **Move a launched window immediately:** a new window first appears at the position the application decided (sometimes on another monitor). To shorten the time it is visible, `wait_new_window` returns as soon as it appears (waiting only 0.08 seconds), and `place_settled` checks again. A window launched with `!` from the dialog of `win place` is placed before the dialog is closed.
- Checked with Firefox (`--new-window` into a running session): it is visible at the default position for 70–90 ms, then moves to the destination once, with no moving back. Even when a tile narrower than the minimum width (639px) is requested, the position does not wobble and it stabilizes at the minimum size (639x960), and a notice appears.
- The same with a Firefox of a fresh profile (a separate instance with `-no-remote -profile`; it appears in about 1 second): it is visible at the default position for about 0.1 seconds, then moves to the destination once, with no moving back for 40 seconds. It may restore its previous size and reset its own size right after being placed (observed only once; timing-dependent).
- When an application resets the position or size right after being placed, `place_settled` looks every 0.05 seconds while waiting, and if the window was once in the right place but was moved, it places it again immediately. The time during which a wrong size is visible went from about 140 ms to about 30 ms (reproduced and measured with `tests/resetter.py`: a test window that resets itself to 500x400 0.25 seconds after opening).
- A window whose position matches and whose size is at least the requested size is regarded as merely not shrinking because of its minimum size, and `place_settled` settles. Maximized and fullscreen windows are excluded, however, and are placed again (`is_maximized`. A window that Ptyxis restored from the previous session went back to maximized after placement, and the code gave up at 1920x1168. Not verified on a real machine right after a restart). An idea of watching until 10 seconds after placement was dropped for lack of grounds (it was introduced in `77ce5a2` and reverted).
- Window movement can be turned into numbers with `tests/trace.py` (changes of position, stacking order and focus about every 20 ms. The positions of existing windows are examined only with `--all`, because the query load delays the measurement). Use it when you suspect display problems (flicker, spanning another monitor, going back and forth).

## 6.2 Speed and lightness (measured 2026-11-20)

- **Ordinary commands** (such as `win list`) take about 80 ms: Python 8 ms, loading `gi` about 50 ms (of which `asyncio` is about 23 ms), our own code about 11–20 ms. The floor is PyGObject itself, and there is almost nothing we can trim. The idea of using `gi` without loading `asyncio` does not work because `gi` requires `asyncio.InvalidStateError`. Loading `GioUnix` takes about 1 ms and is not worth trimming.
- **A dialog** (a child process) takes about 230 ms from startup until the window appears (`gi` about 38 ms, Gtk and Adw about 25 ms, the rest is GTK's startup and creating the window), and about 140 MB of memory. Loading our own code takes about 11 ms.
- Tried without effect: starting the dialog's child process before collecting the material (deriving the arrangement, the window list) so they run in parallel. Even in the original flow the heavy window-list fetch was already done after the child started, so they overlapped; the remaining serial part was about 25 ms, and the time to appear (0.32–0.34 seconds) did not change. It was reverted.
- With effect: when `win layout` arranges existing windows, the wait for settling after placement (0.3 seconds or more per window) was made parallel per window (only the launches are one at a time). 1.27 seconds → 0.96 seconds with 2 windows, 1.91 seconds → 0.95 seconds with 4. The positions matched every time over 8 repetitions.
- `win set`: the current format (`type = "win"`, lines of `layout ...`) benefits directly from the parallelization of `layout` above. The old format (`type = "arrange"`, `run_arrangement`) also had its placing made parallel per window, with only the bringing to the front done afterwards in the saved order (bottom → top), to reproduce the stacking order. 1.43 seconds → 0.44 seconds with 4 windows (the same three times). Launching, maximizing and the notice for windows that are not found were also checked.

## 7. Known issues

- To reduce the lazy imports (about 20 places), move the parts that are used (window visibility checks, deriving tiles, launching dialogs) to a lower layer.
- Not verified on a real machine:
  - `keep_selection` of `Dialog`.
  - Terminal interaction (`layout -i -t`) with `--preview` (the numbered marker windows).
  - Parallelization (`layout`, the old-format `set`) with dozens of windows, and with windows in another workspace.
  - Restoring Firefox's saved size depends on timing and does not reproduce every time (checked with the stand-in window of `tests/resetter.py`).
  - A maximized window does not move to the target monitor (maximizing stays on the monitor where the window is; the behavior as before).
  - Groups and stacks: with dozens of windows. The display and operation of the `stack` and `group` items on the settings window's (`win config`) shortcut page (the key assignments themselves were registered by command and checked with real keys).
- Constraints:
  - A group holds its windows by window ID, so when a window is closed or you log out, that member drops out (window IDs change at the next login, so a saved group becomes empty and disappears). Re-binding by window class or title is not done.
  - Windows on the secondary monitor (eDP-1) are excluded from movement between desktops (`workspaces-only-on-primary`).

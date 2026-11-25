# Design of the interactive dialogs

[日本語](../interactive-design.md) · English translation of the Japanese original; if the two differ, the Japanese is authoritative.

## 1. Current calls (as of 2026-11-20)

| Dialog | Child process | Parent function | Parent–child exchange | Called from |
|---|---|---|---|---|
| Filtering dialog | `_tilepick` (`tilepick.run_tilepick`) | `gui_layout_flow` (choose a layout), `gui_interactive` (per tile), `pick_interactive` (one window), `gui_place` (here/place) | Two-way, one JSON per line. Parent → child: `layouts`, `tile`, `busy`, `quit`. Child → parent: `layout`, `win`, `app`, `cmd`, `skip`, `back`, `target`, `none`, `cancel` | `win layout`, `win here`, `win place`, the extension's `pick()` |
| Set dialog | `_setpick` (`sets.run_setpick`) | `pick_set` | JSON passed once at startup, one line returned as the result | `win set` |
| Window list | `_pick` (`pickwin.run_pick`) | `pick_window` | Passed at startup, the result is returned | `win pick` |
| Command input | `_prompt`, `_nvprompt` | `cmd_prompt` | A line with the result | `win prompt` |
| Numbered markers | `_tile` (`textui.run_tile`) | `start_placeholders` | None (the parent closes it) | The preview display of `layout -i` |
| Settings window | (same process) | `run_config` | — | `win config` |

## 2. What we learned

- The screen "list of rows + filtering + mini map" is in effect one component (`_tilepick`), yet its messages are fixed to two stages, "choose a layout" and "per tile". Every time a use was added, items were added to the messages (`title`, `hint`, `placeholder`, `labels`, `movable`, `mon`, `free`, `apps`, `notice`).
- The set dialog and the window list are built differently and each holds a duplicate of the same-looking component.
- The only interactive facility available to extensions is `pick(title, slot, launch, exclude, rect)`. It cannot do the following.
  - Choose among things other than windows (layouts, sets, monitors, an arbitrary list).
  - Choose a tile or a free space on the map.
  - Move state with keys (← → and so on) (moving the target of `place` is possessed only by the built-in).
  - Confirmation and text input.
  - Learn which key (Enter or Tab) was used to decide.

## 3. What we want extensions to be able to adjust

- Appearance: title, guidance text, description of the input field, notices (errors), rows (name, supplementary text, icon, mark), mini map (tiles, labels, highlights, dotted lines, monitor frames).
- Input: whether to filter, whether launching an app with a leading `!` is allowed, single or multiple selection, the initially selected row.
- Keys: the kind of decision (Enter or Tab), extra keys to receive (← →, Ctrl+S and so on), disabling default keys.
- Flow: a selection that finishes in one go, or an exchange that keeps updating state. A busy indicator, showing an error and keeping the dialog open.

## 4. Proposal: a two-level component

Make the dialog a **generic component that only handles rendering**, and put **state management on the parent (the extension's Python) side**.

### 4.1 Convenience functions (finish in one go)

```python
from winapi import ui

w = ui.pick_window("Window to swap", launch=False, exclude=[a])        # a generalization of the current pick (pick stays as an alias)
i = ui.pick_tile("Target", tiles=ui.slots_map(), current=2)           # choose a tile or free space on the map (move with the arrows)
x = ui.choose("Choose a layout", [ui.Item("lr", sub="v(1,1)")], preview=lambda it: ui.Map(...))
ok = ui.confirm("Run it?")
s = ui.ask("Name", placeholder="…")
```

### 4.2 A component that runs an exchange (state keeps changing)

```python
with ui.dialog(title="Choose a target", hint="Move the target with ← →") as d:
    d.rows(items)                    # replace the rows
    d.map(ui.Map(rects, labels, current=i, free=flags, monitor=m))   # replace the map
    d.notice("There is no target in that direction")
    d.keys("Left", "Right")          # keys to receive
    for ev in d.events():            # ev: Select(item, via="enter"|"tab"), Key("Left"), Text(s), Cancel
        ...
```

`win place` is rewritten on top of this component. The built-in `place` becomes the first user of the same component as extensions (removing special treatment that extensions cannot see).

### 4.3 The rendering component (child process)

- Parent → child is only `show` (it passes the title, guidance, description of the input field, rows, map, notice, keys to receive, filtering and app launching in a single declaration), `busy` and `quit`.
- Child → parent is `select`, `key`, `text` and `cancel`.
- `_setpick` and `_pick` can be replaced with a declaration of rows + preview. `_prompt`, the input field, stays a separate component.

## 5. How to proceed (proposal)

1. Unify the messages of the rendering component into `show` (internal; the appearance does not change).
2. Add the convenience functions (4.1) to `winapi` (`pick` stays).
3. Add the exchange component (4.2).
4. Move `place` and `here`, then `set` and `pick`, onto it.
5. Update `winapi.pyi`, the extension template, `win help api` and the LSP completion.

## 6. Things to decide

- Add both 4.1 and 4.2, or only 4.2 with 4.1 made as thin functions on top of it.
- The scope of the move (only `place`, or also `set` and `pick`).
- Whether to receive events synchronously inside the extension's function (the example above) or to register a callback per key.

## 7. Implementation status (2026-11-20)

All dialogs (`place`, `here`, `set`, `pick`, `layout` and the extension's `pick()`) have been moved onto `Dialog`. Decisions: both the convenience functions and `Dialog`; events are run synchronously inside the function.

**Protocol of the rendering component (`_tilepick`)**
- Parent → child: `show` (redraw everything and wait for input), `patch` (update only the items passed; the answer to a notification that does not wait for a reply), `busy`, `quit`. The old `layouts` and `tile` messages, and the dedicated stages, monitor switching and tile-moving code, were deleted.
- Child → parent: those that wait for a reply — `select` (`via` is enter or tab), `key`, `text`, `app`/`cmd` (launching with `!`), `none` (Tab with no row) and `cancel`. Notifications that do not wait — `highlight` (the selection moved) and `edit` (the text in the input field changed).

**Dialog settings:** `filter`, `entry`, `ask`, `show_list`, `launch`, `highlight`, `keys`, `keep_selection`, `empty`, `chip`, `window_title`, `vim`, `numbers`, `watch`. They can be changed later with `options()` (`win layout` switches the settings in the same dialog, from choosing a layout to choosing per tile).
- `watch`: an `edit` event arrives each time the input changes. If the parent passes `rows()` again, the parent can do the filtering (typing a layout expression).
- `vim`, `numbers`: keys for a list without an input field (j/k, g/G, l, h/q, 1–9) and row numbers (`win pick`).
- Tab with no row → a `select` whose `item` is None (via="tab"). When launched with `!` → `launched` (the window, and its launch command `text`).

**Checked (on a real machine):** `place` and `here` (left/right, across monitors, `!calculator`), `set` (map, left/right, apply), `pick --id` (j/k, digits, q), `layout` (choosing a layout, the expression `1,2`, left/right, `lr` → Ctrl+S → `!calculator`, the reproduction command, both routes of Tab), `layout lr -i` (Ctrl+S, Ctrl+B), and the extension's `choose`, `confirm`, `ask`, `pick_tile`, `Dialog` and `pick()`.

**Not verified:** `keep_selection`, and terminal interaction with `--preview` (the numbered marker windows). The list of terminal interaction (`line_from_picker`) was checked by running `layout lr -i -t` on a pseudo-terminal (`p`, `--pick`, choosing a window number, vacating, going back, cancelling). Tab of `layout` (auto-placement on the layout choice screen, and "decide and let the rest be automatic" in the per-tile choice) was checked on a real machine (the positions of all windows were recorded before the test and restored using the frame-based `place_settled`).

## 8. Preventing a dialog from being opened twice (2026-11-24)

Several dialogs of the same class name can be open at the same time. The following two measures prevent mix-ups and overlaps.
- `center_and_focus` selects the dialog by the child process's pid (selecting by class name alone made the second one keep raising the first window, the keys reached the first one, and the second was left over).
- If a dialog for the same command is already open in another process, the new one is not opened and the open dialog is brought to the front (`dialog.acquire`; a flock on `$XDG_RUNTIME_DIR/win-<name>.lock`, released automatically when the process ends).
  - Built-in: `layout`, `place` (shared with `here`), `pick` and `set` hold it until the process ends (`single_instance`). Terminal interaction is excluded.
  - Extensions: it is held under the running extension's command name (`ext-COMMAND-NAME`) only while a `Dialog` is open. `choose`, `confirm`, `ask`, `pick_tile`, `pick_window` and `pick()` are the same. Nesting and succession within the same process are allowed. The side that was blocked returns as a cancellation (`choose` gives None, `confirm` gives False, `pick()` raises WinError, and the first event of `Dialog.events()` is `cancel`). Different commands are not prevented from each other.

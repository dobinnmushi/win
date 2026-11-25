# Separating personal settings from the generic core, and considering publication (2026-11-21)

[日本語](../publishing.md) · English translation of the Japanese original; if the two differ, the Japanese is authoritative.

## 1. Current scale
- 31 commits, 27 core modules and about 8,400 lines (16% of the lines contain Japanese), about 400 lines related to tests, about 300 lines of documents.
- 27 built-in commands, 3 extensions (`~/.config/win/ext/`: `swap`, `merge`, `split`), and 29 standard shortcut items.
- No personal name, home path or email address is embedded in the repository (checked). The commit author is in GitHub's noreply form.

## 2. The separation

| Layer | Contents | Where | Publication |
|---|---|---|---|
| **The generic core** | Window operations, layouts and placement, `place`, `here`, `stack`, `group`, `send`, `undo`, `set`, `save`, `nav`, the dialog components (`Dialog`, `pickers`), the extension API (`winapi`), `lsp`, the settings window, `stats`, desktops (`desktop` and the extension `win-helper@local`) | The repository (`lib/`, `bin/`, `extension/`) | Can be published as it is |
| **Parts for specific applications** (can be separated as adapters) | Saving and restoring Firefox tabs (`browse`, `appstate`), Ptyxis (`term`, saving the working directory), the nvim input dialog and the LSP connection (`prompt`, `lsp`) | The repository, but turned into a form registered per application (adapters) | After separating |
| **Environmental assumptions** (around key input) | The settings of keyd's Henkan layer (about 50 places in `configwin` and `shortcuts`), switching the IME (IBus, Mozc) | As an optional feature, shown only when keyd is found | After separating |
| **Personal settings** | Shortcut assignments (currently **only in dconf, and not under version control**), keyd's settings, `commands.toml` and `sets.toml`, home-made extensions (`swap`, `merge` and `split` go to `examples/` as generic samples), assumed usage and the key table (`design.md` 4.4), notes on quirks of the environment | Outside the repository (`~/.config/win/` and a separate settings repository) | Not published |

### Progress (2026-11-21)
- Done: `win shortcuts` (export, apply), the personal-settings repository `win-config`, removal of the features that assume keyd and the Henkan key (moved to the personal side), turning the standard assignments into a preset (the code holds no default keys, and `presets/super-alt.toml` holds the 29 items).
- Done: `apps.toml` (only the arguments for a new window; saving state stays dedicated code).
- Done: README (English and Japanese), `install.sh`, `uninstall.sh` and the MIT LICENSE.
- Done: two screenshots (README), updating the structure of the design notes, and the operation to open an extension's source from the settings window (when ptyxis and nvim are absent, it says so on screen).
- Done: English screens (`tr()` and `i18n_en.py`; 641 of 643 keys; excluding nvim's Lua). The design is in 4.4b of `docs/design.md`.
- Done: the English-version screenshots of the README.
- **Published (2026-11-21):** https://github.com/dobinnmushi/win (public, MIT, pre-release v0.1.0). Personal settings are not published and are kept in `win-config` (private).
- Remaining: depending on the reaction, consider checking on other GNOME versions and distributions, CI, and translating comments and design notes into English.

### Things to add for the separation (proposal)
1. **Declarative shortcut settings:** `~/.config/win/shortcuts.toml` (a personal file) and `win shortcuts apply|export`. Currently the assignments exist only in dconf, so they are lost on reinstalling. The standard assignments (the 29 `Super+Alt+X`, which are a personal choice that assumes keyd's Henkan layer) are made **unassigned by default** and shipped as a **preset** (such as `presets/super-alt.toml`).
2. **Make the keyd integration optional:** the keyd items of the settings window are shown only when `/etc/keyd` exists.
3. **A table of application adapters** (`apps.toml`): make it possible to register class → launch command, state saving, and whether it is a terminal, and ship Firefox and Ptyxis as the default registrations.
4. **A settings repository** (personal dotfiles): `shortcuts.toml`, `commands.toml`, `sets.toml`, `ext/` and keyd's settings. The win core only reads them.
5. **Separating the documents:** separate the design (generic) from the record of personal usage (assumptions, key table).

## 3. If it is published
- **Value:** I find no other tool for GNOME/Wayland that combines scriptable window operations (CLI + Python extensions + dialogs), stacking, groups, undo, and saving and restoring (not investigated; a guess).
- **Assumed dependencies:** GNOME Shell and the third-party extension **Window Calls** (`ickyicky/window-calls`, GPL-2.0-or-later, supports GNOME 45–50), Python 3.11 or newer (`tomllib`), `python3-gi`, GTK 4 and libadwaita. For switching desktops, the home-made extension `win-helper@local`.
- **What has been checked:** only Ubuntu 26.04 (GNOME 50.1, Wayland, Python 3.14), a Japanese keyboard, IBus Mozc and two monitors. Other GNOME versions and distributions are unverified.
- **License:** MIT, the same as the other public repositories (such as `bw-autotype`), is natural. A Shell extension needs GPL compatibility, and MIT is compatible.
- **Japanese screens:** about 16% of the on-screen strings, comments and docstrings are Japanese. If published, the README would be English + Japanese (the same as `bw-autotype`), and the screens would either stay in Japanese (with the support stated) or have their strings moved out.

### Checklist before publication
| Item | Contents | Estimate |
|---|---|---|
| Documents | `README.md` (English), `README.ja.md`, screenshots, a support table, known limitations | Half a day |
| Installation | `install.sh`, `uninstall.sh` (the same form as `bw-autotype`; messages in Japanese or English by `LANG`), a launcher for the settings window | Half a day |
| Separation | 1–5 above (`shortcuts.toml`, the preset, making keyd optional, the adapter table, separating documents) | 1–2 days |
| Tests | Neutralizing temporary directories and fixtures, CI (`names.py`, `snapshot.py`) | Half a day |
| Multilingual support | Moving the on-screen strings out (about 1,400 lines) | A few days (can be postponed) |
| Organization | How to take issues, the range of supported GNOME versions, how to version | — |

## 4. Proposed steps
1. **Do only the internal separation first** (valuable even without publishing; personal settings come under version control in a reproducible form).
2. **Prepare for publication** (README, installation, support table). Keep the screens in Japanese and state the support.
3. **Publish** (GitHub, MIT, as alpha. State the support as "checked on Ubuntu 26.04 / GNOME 50").
4. Multilingual support and broadening the supported environments: after seeing the reaction.

## 5. Things to decide
- Whether to publish (yes / no / only the separation first).
- If publishing, the language of the screens (Japanese as is, or English too).
- The license (MIT or GPL).
- Whether to start the separation right away.

## 6. English screens (a revised estimate)
- There are about 900 Japanese string constants excluding docstrings (195 of them f-strings; `configwin` 178, `store` 106, `ext` 89, `cli` 84 and so on). There are 284 docstrings.
- The work is mechanical: wrap the strings in a translation function → make the English table → rewrite the f-strings into a format-based form. The first estimate (a few days) was too large, and was revised to **about one day**.
- The bulk of the effort is not the first time but the maintenance afterwards (two languages for each new string) and checking for dialogs breaking because English is longer.

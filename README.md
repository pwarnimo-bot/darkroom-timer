# Darkroom Timer

Terminal (TUI) timer for black & white film development.

## Run

```sh
.venv/bin/darkroom-timer        # or: .venv/bin/python -m darkroom_timer
```

Fresh setup elsewhere: `python -m venv .venv && .venv/bin/pip install -e .`

## Setup screen

- Film, EI, developer, dilution, temperature, number of rolls
- Time per step: **Pre-rinse, Developer, Stop bath, Fixer, Wash, Rinse aid**.
  Enter `7:30`, `7m30s`, `45s`, or minutes (`7.5`). Leave empty or `0` to skip a step.
- Agitation scheme per step (Ilford, Kodak, continuous, stand, semi-stand, ...)
  or *Custom*: "first X s, then Y s every Z s".

| Key    | Action |
|--------|--------|
| F2     | Presets: film/developer times (type to filter, Enter to load) |
| F3     | Save current film/developer/time as your own preset |
| F4     | Log of past developments |
| F5     | Start |
| Ctrl+O | Open the Massive Dev Chart for this film in your browser |
| Ctrl+P | Command palette (switch theme, etc.) |

## Timer screen

The current step and the total remaining time are shown in large digits. A
banner flashes **AGITATE** with a countdown during agitation and shows the
time to the next one while resting. Sounds: a beep when agitation starts/stops,
two beeps 10 s before the end of a step (start draining), three at the end.

| Key   | Action |
|-------|--------|
| Space | Start step / pause / resume |
| n     | Finish this step now (records the actual time) |
| r     | Restart this step |
| + / - | Add / remove 30 s on the current step |
| a     | Auto-advance (start the next step immediately instead of waiting for Space) |
| Esc/q | Abort (still lets you log it) |

After the last step (or an abort) you can add notes and the session is saved
to the log with planned and actual times per step. In the log (F4): Enter to
view and edit notes, `u` to reuse that setup, `d` to delete.

## Data

Stored in `~/.local/share/darkroom-timer/` (honours `$XDG_DATA_HOME`):

- `log.json`: every development with times, agitation and notes
- `presets.json`: your own presets
- `last_setup.json`: the form as you last started it

Bundled presets (`darkroom_timer/presets.json`) are starting points from
manufacturer datasheets at 20 °C. **Always check them against the current
datasheet.** The Massive Dev Chart blocks scripted access, so the app opens it
in your browser rather than downloading it.

## Arch Linux package

```sh
packaging/arch/build-package.sh -si
```

This tars up the project tree, runs `makepkg` on `packaging/arch/PKGBUILD`,
installs the dependencies from the official repos (`python-textual` and the
Python build tools) and installs the package. Afterwards run `darkroom-timer`
from anywhere, or start it from your app launcher. Uninstall with
`sudo pacman -R darkroom-timer`. To release a new version, bump `pkgver` in
the PKGBUILD and `version` in `pyproject.toml`.

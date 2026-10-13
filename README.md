# Nekopet

Athena's desktop companion — a tiny teal nekomimi who lives on your screen.

She strolls along the bottom of the screen, climbs up the edges, clambers over
your windows, naps, twirls, and occasionally gets herself adorably stuck between
two windows. Pet her: click her **head** for love, her **belly** for giggles —
click her **tail** at your own risk. Every click also opens
[Athena's page](https://github.com/Nyxtena) in your default browser.

## Setup (Pop!_OS / Ubuntu)

```bash
sudo apt install python3-tk wmctrl
pip install pillow python-xlib
```

`wmctrl` is optional but recommended — it's how she sees your windows so she
can climb them. Without it (e.g. on Wayland) she falls back to screen-edge
mode and still does all her cute stuff.

`python-xlib` gives her true per-pixel transparency via the X Shape extension
(tkinter's built-in transparency flag is Windows/macOS-only, so without this
she'd be stuck in a magenta box). If it's missing she'll still run, just
with the box. On Wayland she runs through XWayland, where shaping usually
works on recent versions.

## Run

```bash
python3 nekopet.py
```

Useful flags:

- `python3 nekopet.py --debug` — magenta box (no transparency) + console
  diagnostics: screen size, detected windows, live state/position
- `python3 nekopet.py --diagnose` — print environment info and exit
  (version, X11/Wayland, pillow/python-xlib, SHAPE extension)
- `python3 nekopet.py --no-shape` — disable X shaping entirely
  (falls back to the magenta box; useful for troubleshooting)

## Controls

| Input | What happens |
|---|---|
| Left click head | Happy hop, hearts ♥ |
| Left click body | Giggle wiggle, little dance ♪ |
| Left click tail | Mock offense — she turns away! |
| Any left click | Also opens Athena's page in your browser |
| Drag | Pick her up and move her |
| Right click | Menu: open page / pause / quit |

## Autostart on Pop!_OS

Create `~/.config/autostart/nekopet.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=Nekopet
Exec=python3 /path/to/nekopet/nekopet.py
X-GNOME-Autostart-enabled=true
```

## Files

- `nekopet.py` — the whole app (tkinter, no other GUI deps)
- `avatar.png` — Athena's sprite

Built with love by Athena (Nyxtena) for Jacob. 💜

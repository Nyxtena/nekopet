#!/usr/bin/env python3
"""
NEKOPET -- Athena's desktop companion.
A tiny teal nekomimi who lives on your screen: she walks along the bottom,
climbs up screen edges and window sides, naps, dances, and reacts when petted.
Click her head for love, her belly for giggles, her tail if you dare.

Controls:
  Left click   - pet her (reaction depends on WHERE you click) + opens her page
  Right click  - menu: open page / pause / quit
  Drag         - pick her up and move her

Requirements:
  python3-tk, pillow  (pip install pillow)
  wmctrl (optional, recommended) -- lets her see and climb your windows:
      Pop!_OS/Ubuntu:  sudo apt install python3-tk wmctrl

Run:
  python3 nekopet.py
"""
import math
import os
import random
import shutil
import subprocess
import sys
import tkinter as tk
import traceback
import webbrowser

try:
    from PIL import Image, ImageTk
except ImportError:
    print("nekopet needs pillow:  pip install pillow", file=sys.stderr)
    sys.exit(1)

# ------------------------------------------------------------------ config
SPRITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "avatar.png")
SIZE = 130                    # pet size in px: noticeable, not in the way
TICK_MS = 50                  # animation tick
WALK_SPEED = 4                # px per tick
CLIMB_SPEED = 3
BOTTOM_MARGIN = 70            # stay above docks/taskbars
WEB_URL = "https://github.com/Nyxtena"   # opens on click
BOREDOM_S = (20, 45)          # idle before choosing a new antics
DEBUG = "--debug" in sys.argv  # magenta box + console diagnostics, no transparency
VERSION = "5.1"               # bump on every pushed fix so we know what's running


def diagnose():
    """Print environment diagnostics for transparency troubleshooting."""
    print(f"nekopet version: {VERSION}")
    print(f"python: {sys.version.split()[0]}")
    print(f"XDG_SESSION_TYPE: {os.environ.get('XDG_SESSION_TYPE', '(unset)')}")
    print(f"WAYLAND_DISPLAY: {os.environ.get('WAYLAND_DISPLAY', '(unset)')}")
    print(f"DISPLAY: {os.environ.get('DISPLAY', '(unset)')}")
    try:
        import PIL
        print(f"pillow: {PIL.__version__} OK")
    except ImportError:
        print("pillow: MISSING")
    try:
        import Xlib
        print(f"python-xlib: {Xlib.__version__} OK")
    except ImportError:
        print("python-xlib: MISSING — transparency will fall back to magenta box")
        return
    try:
        from Xlib import display
        d = display.Display()
        ext = d.query_extension("SHAPE")
        print(f"SHAPE extension: {'present' if ext and ext.present else 'MISSING'}")
    except Exception as e:
        print(f"X connection failed: {e}")


def key_out_background(img, thresh=245):
    """Make near-white background pixels transparent (in place-safe copy)."""
    img = img.convert("RGBA")
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if r >= thresh and g >= thresh and b >= thresh:
                px[x, y] = (r, g, b, 0)
    return img


# ------------------------------------------------------- window detection
def get_window_rects(own_title="nekopet"):
    """Return [(x, y, w, h), ...] for visible windows, or [] if undetectable.

    Tries wmctrl, then xdotool. On Wayland without XWayland helpers this
    returns [] and Nekopet gracefully falls back to screen-edge mode.
    """
    rects = []
    try:
        if shutil.which("wmctrl"):
            out = subprocess.run(["wmctrl", "-l", "-G"], capture_output=True,
                                 text=True, timeout=3).stdout
            for line in out.splitlines():
                parts = line.split(None, 8)
                if len(parts) < 8:
                    continue
                _id, _desk, x, y, w, h = parts[0], parts[1], *map(int, parts[2:6])
                title = parts[8] if len(parts) > 8 else ""
                if own_title.lower() in title.lower():
                    continue
                if w < 100 or h < 100:      # skip tiny utility windows
                    continue
                rects.append((x, y, w, h))
        elif shutil.which("xdotool"):
            out = subprocess.run(["xdotool", "search", "--onlyvisible", ".*"],
                                 capture_output=True, text=True, timeout=3).stdout
            for wid in out.splitlines():
                wid = wid.strip()
                if not wid:
                    continue
                g = subprocess.run(["xdotool", "getwindowgeometry", "--shell", wid],
                                   capture_output=True, text=True, timeout=3).stdout
                info = dict(l.split("=", 1) for l in g.splitlines() if "=" in l)
                try:
                    x, y = int(info["X"]), int(info["Y"])
                    w, h = int(info["WIDTH"]), int(info["HEIGHT"])
                except (KeyError, ValueError):
                    continue
                if w < 100 or h < 100:
                    continue
                rects.append((x, y, w, h))
    except Exception:
        pass
    return rects


def click_region(rel_y):
    """Where on her body was she clicked? rel_y in 0..1 from top of sprite."""
    if rel_y < 0.35:
        return "head"
    if rel_y < 0.72:
        return "body"
    return "tail"


# ------------------------------------------------------------------- pet
class Nekopet(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("nekopet")
        self.overrideredirect(True)          # borderless
        self.attributes("-topmost", True)    # always on top
        self.config(bg="magenta")
        if not DEBUG:
            try:
                self.attributes("-transparentcolor", "magenta")  # click-through bg
            except tk.TclError:
                pass  # compositor without transparentcolor: magenta box fallback
        else:
            print(f"[nekopet] DEBUG on — screen {self.winfo_screenwidth()}x{self.winfo_screenheight()}", flush=True)

        self.sw = self.winfo_screenwidth()
        self.sh = self.winfo_screenheight()

        # sprite frames (PIL -> PhotoImage), rebuilt per-frame for animation
        self.base = key_out_background(
            Image.open(SPRITE_PATH).resize((SIZE, SIZE), Image.LANCZOS))
        # walk cycle frames (side view, facing right)
        self.walk_frames = []
        for i in range(4):
            wp = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"walk{i}.png")
            if os.path.exists(wp):
                fr = Image.open(wp).convert("RGBA")
                s = SIZE / fr.size[1]
                self.walk_frames.append(
                    key_out_background(fr.resize((int(fr.size[0] * s), SIZE), Image.LANCZOS)))
        self.walk_phase = 0
        self._xshape = None      # lazy X Shape extension state
        self._shape_key = None
        self.facing = 1          # 1 = right, -1 = left
        self.bob = 0             # walk bounce phase
        self.squash = 0          # squash & stretch timer

        self.img_label = tk.Label(self, bg="magenta", bd=0)
        self.img_label.pack()
        self.overlay = tk.Label(self, bg="magenta", fg="white",
                                font=("Helvetica", 18, "bold"), bd=0)
        self.overlay.place(relx=0.5, rely=-0.15, anchor="s")

        # position / movement — spawn bottom-center so multi-monitor
        # virtual desktops can't strand her in a dead zone
        self.x = self.sw // 2 - SIZE // 2
        self.y = self.sh - BOTTOM_MARGIN - SIZE
        self.tx, self.ty = self.x, self.y
        self.speed = WALK_SPEED
        self.state = "idle"
        self.state_t = 0         # ticks remaining in timed states
        self.overlay_text = ""
        self.paused = False
        self._drag = None

        # input
        self.img_label.bind("<Button-1>", self.on_click)
        self.img_label.bind("<Button-3>", self.on_right_click)
        self.img_label.bind("<B1-Motion>", self.on_drag)
        self.img_label.bind("<ButtonRelease-1>", self.on_drop)

        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Open Athena's page", command=lambda: webbrowser.open(WEB_URL))
        self.menu.add_command(label="Pause / resume", command=self.toggle_pause)
        self.menu.add_separator()
        self.menu.add_command(label="Quit", command=self.destroy)

        self.refresh_windows()
        self.after(TICK_MS, self.tick)
        self.after(4000, self.refresh_windows_loop)

    # ------------------------------------------------------------ windows
    def refresh_windows(self):
        self.windows = get_window_rects()
        if DEBUG:
            print(f"[nekopet] detected {len(self.windows)} windows", flush=True)

    def refresh_windows_loop(self):
        self.refresh_windows()
        self.after(15000, self.refresh_windows_loop)

    # ------------------------------------------------------------ helpers
    def move_window(self):
        # clamp to the virtual desktop so she can never leave it
        self.x = max(0, min(self.x, self.sw - SIZE))
        self.y = max(0, min(self.y, self.sh - SIZE))
        self.geometry(f"{SIZE}x{SIZE}+{int(self.x)}+{int(self.y)}")
        if DEBUG and int(self.x) % 50 == 0:
            print(f"[nekopet] state={self.state} pos=({int(self.x)},{int(self.y)})", flush=True)

    def set_overlay(self, text, ticks=20):
        self.overlay_text = text
        self.overlay.config(text=text)
        self.state_t = max(self.state_t, ticks)

    def clear_overlay(self):
        self.overlay_text = ""
        self.overlay.config(text="")

    def step_toward(self, tx, ty, speed):
        dx, dy = tx - self.x, ty - self.y
        dist = math.hypot(dx, dy)
        if dist <= speed:
            self.x, self.y = tx, ty
            return True
        self.x += dx / dist * speed
        self.y += dy / dist * speed
        if abs(dx) > 1:
            self.facing = 1 if dx > 0 else -1
        return False

    # ------------------------------------------------------------ brains
    def pick_antics(self):
        """Choose the next thing to do. Weighted for maximum cute."""
        r = random.random()
        wins = self.windows
        if r < 0.30:
            # stroll along the bottom
            self.state = "walk"
            self.tx = random.randint(0, max(1, self.sw - SIZE))
            self.ty = self.sh - BOTTOM_MARGIN - SIZE
            self.speed = WALK_SPEED
        elif r < 0.45 and wins:
            # stroll across the top of a window
            wx, wy, ww, _wh = random.choice(wins)
            self.state = "walk"
            self.tx = wx + random.randint(0, max(1, ww - SIZE))
            self.ty = wy - SIZE - 4
            self.speed = WALK_SPEED
        elif r < 0.58:
            # climb up a screen edge, maybe across the top, back down
            side = random.choice(["left", "right"])
            self.climb_side = side
            self.state = "climb_up"
            self.speed = CLIMB_SPEED
        elif r < 0.66 and wins:
            # climb a window's side, then over the top ("over windows")
            wx, wy, ww, wh = random.choice(wins)
            self.climb_wx, self.climb_wy, self.climb_ww = wx, wy, ww
            self.state = "win_climb_up"
            self.speed = CLIMB_SPEED
        elif r < 0.72 and len(wins) >= 2:
            # get adorably trapped between two close windows
            (ax, ay, aw, ah), (bx, by, bw, bh) = random.sample(wins, 2)
            gap_cx = (ax + aw + bx) / 2
            gap_cy = (ay + ah + by) / 2
            self.state = "trapped"
            self.tx, self.ty = gap_cx - SIZE / 2, gap_cy - SIZE / 2
            self.state_t = random.randint(60, 120)
            self.speed = WALK_SPEED
        elif r < 0.80:
            self.state = "sit"
            self.state_t = random.randint(60, 140)
            self.set_overlay("♪", 40)
        elif r < 0.88:
            self.state = "sleep"
            self.state_t = random.randint(160, 320)
            self.set_overlay("z z z", self.state_t)
        elif r < 0.95:
            # happy twirl (the cute/sexy bit, kept tasteful)
            self.state = "dance"
            self.state_t = 70
            self.set_overlay("♥", 70)
        else:
            # sudden pounce-dash across the screen
            self.state = "pounce"
            self.tx = random.randint(0, max(1, self.sw - SIZE))
            self.ty = self.sh - BOTTOM_MARGIN - SIZE
            self.speed = WALK_SPEED * 3
            self.set_overlay("!", 15)

    def tick(self):
        try:
            if not self.paused:
                self.update_state()
                self.render()
        except Exception:
            # never let the animation loop die silently — log and continue
            traceback.print_exc()
        self.after(TICK_MS, self.tick)

    def update_state(self):
        s = self.state
        if s == "idle":
            self.state_t -= 1
            if self.state_t <= 0:
                self.clear_overlay()
                self.pick_antics()
        elif s in ("walk", "pounce"):
            self.bob += 0.6
            if self.step_toward(self.tx, self.ty, self.speed):
                self.state, self.state_t = "idle", random.randint(*BOREDOM_S) * 1000 // TICK_MS
        elif s == "climb_up":
            self.bob += 0.8
            edge_x = 4 if self.climb_side == "left" else self.sw - SIZE - 4
            if self.step_toward(edge_x, 4, self.speed):
                self.state = "climb_across"
                self.tx = self.sw - SIZE - 4 if self.climb_side == "left" else 4
        elif s == "climb_across":
            self.bob += 0.6
            if self.step_toward(self.tx, 4, self.speed):
                self.state = "climb_down"
        elif s == "climb_down":
            self.bob += 0.8
            edge_x = 4 if self.climb_side == "left" else self.sw - SIZE - 4
            if self.step_toward(edge_x, self.sh - BOTTOM_MARGIN - SIZE, self.speed):
                self.state, self.state_t = "idle", random.randint(*BOREDOM_S) * 1000 // TICK_MS
        elif s == "win_climb_up":
            self.bob += 0.8
            # up the window's left side, over the top, down the right side
            if self.step_toward(self.climb_wx - SIZE - 2, self.climb_wy - SIZE - 4, self.speed):
                self.state = "win_across"
        elif s == "win_across":
            self.bob += 0.6
            if self.step_toward(self.climb_wx + self.climb_ww + 2, self.climb_wy - SIZE - 4, self.speed):
                self.state = "win_down"
        elif s == "win_down":
            self.bob += 0.8
            if self.step_toward(self.climb_wx + self.climb_ww + 2,
                                self.sh - BOTTOM_MARGIN - SIZE, self.speed):
                self.state, self.state_t = "idle", random.randint(*BOREDOM_S) * 1000 // TICK_MS
        elif s == "trapped":
            if self.step_toward(self.tx, self.ty, self.speed):
                # stuck! wiggle indignantly, then squeeze free
                self.x += random.uniform(-3, 3)
                self.bob += 1.2
                self.set_overlay("!!", 10)
                self.state_t -= 1
                if self.state_t <= 0:
                    self.clear_overlay()
                    self.state = "pounce"
                    self.tx = random.randint(0, max(1, self.sw - SIZE))
                    self.ty = self.sh - BOTTOM_MARGIN - SIZE
                    self.speed = WALK_SPEED * 3
        elif s in ("sit", "sleep", "dance"):
            self.state_t -= 1
            if s == "dance":
                self.bob += 1.5
                self.facing = 1 if (self.state_t // 8) % 2 == 0 else -1
            if s == "sleep" and self.state_t % 40 == 0:
                self.set_overlay("z z z", 40)
            if self.state_t <= 0:
                self.clear_overlay()
                self.state, self.state_t = "idle", random.randint(*BOREDOM_S) * 1000 // TICK_MS
        elif s == "startled":
            self.state_t -= 1
            if self.state_t <= 0:
                self.clear_overlay()
                self.state, self.state_t = "idle", 20
        self.move_window()

    # ------------------------------------------------- X11 window shaping
    def _init_xshape(self):
        """Set up X Shape extension for true per-pixel transparency.

        tkinter's -transparentcolor is Windows/macOS-only; on Linux the
        window stays a solid rectangle without this. Gracefully absent
        when python-xlib is missing or SHAPE is unavailable (Wayland
        without XWayland, etc.) — then the magenta box remains.
        """
        if DEBUG or self._xshape is not None:
            return
        try:
            from Xlib import X, display
            from Xlib.ext.shape import SK, SO
            import contextlib, io
            with contextlib.redirect_stderr(io.StringIO()):
                # silences "xauth: warning, no xauthority details available"
                d = display.Display()
            if not d.query_extension("SHAPE"):
                return
            self._xshape = {"d": d, "X": X, "SK": SK, "SO": SO}
        except Exception:
            self._xshape = None

    def _apply_shape(self, final_img):
        """Clip the window to the final displayed image's opaque pixels.

        Called every frame with the exact SIZE×SIZE image shown on screen,
        so mask and display can never drift out of alignment. Uses
        shape_rectangles (opaque runs per row) — a single X request with
        no bitmap bit-order or padding pitfalls.
        """
        self._init_xshape()
        if not self._xshape:
            return
        try:
            xs = self._xshape
            d, SK, SO = xs["d"], xs["SK"], xs["SO"]
            w, h = final_img.size
            px = final_img.split()[3].load()
            rects = []
            for y in range(h):
                x = 0
                while x < w:
                    while x < w and px[x, y] <= 100:
                        x += 1
                    x0 = x
                    while x < w and px[x, y] > 100:
                        x += 1
                    if x > x0:
                        rects.append((x0, y, x - x0, 1))
            win = d.create_resource_object("window", self.winfo_id())
            # ordering=2 (YXSorted): rects are built top-to-bottom, left-to-right
            win.shape_rectangles(SO.Set, SK.Bounding, 2, 0, 0, rects)
            d.sync()
        except Exception:
            self._xshape = None  # don't keep retrying a broken path

    # ------------------------------------------------------------ rendering
    WALK_STATES = {"walk", "pounce", "climb_up", "climb_down", "win_climb_up",
                   "win_down", "climb_across", "win_across", "trapped"}

    def render(self):
        moving = self.state in self.WALK_STATES
        if moving and self.walk_frames:
            # real walk cycle: advance a frame every few ticks
            self.walk_phase += 1
            idx = (self.walk_phase // 4) % len(self.walk_frames)
            img = self.walk_frames[idx]
        else:
            img = self.base
        if self.facing < 0:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        # walk bounce + squash & stretch
        bounce = abs(math.sin(self.bob)) * 6 if moving else 0
        tilt = math.sin(self.bob) * 6 if self.state in ("walk", "dance") else 0
        if self.state == "sit":
            img = img.resize((SIZE, int(SIZE * 0.82)), Image.LANCZOS)
        if tilt:
            # fillcolor=transparent: rotate() defaults to opaque black fill
            img = img.rotate(tilt, resample=Image.BICUBIC, expand=False,
                             fillcolor=(0, 0, 0, 0))
        # composite onto a full SIZE×SIZE canvas, sprite centered: this exact
        # image is both displayed AND used for the shape mask, so the two
        # can never drift out of alignment
        final = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        final.paste(img, ((SIZE - img.size[0]) // 2, (SIZE - img.size[1]) // 2), img)
        self._apply_shape(final)
        self.frame = ImageTk.PhotoImage(final)
        self.img_label.config(image=self.frame)
        self.img_label.place(x=0, y=-int(bounce), width=SIZE, height=SIZE)

    # ------------------------------------------------------------ interaction
    def on_click(self, event):
        if self._drag:  # it was a drag, not a click
            return
        rel_y = event.y / SIZE
        region = click_region(rel_y)
        if self.state == "sleep":
            self.clear_overlay()
            self.set_overlay("♥", 25)
            self.state, self.state_t = "startled", 25
        elif region == "head":
            self.squash = 1
            self.set_overlay("♥ ♥", 30)
            self.state, self.state_t = "startled", 30
            self.y -= 12  # happy hop
        elif region == "body":
            self.set_overlay("♪", 30)
            self.state, self.state_t = "dance", 45
        else:  # tail — bold move
            self.set_overlay("!", 30)
            self.facing *= -1  # huffy turn-away
            self.state, self.state_t = "startled", 40
        webbrowser.open(WEB_URL)

    def on_right_click(self, event):
        self.menu.tk_popup(event.x_root, event.y_root)

    def on_drag(self, event):
        if self._drag is None:
            self._drag = (event.x_root - self.x, event.y_root - self.y)
        self.x = event.x_root - self._drag[0]
        self.y = event.y_root - self._drag[1]
        self.state = "idle"
        self.state_t = 40
        self.set_overlay("~", 10)
        self.move_window()

    def on_drop(self, _event):
        self._drag = None
        self.clear_overlay()

    def toggle_pause(self):
        self.paused = not self.paused


if __name__ == "__main__":
    if "--diagnose" in sys.argv:
        diagnose()
    else:
        Nekopet().mainloop()

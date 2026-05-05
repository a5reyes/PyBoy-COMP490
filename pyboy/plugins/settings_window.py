#
# License: See LICENSE.md file
# GitHub: https://github.com/Baekalfen/PyBoy
#
"""
Settings window plugin – opens a Tkinter panel when the user presses F2.

All Tkinter work happens on the main thread: `tk_root.update()` is called
from `post_tick()` so the emulator loop and the UI share one thread and
there are no thread-safety concerns.
"""

from pyboy.plugins.base_plugin import PyBoyPlugin
from pyboy.utils import WindowEvent

import pyboy as _pyboy_pkg

logger = _pyboy_pkg.logging.get_logger(__name__)

# DMG palette presets (name -> (color0, color1, color2, color3))
# Colors are 24-bit RGB integers, lightest-to-darkest.
DMG_PALETTE_PRESETS = {
    "Grey":           (0xFFFFFF, 0x999999, 0x555555, 0x000000),
    "Classic Green":  (0x9BBC0F, 0x8BAC0F, 0x306230, 0x0F380F),
    "SameBoy DMG":    (0xC6DE8C, 0x84A563, 0x396139, 0x081810),
    "Parchment":      (0xE0DBCD, 0xA89F94, 0x706B64, 0x2B2B26),
    "Mossy":          (0xC4CFA1, 0x8B956D, 0x4D533C, 0x1F1F1C),
}

PALETTE_NAMES = list(DMG_PALETTE_PRESETS.keys())


class SettingsWindow(PyBoyPlugin):
    """
    In-emulator settings panel.

    Press **F2** (or send ``WindowEvent.SETTINGS_TOGGLE``) while a game is
    running to open / close the window.  Changes take effect immediately.

    Settings exposed
    ----------------
    * **Volume** – master sound volume 0–100 %.
    * **Speed**  – emulation speed multiplier 0–5×  (0 = unlimited).
    * **Palette** – DMG colour palette preset (ignored in CGB mode).
    * **Pause**  – pause / resume the emulator.
    """

    argv = []  # no CLI arguments needed

    def __init__(self, pyboy, mb, pyboy_argv):
        super().__init__(pyboy, mb, pyboy_argv)
        self._tk_root = None
        self._open = False

        # Tkinter variable / widget handles (created when the window is opened)
        self._var_volume = None
        self._var_speed = None
        self._var_palette = None
        self._var_pause = None
        self._vol_label = None
        self._palette_preview = None

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------

    def handle_events(self, events):
        for event in events:
            if event == WindowEvent.SETTINGS_TOGGLE:
                if self._open:
                    self._close_window()
                else:
                    self._open_window()
        return events

    def post_tick(self):
        """Drive the Tkinter event loop once per emulator frame."""
        if self._open and self._tk_root is not None:
            try:
                self._tk_root.update()
            except Exception:
                # Window was closed by the OS / WM
                self._open = False
                self._tk_root = None

    def stop(self):
        self._close_window()

    def enabled(self):
        return True

    # ------------------------------------------------------------------
    # Window creation / destruction
    # ------------------------------------------------------------------

    def _open_window(self):
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError:
            logger.warning(
                "tkinter is not available on this system – settings window disabled."
            )
            return

        root = tk.Tk()
        root.title("PyBoy – Settings")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self._close_window)

        # Keep a reference so post_tick() can call update()
        self._tk_root = root

        pad = {"padx": 10, "pady": 6}

        # ── Header ────────────────────────────────────────────────────
        header = tk.Label(
            root,
            text="PyBoy Settings",
            font=("Helvetica", 14, "bold"),
        )
        header.grid(row=0, column=0, columnspan=3, pady=(12, 4))

        separator = ttk.Separator(root, orient="horizontal")
        separator.grid(row=1, column=0, columnspan=3, sticky="ew", **pad)

        # ── Volume ────────────────────────────────────────────────────
        tk.Label(root, text="Volume:", anchor="e").grid(
            row=2, column=0, sticky="e", **pad
        )
        self._var_volume = tk.IntVar(value=self.mb.sound.volume)
        vol_scale = tk.Scale(
            root,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            length=200,
            variable=self._var_volume,
            command=self._on_volume_change,
        )
        vol_scale.grid(row=2, column=1, sticky="w", **pad)
        self._vol_label = tk.Label(
            root, text=f"{self.mb.sound.volume}%", width=5, anchor="w"
        )
        self._vol_label.grid(row=2, column=2, sticky="w")

        # ── Emulation Speed ───────────────────────────────────────────
        tk.Label(root, text="Speed:", anchor="e").grid(
            row=3, column=0, sticky="e", **pad
        )
        current_speed = getattr(self.pyboy, "target_emulationspeed", 1)
        self._var_speed = tk.IntVar(value=current_speed)
        speed_scale = tk.Scale(
            root,
            from_=0,
            to=5,
            orient=tk.HORIZONTAL,
            length=200,
            variable=self._var_speed,
            command=self._on_speed_change,
        )
        speed_scale.grid(row=3, column=1, sticky="w", **pad)
        speed_hint = tk.Label(root, text="(0 = unlimited)", anchor="w", fg="grey")
        speed_hint.grid(row=3, column=2, sticky="w")

        # ── DMG Colour Palette ────────────────────────────────────────
        if not self.cgb:
            separator2 = ttk.Separator(root, orient="horizontal")
            separator2.grid(row=4, column=0, columnspan=3, sticky="ew", **pad)

            tk.Label(root, text="Palette:", anchor="e").grid(
                row=5, column=0, sticky="e", **pad
            )
            self._var_palette = tk.StringVar(value=PALETTE_NAMES[0])
            palette_menu = ttk.Combobox(
                root,
                textvariable=self._var_palette,
                values=PALETTE_NAMES,
                state="readonly",
                width=18,
            )
            palette_menu.grid(row=5, column=1, sticky="w", **pad)
            palette_menu.bind("<<ComboboxSelected>>", self._on_palette_change)

            # Small coloured preview squares
            self._palette_preview = tk.Canvas(
                root, width=80, height=16, bg="white", highlightthickness=0
            )
            self._palette_preview.grid(row=5, column=2, sticky="w")
            self._update_palette_preview()

        # ── Pause / Resume ────────────────────────────────────────────
        separator3 = ttk.Separator(root, orient="horizontal")
        separator3.grid(row=6, column=0, columnspan=3, sticky="ew", **pad)

        self._var_pause = tk.BooleanVar(value=self.pyboy.paused)
        pause_cb = tk.Checkbutton(
            root,
            text="Pause emulation",
            variable=self._var_pause,
            command=self._on_pause_toggle,
        )
        pause_cb.grid(row=7, column=0, columnspan=2, sticky="w", padx=14, pady=4)

        # ── Close button ──────────────────────────────────────────────
        separator4 = ttk.Separator(root, orient="horizontal")
        separator4.grid(row=8, column=0, columnspan=3, sticky="ew", **pad)

        close_btn = ttk.Button(root, text="Close", command=self._close_window)
        close_btn.grid(row=9, column=0, columnspan=3, pady=(4, 12))

        # ── Key hints ─────────────────────────────────────────────────
        hint = tk.Label(
            root,
            text="Tip: press F2 to toggle this window",
            fg="grey",
            font=("Helvetica", 9),
        )
        hint.grid(row=10, column=0, columnspan=3, pady=(0, 8))

        self._open = True

        # Initial render pass
        root.update()

    def _close_window(self):
        if self._tk_root is not None:
            try:
                self._tk_root.destroy()
            except Exception:
                pass
            self._tk_root = None
        self._open = False
        # Reset widget / variable handles so a re-open starts fresh
        self._var_volume = None
        self._var_speed = None
        self._var_palette = None
        self._var_pause = None
        self._vol_label = None
        self._palette_preview = None

    # ------------------------------------------------------------------
    # Callbacks – called by Tkinter on the main thread during update()
    # ------------------------------------------------------------------

    def _on_volume_change(self, value):
        vol = int(float(value))
        self.mb.sound.volume = vol
        if self._vol_label:
            self._vol_label.config(text=f"{vol}%")

    def _on_speed_change(self, value):
        speed = int(float(value))
        self.pyboy.target_emulationspeed = speed

    def _on_palette_change(self, _event=None):
        if self.cgb:
            return  # palette only applies to DMG mode
        name = self._var_palette.get()
        palette = DMG_PALETTE_PRESETS.get(name)
        if palette:
            try:
                self.pyboy.set_color_palette(palette)
            except Exception as exc:
                logger.warning("Could not set colour palette: %s", exc)
        self._update_palette_preview()

    def _on_pause_toggle(self):
        if self._var_pause.get():
            self.pyboy._pause()
        else:
            self.pyboy._unpause()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_palette_preview(self):
        """Draw four tiny colour swatches on the canvas."""
        if self._palette_preview is None or self._var_palette is None:
            return
        name = self._var_palette.get()
        palette = DMG_PALETTE_PRESETS.get(name, DMG_PALETTE_PRESETS[PALETTE_NAMES[0]])
        canvas = self._palette_preview
        canvas.delete("all")
        swatch_w = 20
        for i, color_int in enumerate(palette):
            hex_color = f"#{color_int:06X}"
            x0 = i * swatch_w
            canvas.create_rectangle(x0, 0, x0 + swatch_w, 16, fill=hex_color, outline="")

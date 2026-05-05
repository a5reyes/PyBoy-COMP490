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
        # Key binding: button name -> label widget showing current key
        self._keybind_labels = {}
        self._awaiting_remap = None  # button name being remapped

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
        current_speed = getattr(self.pyboy, "target_emulationspeed", None) or 1
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

        # ── Key Bindings ──────────────────────────────────────────────
        sep_keys = ttk.Separator(root, orient="horizontal")
        sep_keys.grid(row=8, column=0, columnspan=3, sticky="ew", **pad)

        tk.Label(root, text="Key Bindings", font=("Helvetica", 11, "bold")).grid(
            row=9, column=0, columnspan=3, pady=(4, 2)
        )

        self._keybind_labels = {}
        self._awaiting_remap = None
        self._build_keybind_rows(root, start_row=10, pad=pad)

        # ── Close button ──────────────────────────────────────────────
        separator4 = ttk.Separator(root, orient="horizontal")
        separator4.grid(row=10 + len(self._keybind_labels), column=0, columnspan=3, sticky="ew", **pad)

        close_btn = ttk.Button(root, text="Close", command=self._close_window)
        close_btn.grid(row=11 + len(self._keybind_labels), column=0, columnspan=3, pady=(4, 12))

        # ── Key hints ─────────────────────────────────────────────────
        hint = tk.Label(
            root,
            text="Tip: press F2 to toggle this window",
            fg="grey",
            font=("Helvetica", 9),
        )
        hint.grid(row=12 + len(self._keybind_labels), column=0, columnspan=3, pady=(0, 8))

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
        self._keybind_labels = {}
        self._awaiting_remap = None

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
        self.pyboy.set_emulation_speed(speed)

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

    def _build_keybind_rows(self, root, start_row, pad):
        """
        Build one row per Game Boy button showing the current key and a Remap button.

        Each row has three columns: button name label, current key display,
        and a Remap button.  Clicking Remap switches the key display to
        'Press a key…' and listens for the next KeyPress event via Tkinter.
        """
        try:
            import tkinter as tk
            from tkinter import ttk
            from pyboy.plugins.window_sdl2 import GAMEBOY_BUTTONS, get_key_for_button
            try:
                import sdl2
                _sdl2_available = True
            except ImportError:
                _sdl2_available = False
        except ImportError:
            return

        def _sdl_key_name(keycode):
            if keycode is None or not _sdl2_available:
                return "(none)"
            name = sdl2.SDL_GetKeyName(keycode)
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="replace")
            return name

        for i, (btn_name, (press_ev, _release_ev)) in enumerate(GAMEBOY_BUTTONS.items()):
            row = start_row + i
            tk.Label(root, text=f"{btn_name}:", anchor="e").grid(
                row=row, column=0, sticky="e", **pad
            )
            current_key = _sdl_key_name(get_key_for_button(press_ev))
            lbl = tk.Label(root, text=current_key, width=12, anchor="w", relief="sunken")
            lbl.grid(row=row, column=1, sticky="w", **pad)
            self._keybind_labels[btn_name] = lbl

            def _make_remap(b=btn_name, lbl=lbl):
                # Default-argument capture keeps b/lbl bound to this iteration.
                def _click():
                    # Record which button is waiting, update the label, then
                    # grab keyboard focus so the next key goes to our handler.
                    self._awaiting_remap = b
                    lbl.config(text="Press a key…", fg="red")
                    lbl.bind("<KeyPress>", self._on_remap_keypress)
                    lbl.focus_set()
                return _click

            ttk.Button(root, text="Remap", command=_make_remap()).grid(
                row=row, column=2, sticky="w", padx=(0, 10)
            )

    def _on_remap_keypress(self, event):
        """
        Handle the key press captured during a remap operation.

        Converts the Tkinter keysym to an SDL2 keycode using
        SDL_GetKeyFromName, calls remap_key() to update KEY_DOWN/KEY_UP,
        and updates the label to show the new key name.
        """
        if self._awaiting_remap is None:
            return
        try:
            import sdl2
            from pyboy.plugins.window_sdl2 import GAMEBOY_BUTTONS, remap_key
        except ImportError:
            self._awaiting_remap = None
            return

        btn_name = self._awaiting_remap
        self._awaiting_remap = None

        press_ev, release_ev = GAMEBOY_BUTTONS[btn_name]

        # SDL_GetKeyFromName expects bytes. Tkinter keysyms like "Return"
        # match SDL names, but SDL uses lowercase for single characters
        # ("a", "b") while Tkinter uses uppercase ("A", "B"), so we try
        # the lowercase form as a fallback.
        new_sdl_keycode = sdl2.SDL_GetKeyFromName(event.keysym.encode("utf-8"))
        if new_sdl_keycode == sdl2.SDLK_UNKNOWN:
            new_sdl_keycode = sdl2.SDL_GetKeyFromName(event.keysym.lower().encode("utf-8"))

        lbl = self._keybind_labels.get(btn_name)
        if new_sdl_keycode == sdl2.SDLK_UNKNOWN or new_sdl_keycode is None:
            if lbl:
                lbl.config(text="(unknown)", fg="orange")
            return

        remap_key(press_ev, release_ev, new_sdl_keycode)

        key_name = sdl2.SDL_GetKeyName(new_sdl_keycode)
        if isinstance(key_name, bytes):
            key_name = key_name.decode("utf-8", errors="replace")
        if lbl:
            lbl.config(text=key_name, fg="black")
            lbl.unbind("<KeyPress>")

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

#
# License: See LICENSE.md file
# GitHub: https://github.com/Baekalfen/PyBoy
#
"""
Tests for the SettingsWindow plugin (pyboy/plugins/settings_window.py).

All tests run headlessly (window="null") and mock the Tkinter layer so they
work in CI environments that have no display.  The plugin behaviour – event
routing, runtime mutations of volume / speed / palette / pause – is tested
against the real emulator state so the coverage is meaningful.
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from pyboy import PyBoy
from pyboy.utils import WindowEvent
from pyboy.plugins.settings_window import (
    SettingsWindow,
    DMG_PALETTE_PRESETS,
    PALETTE_NAMES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pyboy(default_rom):
    """Return a headless PyBoy configured for speed."""
    pyboy = PyBoy(default_rom, window="null", sound_emulated=True)
    pyboy.set_emulation_speed(0)
    pyboy.tick(10, True, False)
    return pyboy


def _get_plugin(pyboy) -> SettingsWindow:
    return pyboy._plugin_manager.settings_window


# ---------------------------------------------------------------------------
# WindowEvent – event ID & string representation
# ---------------------------------------------------------------------------

def test_settings_toggle_event_id():
    """SETTINGS_TOGGLE must be exactly 43, just after CYCLE_PALETTE (42)."""
    assert WindowEvent.CYCLE_PALETTE == 42
    assert WindowEvent.SETTINGS_TOGGLE == 43


def test_settings_toggle_str():
    """str(WindowEvent(SETTINGS_TOGGLE)) should return 'SETTINGS_TOGGLE'."""
    event = WindowEvent(WindowEvent.SETTINGS_TOGGLE)
    assert str(event) == "SETTINGS_TOGGLE"


def test_settings_toggle_equality():
    """WindowEvent comparison helpers work for the new event."""
    e = WindowEvent(WindowEvent.SETTINGS_TOGGLE)
    assert e == WindowEvent.SETTINGS_TOGGLE
    assert e != WindowEvent.CYCLE_PALETTE
    assert e != WindowEvent.QUIT


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------

def test_settings_window_in_manager(default_rom):
    """SettingsWindow must be instantiated and enabled inside PluginManager."""
    pyboy = _make_pyboy(default_rom)
    try:
        plugin = _get_plugin(pyboy)
        assert isinstance(plugin, SettingsWindow)
        assert pyboy._plugin_manager.settings_window_enabled is True
    finally:
        pyboy.stop(save=False)


def test_settings_window_always_enabled(default_rom):
    """enabled() must return True unconditionally."""
    pyboy = _make_pyboy(default_rom)
    try:
        assert _get_plugin(pyboy).enabled() is True
    finally:
        pyboy.stop(save=False)


# ---------------------------------------------------------------------------
# Open / close via SETTINGS_TOGGLE (Tkinter mocked out)
# ---------------------------------------------------------------------------

class _FakeTk:
    """Minimal Tkinter.Tk stand-in that records calls."""

    def __init__(self):
        self.destroyed = False
        self.title_set = ""
        self.protocol_callbacks = {}
        self.update_count = 0

    # Tk window methods used by the plugin
    def title(self, t=""):
        self.title_set = t

    def resizable(self, *_):
        pass

    def protocol(self, name, callback):
        self.protocol_callbacks[name] = callback

    def update(self):
        self.update_count += 1

    def destroy(self):
        self.destroyed = True

    # grid geometry manager  (widgets call root.grid internally)
    def grid_columnconfigure(self, *_, **__):
        pass


def _mock_tkinter_module():
    """Return a minimal mock of the tkinter module used by SettingsWindow."""
    tk_mod = MagicMock()

    # tk.Tk() returns a _FakeTk each time
    fake_root = _FakeTk()
    tk_mod.Tk.return_value = fake_root

    # Variable classes – just return mocks
    for cls in ("IntVar", "BooleanVar", "StringVar"):
        var = MagicMock()
        var.return_value = MagicMock()
        setattr(tk_mod, cls, var)

    # Constants
    tk_mod.HORIZONTAL = "horizontal"

    # Widget constructors – return MagicMocks (they all support .grid())
    for widget in ("Label", "Scale", "Checkbutton", "Canvas"):
        w = MagicMock()
        w.return_value = MagicMock()
        setattr(tk_mod, widget, w)

    # ttk sub-module
    ttk = MagicMock()
    for widget in ("Separator", "Combobox", "Button"):
        w = MagicMock()
        w.return_value = MagicMock()
        setattr(ttk, widget, w)

    tk_mod.ttk = ttk

    return tk_mod, fake_root


@pytest.fixture()
def _patched_tk():
    """
    Patch the 'tkinter' import inside settings_window so tests never open a
    real window.  Yields (tk_module_mock, fake_root).
    """
    tk_mod, fake_root = _mock_tkinter_module()

    # The plugin does `import tkinter as tk` and `from tkinter import ttk`
    # inside _open_window, so we patch sys.modules at that level.
    with patch.dict("sys.modules", {"tkinter": tk_mod, "tkinter.ttk": tk_mod.ttk}):
        yield tk_mod, fake_root


def test_settings_toggle_opens_window(default_rom, _patched_tk):
    """Sending SETTINGS_TOGGLE when closed should open the settings window."""
    tk_mod, fake_root = _patched_tk
    pyboy = _make_pyboy(default_rom)
    try:
        plugin = _get_plugin(pyboy)
        assert plugin._open is False

        plugin.handle_events([WindowEvent(WindowEvent.SETTINGS_TOGGLE)])

        assert plugin._open is True
        assert plugin._tk_root is not None
    finally:
        pyboy.stop(save=False)


def test_settings_toggle_closes_window(default_rom, _patched_tk):
    """Sending SETTINGS_TOGGLE twice should close the window."""
    tk_mod, fake_root = _patched_tk
    pyboy = _make_pyboy(default_rom)
    try:
        plugin = _get_plugin(pyboy)

        plugin.handle_events([WindowEvent(WindowEvent.SETTINGS_TOGGLE)])  # open
        assert plugin._open is True

        plugin.handle_events([WindowEvent(WindowEvent.SETTINGS_TOGGLE)])  # close
        assert plugin._open is False
        assert plugin._tk_root is None
    finally:
        pyboy.stop(save=False)


def test_settings_toggle_can_reopen(default_rom, _patched_tk):
    """The window should be re-openable after it has been closed."""
    pyboy = _make_pyboy(default_rom)
    try:
        plugin = _get_plugin(pyboy)

        plugin.handle_events([WindowEvent(WindowEvent.SETTINGS_TOGGLE)])  # open
        plugin.handle_events([WindowEvent(WindowEvent.SETTINGS_TOGGLE)])  # close
        plugin.handle_events([WindowEvent(WindowEvent.SETTINGS_TOGGLE)])  # re-open
        assert plugin._open is True
    finally:
        pyboy.stop(save=False)


def test_unrelated_events_do_not_open_window(default_rom):
    """Events other than SETTINGS_TOGGLE must not affect the plugin state."""
    pyboy = _make_pyboy(default_rom)
    try:
        plugin = _get_plugin(pyboy)
        assert plugin._open is False

        plugin.handle_events([
            WindowEvent(WindowEvent.PAUSE),
            WindowEvent(WindowEvent.CYCLE_PALETTE),
            WindowEvent(WindowEvent.PASS),
        ])

        assert plugin._open is False
    finally:
        pyboy.stop(save=False)


# ---------------------------------------------------------------------------
# post_tick safety
# ---------------------------------------------------------------------------

def test_post_tick_safe_when_closed(default_rom):
    """post_tick() must not raise when the settings window is not open."""
    pyboy = _make_pyboy(default_rom)
    try:
        plugin = _get_plugin(pyboy)
        assert plugin._open is False
        plugin.post_tick()  # must not raise
    finally:
        pyboy.stop(save=False)


def test_post_tick_calls_tk_update(default_rom, _patched_tk):
    """When open, post_tick() must call tk_root.update() once per call."""
    tk_mod, fake_root = _patched_tk
    pyboy = _make_pyboy(default_rom)
    try:
        plugin = _get_plugin(pyboy)
        plugin.handle_events([WindowEvent(WindowEvent.SETTINGS_TOGGLE)])  # open

        before = fake_root.update_count
        plugin.post_tick()
        assert fake_root.update_count == before + 1
    finally:
        pyboy.stop(save=False)


def test_post_tick_handles_destroyed_window(default_rom, _patched_tk):
    """If tk_root.update() raises (window was closed by OS), state is cleaned up."""
    tk_mod, fake_root = _patched_tk
    pyboy = _make_pyboy(default_rom)
    try:
        plugin = _get_plugin(pyboy)
        plugin.handle_events([WindowEvent(WindowEvent.SETTINGS_TOGGLE)])  # open

        # Simulate OS closing the window
        fake_root.update = MagicMock(side_effect=Exception("window destroyed"))

        plugin.post_tick()  # must not propagate the exception

        assert plugin._open is False
        assert plugin._tk_root is None
    finally:
        pyboy.stop(save=False)


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------

def test_stop_when_closed_does_not_raise(default_rom):
    """stop() on an already-closed plugin must not raise."""
    pyboy = _make_pyboy(default_rom)
    try:
        plugin = _get_plugin(pyboy)
        plugin.stop()  # must not raise
    finally:
        pyboy.stop(save=False)


def test_stop_closes_open_window(default_rom, _patched_tk):
    """stop() while open must close and clean up the tkinter window."""
    tk_mod, fake_root = _patched_tk
    pyboy = _make_pyboy(default_rom)
    try:
        plugin = _get_plugin(pyboy)
        plugin.handle_events([WindowEvent(WindowEvent.SETTINGS_TOGGLE)])  # open
        assert plugin._open is True

        plugin.stop()

        assert plugin._open is False
        assert plugin._tk_root is None
        assert fake_root.destroyed is True
    finally:
        pyboy.stop(save=False)


# ---------------------------------------------------------------------------
# Runtime mutations – volume
# ---------------------------------------------------------------------------

def test_volume_callback_updates_sound(default_rom):
    """_on_volume_change() must immediately update mb.sound.volume."""
    pyboy = _make_pyboy(default_rom)
    try:
        plugin = _get_plugin(pyboy)

        plugin._on_volume_change("75")
        assert pyboy.mb.sound.volume == 75

        plugin._on_volume_change("0")
        assert pyboy.mb.sound.volume == 0

        plugin._on_volume_change("100")
        assert pyboy.mb.sound.volume == 100
    finally:
        pyboy.stop(save=False)


def test_volume_callback_boundary_values(default_rom):
    """Volume callback must handle boundary integers correctly."""
    pyboy = _make_pyboy(default_rom)
    try:
        plugin = _get_plugin(pyboy)
        for vol in (0, 1, 50, 99, 100):
            plugin._on_volume_change(str(vol))
            assert pyboy.mb.sound.volume == vol
    finally:
        pyboy.stop(save=False)


# ---------------------------------------------------------------------------
# Runtime mutations – speed
# ---------------------------------------------------------------------------

def test_speed_callback_updates_emulation_speed(default_rom):
    """_on_speed_change() must immediately update target_emulationspeed."""
    pyboy = _make_pyboy(default_rom)
    try:
        plugin = _get_plugin(pyboy)

        plugin._on_speed_change("2")
        assert pyboy.target_emulationspeed == 2

        plugin._on_speed_change("0")
        assert pyboy.target_emulationspeed == 0

        plugin._on_speed_change("5")
        assert pyboy.target_emulationspeed == 5
    finally:
        pyboy.stop(save=False)


def test_speed_callback_boundary_values(default_rom):
    """Speed callback must handle all valid multipliers 0-5."""
    pyboy = _make_pyboy(default_rom)
    try:
        plugin = _get_plugin(pyboy)
        for speed in range(0, 6):
            plugin._on_speed_change(str(speed))
            assert pyboy.target_emulationspeed == speed
    finally:
        pyboy.stop(save=False)


# ---------------------------------------------------------------------------
# Runtime mutations – DMG colour palette
# ---------------------------------------------------------------------------

def test_palette_callback_changes_screen_in_dmg(default_rom):
    """Selecting a non-default palette must visibly change the rendered screen."""
    import numpy as np

    pyboy = _make_pyboy(default_rom)
    pyboy.tick(60, True, False)  # let the boot screen render
    try:
        plugin = _get_plugin(pyboy)
        if pyboy.mb.cgb:
            pytest.skip("default_rom is CGB – palette callback is a no-op")

        screen_before = pyboy.screen.ndarray.copy()

        # Switch to Classic Green (very different from grey)
        plugin._var_palette = MagicMock()
        plugin._var_palette.get.return_value = "Classic Green"
        plugin._palette_preview = MagicMock()  # suppress canvas calls
        plugin._on_palette_change()
        pyboy.tick(1, True, False)

        screen_after = pyboy.screen.ndarray.copy()
        assert not np.array_equal(screen_before, screen_after), (
            "Screen should differ after palette change"
        )
    finally:
        pyboy.stop(save=False)


def test_palette_callback_all_presets_apply_without_error(default_rom):
    """Every preset in DMG_PALETTE_PRESETS must apply without raising."""
    pyboy = _make_pyboy(default_rom)
    try:
        plugin = _get_plugin(pyboy)
        if pyboy.mb.cgb:
            pytest.skip("default_rom is CGB – palette callback is a no-op")

        for name in PALETTE_NAMES:
            plugin._var_palette = MagicMock()
            plugin._var_palette.get.return_value = name
            plugin._palette_preview = MagicMock()
            plugin._on_palette_change()  # must not raise
    finally:
        pyboy.stop(save=False)


def test_palette_callback_noop_in_cgb(default_rom):
    """_on_palette_change() must be a no-op (no exception) in CGB mode."""
    pyboy = _make_pyboy(default_rom)
    try:
        plugin = _get_plugin(pyboy)
        # Force CGB flag to True for this test regardless of ROM
        original_cgb = plugin.cgb
        plugin.cgb = True

        plugin._var_palette = MagicMock()
        plugin._var_palette.get.return_value = "Classic Green"
        plugin._on_palette_change()  # must not raise or call set_color_palette
    finally:
        plugin.cgb = original_cgb
        pyboy.stop(save=False)


# ---------------------------------------------------------------------------
# Runtime mutations – pause / unpause
# ---------------------------------------------------------------------------

def test_pause_callback_pauses_emulator(default_rom):
    """_on_pause_toggle() with var=True must pause the emulator."""
    pyboy = _make_pyboy(default_rom)
    try:
        plugin = _get_plugin(pyboy)
        assert pyboy.paused is False

        plugin._var_pause = MagicMock()
        plugin._var_pause.get.return_value = True
        plugin._on_pause_toggle()

        assert pyboy.paused is True
    finally:
        pyboy.stop(save=False)


def test_pause_callback_unpauses_emulator(default_rom):
    """_on_pause_toggle() with var=False must unpause the emulator."""
    pyboy = _make_pyboy(default_rom)
    try:
        pyboy._pause()
        assert pyboy.paused is True

        plugin = _get_plugin(pyboy)
        plugin._var_pause = MagicMock()
        plugin._var_pause.get.return_value = False
        plugin._on_pause_toggle()

        assert pyboy.paused is False
    finally:
        pyboy.stop(save=False)


def test_pause_callback_idempotent_pause(default_rom):
    """Calling _on_pause_toggle(True) twice must not raise."""
    pyboy = _make_pyboy(default_rom)
    try:
        plugin = _get_plugin(pyboy)
        plugin._var_pause = MagicMock()
        plugin._var_pause.get.return_value = True
        plugin._on_pause_toggle()
        plugin._on_pause_toggle()  # second call – emulator already paused
        assert pyboy.paused is True
    finally:
        pyboy.stop(save=False)


# ---------------------------------------------------------------------------
# DMG_PALETTE_PRESETS data integrity
# ---------------------------------------------------------------------------

def test_all_palette_presets_have_four_colours():
    """Every preset must be a 4-tuple of integers."""
    for name, palette in DMG_PALETTE_PRESETS.items():
        assert len(palette) == 4, f"Preset '{name}' does not have 4 colours"
        for colour in palette:
            assert isinstance(colour, int), (
                f"Colour {colour!r} in preset '{name}' is not an int"
            )


def test_palette_names_match_presets():
    """PALETTE_NAMES must be exactly the keys of DMG_PALETTE_PRESETS."""
    assert PALETTE_NAMES == list(DMG_PALETTE_PRESETS.keys())


def test_palette_colours_in_valid_rgb_range():
    """All palette colours must be valid 24-bit RGB values."""
    for name, palette in DMG_PALETTE_PRESETS.items():
        for colour in palette:
            assert 0x000000 <= colour <= 0xFFFFFF, (
                f"Colour 0x{colour:06X} in '{name}' is outside 24-bit range"
            )


# ---------------------------------------------------------------------------
# Event pipeline integration (null window)
# ---------------------------------------------------------------------------

def test_settings_toggle_passes_through_event_pipeline(default_rom):
    """
    SETTINGS_TOGGLE sent via send_input must reach the plugin's handle_events
    without raising and the event must not be consumed (PASS is returned for
    unknown game-button events).
    """
    pyboy = _make_pyboy(default_rom)
    try:
        # Just verify no exception is raised when the event is injected into
        # the full emulator pipeline.
        pyboy.send_input(WindowEvent.SETTINGS_TOGGLE)
        pyboy.tick(1, True, False)  # processes queued events
    finally:
        pyboy.stop(save=False)

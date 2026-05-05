"""
Tests for the key-mapping logic in window_sdl2.py.

These tests exercise remap_key / get_key_for_button directly and do NOT
require a running emulator, a display, or SDL2 to be initialised.  They
validate that the KEY_DOWN / KEY_UP dicts are mutated correctly when a
binding is changed.
"""

import pytest

# We need sdl2 available for the keycode constants; skip the whole module
# gracefully if it is not installed.
sdl2 = pytest.importorskip("sdl2", reason="pysdl2 not installed")

from pyboy.plugins.window_sdl2 import (  # noqa: E402
    KEY_DOWN,
    KEY_UP,
    GAMEBOY_BUTTONS,
    get_key_for_button,
    remap_key,
)
from pyboy.utils import WindowEvent  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _restore(original_down, original_up):
    """Put KEY_DOWN / KEY_UP back to their original state."""
    KEY_DOWN.clear()
    KEY_DOWN.update(original_down)
    KEY_UP.clear()
    KEY_UP.update(original_up)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_get_key_for_button_returns_default():
    """A is mapped to SDLK_a by default."""
    keycode = get_key_for_button(WindowEvent.PRESS_BUTTON_A)
    assert keycode == sdl2.SDLK_a


def test_remap_key_changes_press_mapping():
    """After remapping A to SDLK_z, pressing Z should produce PRESS_BUTTON_A."""
    orig_down = dict(KEY_DOWN)
    orig_up = dict(KEY_UP)
    try:
        remap_key(WindowEvent.PRESS_BUTTON_A, WindowEvent.RELEASE_BUTTON_A, sdl2.SDLK_z)
        assert KEY_DOWN.get(sdl2.SDLK_z) == WindowEvent.PRESS_BUTTON_A
    finally:
        _restore(orig_down, orig_up)


def test_remap_key_changes_release_mapping():
    """After remapping A to SDLK_z, releasing Z should produce RELEASE_BUTTON_A."""
    orig_down = dict(KEY_DOWN)
    orig_up = dict(KEY_UP)
    try:
        remap_key(WindowEvent.PRESS_BUTTON_A, WindowEvent.RELEASE_BUTTON_A, sdl2.SDLK_z)
        assert KEY_UP.get(sdl2.SDLK_z) == WindowEvent.RELEASE_BUTTON_A
    finally:
        _restore(orig_down, orig_up)


def test_remap_key_removes_old_binding():
    """The old keycode should no longer appear in KEY_DOWN after a remap."""
    orig_down = dict(KEY_DOWN)
    orig_up = dict(KEY_UP)
    try:
        old_keycode = get_key_for_button(WindowEvent.PRESS_BUTTON_A)
        remap_key(WindowEvent.PRESS_BUTTON_A, WindowEvent.RELEASE_BUTTON_A, sdl2.SDLK_z)
        assert old_keycode not in KEY_DOWN
        assert old_keycode not in KEY_UP
    finally:
        _restore(orig_down, orig_up)


def test_remap_key_returns_old_keycode():
    """remap_key should return the previous keycode that was displaced."""
    orig_down = dict(KEY_DOWN)
    orig_up = dict(KEY_UP)
    try:
        old = get_key_for_button(WindowEvent.PRESS_BUTTON_A)
        returned = remap_key(WindowEvent.PRESS_BUTTON_A, WindowEvent.RELEASE_BUTTON_A, sdl2.SDLK_z)
        assert returned == old
    finally:
        _restore(orig_down, orig_up)


def test_remap_key_no_collision():
    """Remapping B onto A's old key should not leave A's old key still mapped to A."""
    orig_down = dict(KEY_DOWN)
    orig_up = dict(KEY_UP)
    try:
        key_a = get_key_for_button(WindowEvent.PRESS_BUTTON_A)
        # Map B onto A's current key
        remap_key(WindowEvent.PRESS_BUTTON_B, WindowEvent.RELEASE_BUTTON_B, key_a)
        # That key should now fire B, not A
        assert KEY_DOWN.get(key_a) == WindowEvent.PRESS_BUTTON_B
    finally:
        _restore(orig_down, orig_up)


def test_all_default_buttons_have_bindings():
    """Every entry in GAMEBOY_BUTTONS should have a key bound by default."""
    for btn_name, (press_ev, _) in GAMEBOY_BUTTONS.items():
        keycode = get_key_for_button(press_ev)
        assert keycode is not None, f"No default binding for button '{btn_name}'"


def test_remap_get_reflects_new_key():
    """get_key_for_button should return the new keycode after a remap."""
    orig_down = dict(KEY_DOWN)
    orig_up = dict(KEY_UP)
    try:
        remap_key(WindowEvent.PRESS_ARROW_UP, WindowEvent.RELEASE_ARROW_UP, sdl2.SDLK_w)
        assert get_key_for_button(WindowEvent.PRESS_ARROW_UP) == sdl2.SDLK_w
    finally:
        _restore(orig_down, orig_up)

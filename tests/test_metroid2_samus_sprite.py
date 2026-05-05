#
# License: See LICENSE.md file
# GitHub: https://github.com/Baekalfen/PyBoy
#
"""
Regression tests for GitHub issue #351:
  Metroid 2 – Samus sprite invisible at game start
  https://github.com/Baekalfen/PyBoy/issues/351

The bug: after starting a new game, Samus's body is mostly invisible
(only a few foot-pixels are rendered).  The cause is that her VRAM tile
data is not loaded correctly, so the sprites appear blank on screen.

These tests load both known-good ROM dumps, navigate past the title screen,
and assert that Samus's complete sprite is present on screen with real pixel
data loaded in VRAM.

── Git-bisect usage ──────────────────────────────────────────────────────────
To find the commit that introduced the regression:

  git bisect start
  git bisect bad                    # mark current (broken) HEAD
  git checkout v2.3.0               # last known-good release
  git bisect good
  git bisect run python -m pytest tests/test_metroid2_samus_sprite.py -x -q

Each bisect step checks out a commit, runs these tests, and marks the result
automatically (exit 0 = good, non-zero = bad).  The bisect will identify the
first bad commit in ~7-10 steps between v2.3.0 and v2.4.0.
──────────────────────────────────────────────────────────────────────────────
"""

import os
import pytest
import numpy as np

from pyboy import PyBoy

# ── ROM paths ────────────────────────────────────────────────────────────────
ROM_USA   = os.path.join("roms", "metroid2usaia.gb")
ROM_WORLD = os.path.join("roms", "metroid2worldvimms.gb")

ROMS = [
    pytest.param(ROM_USA,   id="metroid2-usa"),
    pytest.param(ROM_WORLD, id="metroid2-world"),
]


# ── Thresholds derived from a working build ───────────────────────────────────
# On a working version, after navigating to the game start:
#   • 17 sprites are on-screen (Samus is built from ~15 8×8 sprites)
#   • 9 580 non-black pixels are rendered on screen
#   • 248 total non-zero VRAM bytes across all on-screen sprite tiles
#
# On the broken version, Samus's body tiles are empty/near-zero so:
#   • Fewer sprites may appear on-screen
#   • Non-black pixel count drops drastically (only feet remain ~100-200 px)
#   • Total VRAM tile bytes drop to ~30-80 (feet tiles only)
#
# Conservative thresholds give a clear pass/fail signal:
MIN_ONSCREEN_SPRITES   = 15    # Samus alone occupies 15 sprite slots (5 rows × 3 cols)
MIN_SPRITE_VRAM_BYTES  = 150   # feet-only gives ~84; full Samus gives ~248
MIN_SCREEN_PIXELS      = 2000  # feet-only < 500; full render > 9000


# ── Navigation constants ─────────────────────────────────────────────────────
FRAMES_TO_TITLE       = 90   # frames to reach the title screen / opening logo
FRAMES_BETWEEN_STARTS = 5    # gap between the two Start presses
FRAMES_TO_GAME        = 300  # frames after the second Start for the level to load


# ── Helpers ───────────────────────────────────────────────────────────────────

def skip_if_missing(path):
    """Skip the test if the ROM file does not exist in the project."""
    if not os.path.isfile(path):
        pytest.skip(f"ROM not found: {path}")


def navigate_to_game_start(pyboy: PyBoy) -> None:
    """
    Navigate from ROM cold-boot to the point where Samus is standing at
    her starting position in the game world.

    Timeline (all frames run at unlimited speed, render disabled for speed
    except the final frame where we need the screen buffer):
      0 – 90    : boot + title-screen animation
      ~90       : title screen is ready → first Start press (enters intro)
      90 – 95   : short gap
      ~95       : second Start press (skips intro, starts the game)
      95 – 395  : level loads, Samus spawns at starting position
      ~395      : render=True to flush the GPU screen buffer

    Two Start presses are required:
      1st Start  →  title screen → game intro / attract mode
      2nd Start  →  skips intro  → actual gameplay (Samus on screen)
    """
    # Run to title screen
    pyboy.tick(FRAMES_TO_TITLE, render=False, sound=False)

    # First Start: enter intro/attract
    pyboy.button("start")
    pyboy.tick(FRAMES_BETWEEN_STARTS, render=False, sound=False)

    # Second Start: skip intro, enter gameplay
    pyboy.button("start")

    # Let the level load; render the last frame so the screen buffer is fresh
    pyboy.tick(FRAMES_TO_GAME - 1, render=False, sound=False)
    pyboy.tick(1, render=True, sound=False)  # flush screen buffer


def count_onscreen_sprites_with_vram_data(pyboy: PyBoy):
    """
    Return (on_screen_count, total_nonzero_vram_bytes) across all 40 OAM
    sprite slots.  A sprite counts toward total_nonzero_vram_bytes only when
    it is actually on screen AND its primary tile has at least one non-zero
    byte in VRAM (i.e. the game engine loaded actual pixel data for it).
    """
    on_screen = 0
    vram_bytes = 0
    for idx in range(40):
        sprite = pyboy.get_sprite(idx)
        if sprite.on_screen:
            on_screen += 1
            for tile in sprite.tiles:
                tile_data = pyboy.memory[tile.data_address: tile.data_address + 16]
                vram_bytes += sum(1 for b in tile_data if b != 0)
    return on_screen, vram_bytes


def count_nonblack_screen_pixels(pyboy: PyBoy) -> int:
    """
    Return the number of pixels on the screen whose RGB value is not (0,0,0).
    A working render of Samus at game start produces ~9500 non-black pixels.
    An invisible Samus (feet only) produces fewer than 500.
    """
    screen = pyboy.screen.ndarray          # shape (144, 160, 4)  RGBA
    return int(np.sum(np.any(screen[:, :, :3] != 0, axis=2)))


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rom_path", ROMS)
def test_samus_sprite_onscreen_count(rom_path):
    """
    After starting a new game, at least MIN_ONSCREEN_SPRITES sprites must
    be on screen.

    Samus is composed of ~15 individual 8×8 sprite tiles arranged in a 3-wide
    × 5-tall grid.  On a broken build her body tiles are invisible/blank and
    only the foot sprites (2-6 slots) remain on screen.
    """
    skip_if_missing(rom_path)
    pyboy = PyBoy(rom_path, window="null", sound_emulated=False)
    pyboy.set_emulation_speed(0)
    try:
        navigate_to_game_start(pyboy)
        on_screen, _ = count_onscreen_sprites_with_vram_data(pyboy)
        assert on_screen >= MIN_ONSCREEN_SPRITES, (
            f"Expected ≥{MIN_ONSCREEN_SPRITES} on-screen sprites but found {on_screen}. "
            f"Samus's sprite may not be loaded (issue #351)."
        )
    finally:
        pyboy.stop(save=False)


@pytest.mark.parametrize("rom_path", ROMS)
def test_samus_sprite_vram_data_loaded(rom_path):
    """
    The VRAM tile data for Samus's on-screen sprites must contain real pixel
    data (non-zero bytes).

    On a broken build, the body tiles are not DMA'd into VRAM, so most tile
    bytes remain zero even though the OAM still lists the sprite positions.
    Total non-zero VRAM bytes across all on-screen sprite tiles should be
    ≥ MIN_SPRITE_VRAM_BYTES (currently ~248 on a working build, ~84 on a
    broken one where only feet tiles are present).
    """
    skip_if_missing(rom_path)
    pyboy = PyBoy(rom_path, window="null", sound_emulated=False)
    pyboy.set_emulation_speed(0)
    try:
        navigate_to_game_start(pyboy)
        _, vram_bytes = count_onscreen_sprites_with_vram_data(pyboy)
        assert vram_bytes >= MIN_SPRITE_VRAM_BYTES, (
            f"Expected ≥{MIN_SPRITE_VRAM_BYTES} non-zero VRAM bytes in on-screen sprite tiles "
            f"but found {vram_bytes}. "
            f"Samus's tile data may not be loaded into VRAM (issue #351)."
        )
    finally:
        pyboy.stop(save=False)


@pytest.mark.parametrize("rom_path", ROMS)
def test_samus_visible_on_screen(rom_path):
    """
    The rendered screen must contain a meaningful number of non-black pixels.

    At the game start position the screen shows Samus, the environment, and
    the HUD.  A working render produces ~9500 non-black pixels.  When Samus
    is invisible (bug) the pixel count drops to well under 500 because only
    a handful of foot-pixels and the background remain.
    """
    skip_if_missing(rom_path)
    pyboy = PyBoy(rom_path, window="null", sound_emulated=False)
    pyboy.set_emulation_speed(0)
    try:
        navigate_to_game_start(pyboy)
        nonblack = count_nonblack_screen_pixels(pyboy)
        assert nonblack >= MIN_SCREEN_PIXELS, (
            f"Expected ≥{MIN_SCREEN_PIXELS} non-black screen pixels but found {nonblack}. "
            f"Samus may be invisible on screen (issue #351)."
        )
    finally:
        pyboy.stop(save=False)


@pytest.mark.parametrize("rom_path", ROMS)
def test_samus_sprite_body_tiles_nonempty(rom_path):
    """
    Individually verify that the body-region sprites (those in the upper half
    of the screen, y < 110) have non-zero VRAM data.

    The bug manifests as the *body* tiles being blank while the *foot* tiles
    remain populated.  This test isolates the body check so the bisect can
    pinpoint the exact frame/code path involved.
    """
    skip_if_missing(rom_path)
    pyboy = PyBoy(rom_path, window="null", sound_emulated=False)
    pyboy.set_emulation_speed(0)
    try:
        navigate_to_game_start(pyboy)

        body_sprites_found  = 0
        body_sprites_loaded = 0

        for idx in range(40):
            sprite = pyboy.get_sprite(idx)
            # Consider only on-screen sprites in the upper body region
            if sprite.on_screen and sprite.y < 110:
                body_sprites_found += 1
                tile_data = pyboy.memory[
                    sprite.tiles[0].data_address: sprite.tiles[0].data_address + 16
                ]
                if any(b != 0 for b in tile_data):
                    body_sprites_loaded += 1

        assert body_sprites_found >= 9, (
            f"Expected ≥9 body-region sprites on screen (y < 110) but found "
            f"{body_sprites_found}.  Samus's upper body may be off-screen (issue #351)."
        )
        assert body_sprites_loaded == body_sprites_found, (
            f"{body_sprites_found - body_sprites_loaded}/{body_sprites_found} body-region "
            f"sprite tiles are empty in VRAM.  Samus's body tiles are not loaded (issue #351)."
        )
    finally:
        pyboy.stop(save=False)

"""
Pokedex Trace Diagnostic Tool
==============================

PURPOSE:
  This script diagnoses rendering issues in Pokemon Crystal's Pokedex screen by
  continuously monitoring the Pokedex panel and detecting "blank-like" (mostly black
  or single-color) states. When such states are detected, it captures:
  - Full LCD register state (LCDC, STAT, LY, WY, WX, etc.)
  - VRAM contents (background map, window map, tile data)
  - Palette data (both background and object palettes)
  - Screenshots for visual inspection
  - Screen tilemap position data

ROOT CAUSE IT HELPED IDENTIFY:
  The wy_activated_frame boolean flag in the LCD renderer was leaking between frames
  and not resetting at VBlank. When WY=0 (window should activate from scanline 0),
  the flag was not being re-initialized at frame boundaries, causing the window layer
  to fail rendering. This tool's logs revealed the pattern by showing the LCD state
  at each "blank detection" event.

USAGE:
  python tools/pokedex_trace.py path/to/PokemonCrystal.gbc \\
    --window SDL2 \\
    --loadstate auto \\
    --output trace_log.jsonl \\
    --screenshot-dir screenshots/trace \\
    --blank-log-interval 120

  Then:
  1. Open the Pokedex (select panel on the right)
  2. Move over Pokemon entries to see blank panel detection
  3. Close window or press Ctrl+C to stop
  4. Inspect trace_log.jsonl and screenshots/trace/ for state analysis

OUTPUT:
  - trace_log.jsonl: JSONL file with frame-by-frame LCD state snapshots
  - screenshots/trace/*.png: Screen captures at each state change
  - Useful for debugging rendering edge cases and state machine issues

INTEGRATION WITH FIXES:
  After using this tool to identify the wy_activated_frame leak:
  1. Regression tests were added to tests/test_lcd.py to verify the flag
     properly resets at VBlank and activates correctly when WY=0
  2. LCD frame-reset logic in pyboy/core/lcd.py was corrected to initialize
     the flag at each frame boundary
"""

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyboy import PyBoy
from pyboy.utils import cython_compiled


RIGHT_PANEL_Y = slice(16, 124)
RIGHT_PANEL_X = slice(74, 154)

REGISTERS = {
    "LCDC": 0xFF40,
    "STAT": 0xFF41,
    "SCY": 0xFF42,
    "SCX": 0xFF43,
    "LY": 0xFF44,
    "LYC": 0xFF45,
    "BGP": 0xFF47,
    "OBP0": 0xFF48,
    "OBP1": 0xFF49,
    "WY": 0xFF4A,
    "WX": 0xFF4B,
    "KEY0": 0xFF4C,
    "KEY1": 0xFF4D,
    "VBK": 0xFF4F,
    "HDMA1": 0xFF51,
    "HDMA2": 0xFF52,
    "HDMA3": 0xFF53,
    "HDMA4": 0xFF54,
    "HDMA5": 0xFF55,
    "BCPS": 0xFF68,
    "BCPD": 0xFF69,
    "OCPS": 0xFF6A,
    "OCPD": 0xFF6B,
    "OPRI": 0xFF6C,
    "SVBK": 0xFF70,
}


def md5_bytes(data):
    return hashlib.md5(bytes(data)).hexdigest()


def read_vram_bank(memory, bank, start, end):
    original_bank = memory[0xFF4F] & 0x1
    memory[0xFF4F] = bank & 0x1
    try:
        return memory[start:end]
    finally:
        memory[0xFF4F] = original_bank


def read_palette_bytes(memory, index_addr, data_addr):
    original_index = memory[index_addr]
    try:
        palette = []
        for raw_index in range(64):
            memory[index_addr] = raw_index
            palette.append(memory[data_addr])
        return palette
    finally:
        memory[index_addr] = original_index


def color_summary(region):
    """
    Analyze a screen region's color distribution to detect "blank-like" panels.
    
    A panel is considered "blank-like" if it has very high color dominance
    (>= 90% of pixels are the same color) and few unique colors (<= 6).
    This heuristic detects when the window layer fails to render.
    
    Returns dict with dominant_fraction, unique_colors, and top 4 colors.
    """
    pixels = region.reshape(-1, region.shape[-1])
    counter = Counter(map(tuple, pixels.tolist()))
    top_colors = counter.most_common(4)
    dominant_count = top_colors[0][1] if top_colors else 0
    total = pixels.shape[0]
    dominant_fraction = dominant_count / total if total else 0.0
    return {
        "dominant_fraction": round(dominant_fraction, 4),
        "unique_colors": len(counter),
        "top_colors": [[list(color), count] for color, count in top_colors],
    }


def panel_blank_metrics(pyboy):
    """
    Compute metrics for the Pokedex right panel to detect blank rendering.
    
    This focuses on the RIGHT_PANEL_Y / RIGHT_PANEL_X region where Pokemon
    data is displayed. High dominant_fraction + low unique_colors indicates
    the window layer is not rendering (leaving mostly black background).
    
    Returns dict with blank_like boolean and color metrics.
    """
    region = pyboy.screen.ndarray[RIGHT_PANEL_Y, RIGHT_PANEL_X, :3]
    summary = color_summary(region)
    summary["blank_like"] = summary["dominant_fraction"] >= 0.9 and summary["unique_colors"] <= 6
    return summary


def serialize_registers(pyboy):
    """
    Capture complete LCD and VRAM state into a serializable snapshot.
    
    This is the core diagnostic function. It extracts:
    - All LCD control registers (LCDC, STAT, LY, WY, WX, etc.)
    - VRAM contents: window map, background map, tile data from both banks
    - Palette data: background and object color palettes
    - Screen state: tilemap positions and scanline samples
    
    The snapshot is JSON-serializable and written to the trace log to build
    a timeline of LCD state as the Pokedex panel transitions between blank
    and non-blank renders. Useful for correlating state changes with flag resets.
    
    Returns dict snapshot with frame number, all register values, and VRAM hashes.
    """
    memory = pyboy.memory
    registers = {name: memory[address] for name, address in REGISTERS.items()}

    lcdc = registers["LCDC"]
    active_window_offset = 0x1C00 if (lcdc & (1 << 6)) else 0x1800
    active_bg_offset = 0x1C00 if (lcdc & (1 << 3)) else 0x1800
    wx = registers["WX"] - 7
    wy = registers["WY"]
    scx = registers["SCX"]
    scy = registers["SCY"]
    window_bank0 = read_vram_bank(memory, 0, 0x8000 + active_window_offset, 0x8000 + active_window_offset + 0x400)
    window_bank1 = read_vram_bank(memory, 1, 0x8000 + active_window_offset, 0x8000 + active_window_offset + 0x400)
    bg_bank0 = read_vram_bank(memory, 0, 0x8000 + active_bg_offset, 0x8000 + active_bg_offset + 0x400)
    bg_bank1 = read_vram_bank(memory, 1, 0x8000 + active_bg_offset, 0x8000 + active_bg_offset + 0x400)
    tiledata_bank0 = read_vram_bank(memory, 0, 0x8000, 0x9800)
    tiledata_bank1 = read_vram_bank(memory, 1, 0x8000, 0x9800)
    bg_palette_bytes = read_palette_bytes(memory, 0xFF68, 0xFF69)
    obj_palette_bytes = read_palette_bytes(memory, 0xFF6A, 0xFF6B)

    snapshot = {
        "frame": pyboy.frame_count,
        "registers": {name: hex(value) for name, value in registers.items()},
        "lcd": {
            "stat_mode": registers["STAT"] & 0b11,
            "LY": registers["LY"],
            "LYC": registers["LYC"],
            "SCX": scx,
            "SCY": scy,
            "WX": registers["WX"],
            "WY": wy,
            "window_pos": [wx, wy],
            "viewport": [scx, scy],
            "window_enabled": bool(lcdc & (1 << 5)),
            "windowmap_offset": hex(active_window_offset),
            "backgroundmap_offset": hex(active_bg_offset),
            "tiledata_select": bool(lcdc & (1 << 4)),
            "background_enable": bool(lcdc & (1 << 0)),
            "vbk": registers["VBK"] & 0x1,
            "bcps": registers["BCPS"],
            "ocps": registers["OCPS"],
            "object_priority_mode": registers["OPRI"] & 0x1,
        },
        "hdma": {
            "transfer_active": (registers["HDMA5"] & 0x80) == 0,
            "hdma1": hex(registers["HDMA1"]),
            "hdma2": hex(registers["HDMA2"]),
            "hdma3": hex(registers["HDMA3"]),
            "hdma4": hex(registers["HDMA4"]),
            "hdma5": hex(registers["HDMA5"]),
        },
        "vram": {
            "windowmap_bank0_hash": md5_bytes(window_bank0),
            "windowmap_bank1_hash": md5_bytes(window_bank1),
            "bgmap_bank0_hash": md5_bytes(bg_bank0),
            "bgmap_bank1_hash": md5_bytes(bg_bank1),
            "tiledata_bank0_hash": md5_bytes(tiledata_bank0),
            "tiledata_bank1_hash": md5_bytes(tiledata_bank1),
            "windowmap_bank0_head": window_bank0[:32],
            "windowmap_bank1_head": window_bank1[:32],
            "bgmap_bank0_head": bg_bank0[:32],
            "bgmap_bank1_head": bg_bank1[:32],
        },
        "palettes": {
            "bg_hash": md5_bytes(bg_palette_bytes),
            "obj_hash": md5_bytes(obj_palette_bytes),
            "bg_head": bg_palette_bytes[:16],
            "obj_head": obj_palette_bytes[:16],
        },
        "screen": {
            "tilemap_position": [list(item) for item in pyboy.screen.get_tilemap_position()],
            "scanline_sample": pyboy.screen.tilemap_position_list[0:6],
        },
    }

    return snapshot


def write_snapshot(log_path, snapshot):
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, sort_keys=True))
        handle.write("\n")


def save_frame(pyboy, screenshot_dir, label):
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    image_path = screenshot_dir / f"{label}_{pyboy.frame_count:06d}.png"
    pyboy.screen.image.copy().save(image_path)
    return image_path


def resolve_state_path(rom_path, value, *, for_save):
    if value == "off":
        return None
    if value == "auto":
        if for_save:
            return rom_path.with_suffix(rom_path.suffix + ".trace.state")

        trace_path = rom_path.with_suffix(rom_path.suffix + ".trace.state")
        if trace_path.exists():
            return trace_path
        primary_path = rom_path.with_suffix(rom_path.suffix + ".state")
        if primary_path.exists():
            return primary_path
        return None

    return Path(value)


def maybe_load_state(pyboy, rom_path, loadstate):
    state_path = resolve_state_path(rom_path, loadstate, for_save=False)
    if state_path is None or not state_path.exists():
        return None
    with state_path.open("rb") as handle:
        pyboy.load_state(handle)
    return state_path


def maybe_save_state(pyboy, rom_path, savestate):
    state_path = resolve_state_path(rom_path, savestate, for_save=True)
    if state_path is None:
        return None
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.open("wb") as handle:
        pyboy.save_state(handle)
    return state_path


def run_trace(args):
    """
    Main trace loop: run emulation and log LCD state when panel blank-ness changes.
    
    This function:
    1. Loads the ROM and optionally a saved state (for fast navigation to Pokedex)
    2. Starts the emulation loop at the specified speed
    3. Each frame, analyzes the Pokedex panel for blank-like rendering
    4. When blank-ness changes (True->False or False->True), captures:
       - Full LCD/VRAM state via serialize_registers()
       - Screenshot saved to screenshot_dir/
       - Single-line entry appended to output JSONL log
    5. Saves final state on exit (Ctrl+C or emulator quit)
    
    The JSONL log can be parsed to build a timeline and correlate blank panels
    with specific LCD register values (especially WY, LCDC window enable, LY).
    
    This was critical for identifying the wy_activated_frame flag leak: the logs
    showed the flag was not being reset at frame boundaries, causing the window
    to fail rendering when WY=0.
    """
    rom_path = Path(args.rom).resolve()
    output_path = Path(args.output).resolve()
    screenshot_dir = Path(args.screenshot_dir).resolve()

    pyboy = PyBoy(
        str(rom_path),
        window=args.window,
        sound_emulated=not args.no_sound_emulation,
        sound_volume=0 if args.no_sound_emulation else 100,
    )
    pyboy.set_emulation_speed(args.speed)
    loaded_state = maybe_load_state(pyboy, rom_path, args.loadstate)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        header = {
            "rom": str(rom_path),
            "loadstate": str(loaded_state) if loaded_state else None,
            "window": args.window,
            "speed": args.speed,
            "cython_compiled": cython_compiled,
        }
        handle.write(json.dumps({"header": header}, sort_keys=True))
        handle.write("\n")

    print("Tracing started.")
    print(f"Log file: {output_path}")
    print(f"Screenshot dir: {screenshot_dir}")
    print("Open the Pokedex, move over a Pokemon, then close the window or press Ctrl+C.")

    previous_blank = None
    last_logged_frame = -99999

    try:
        while pyboy.tick(1, True, False):
            metrics = panel_blank_metrics(pyboy)
            blank_like = metrics["blank_like"]

            should_log = previous_blank is None or blank_like != previous_blank
            if blank_like and pyboy.frame_count - last_logged_frame >= args.blank_log_interval:
                should_log = True
            if args.log_every and pyboy.frame_count % args.log_every == 0:
                should_log = True

            if should_log:
                snapshot = serialize_registers(pyboy)
                snapshot["panel_metrics"] = metrics
                screenshot_path = save_frame(pyboy, screenshot_dir, "blank" if blank_like else "normal")
                snapshot["screenshot"] = str(screenshot_path)
                write_snapshot(output_path, snapshot)
                last_logged_frame = pyboy.frame_count
                print(
                    f"frame={pyboy.frame_count} blank_like={blank_like} dominant={metrics['dominant_fraction']} "
                    f"unique_colors={metrics['unique_colors']} screenshot={screenshot_path.name}"
                )

            previous_blank = blank_like
    except KeyboardInterrupt:
        print("Trace interrupted by user.")
    finally:
        saved_state = maybe_save_state(pyboy, rom_path, args.savestate)
        pyboy.stop(save=False)
        if saved_state is not None:
            print(f"Saved state: {saved_state}")
        print(f"Trace finished. Send {output_path} back along with the latest screenshot if needed.")


def build_parser():
    parser = argparse.ArgumentParser(description="Trace live Pokedex rendering state while PyBoy is running.")
    parser.add_argument("rom", help="Path to the ROM file")
    parser.add_argument("--window", default="SDL2", choices=["SDL2", "OpenGL", "GLFW"], help="PyBoy window backend")
    parser.add_argument("--speed", type=int, default=1, help="Emulation speed multiplier")
    parser.add_argument(
        "--loadstate",
        default="auto",
        help="State file to load before tracing. Use 'auto' to load '<rom>.state', or 'off' to skip.",
    )
    parser.add_argument(
        "--savestate",
        default="auto",
        help="State file to save on exit. Use 'auto' to write '<rom>.trace.state', or 'off' to disable saving.",
    )
    parser.add_argument("--output", default="pokedex_trace.log", help="Path to the JSONL trace log")
    parser.add_argument("--screenshot-dir", default="screenshots/pokedex_trace", help="Directory for captured screenshots")
    parser.add_argument("--blank-log-interval", type=int, default=120, help="Frames between repeated blank-panel snapshots")
    parser.add_argument("--log-every", type=int, default=0, help="Log every N frames regardless of blank detection")
    parser.add_argument("--no-sound-emulation", action="store_true", help="Disable sound emulation while tracing")
    return parser


if __name__ == "__main__":
    run_trace(build_parser().parse_args())
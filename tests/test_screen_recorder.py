#
# License: See LICENSE.md file
# GitHub: https://github.com/Baekalfen/PyBoy
#

from array import array

import pytest
from PIL import Image

from pyboy.plugins.screen_recorder import ScreenRecorder


class DummyLCD:
    renderer = None


class DummyMB:
    def __init__(self):
        self.cgb = False
        self.lcd = DummyLCD()


class DummySound:
    def __init__(self):
        # Simulate a small sound buffer with stereo signed 8-bit samples.
        raw = array("b", [0, 1, -1, 2, -2, 0])
        self.raw_buffer = memoryview(raw)
        self.raw_buffer_head = len(raw)
        self.sample_rate = 48000


class DummyScreen:
    def __init__(self):
        self.image = Image.new("RGB", (160, 144), "black")


class DummyPyBoy:
    def __init__(self):
        self.screen = DummyScreen()
        self.sound = DummySound()
        self.cartridge_title = "DUMMY"


def test_screen_recorder_defaults_to_mp4_and_captures_audio(monkeypatch, tmp_path):
    """Verify the screen recorder defaults to MP4 and captures raw audio for FFmpeg muxing."""
    dummy_pyboy = DummyPyBoy()

    # Create the recorder with the new default MP4 settings and audio enabled.
    recorder = ScreenRecorder(
        dummy_pyboy,
        DummyMB(),
        {"recording_format": "mp4", "recording_fps": 30, "recording_audio": True},
    )

    assert recorder.recording_format == "mp4"
    assert recorder.recording_audio is True

    recorder.recording = True
    recorder.post_tick()

    # Confirm one frame and one audio chunk were captured during record mode.
    assert len(recorder.frames) == 1
    assert len(recorder.audio_chunks) == 1

    recorded_path = tmp_path / "test_output.mp4"

    # Mock ffmpeg presence and the subprocess call so we don't need a real ffmpeg binary.
    monkeypatch.setattr(
        "pyboy.plugins.screen_recorder.shutil.which",
        lambda exe: str(tmp_path / "ffmpeg") if exe == "ffmpeg" else None,
    )

    called = []

    def fake_run(cmd, check, capture_output):
        called.append(cmd)
        return None

    monkeypatch.setattr("pyboy.plugins.screen_recorder.subprocess.run", fake_run)

    recorder.save(path=str(recorded_path), fps=30)

    assert called, "FFmpeg command should have been invoked"
    command = called[0]

    # Validate the generated ffmpeg command line includes both video and audio muxing.
    assert recorded_path.name in command
    assert "-c:v" in command
    assert "libx264" in command
    assert "-c:a" in command
    assert "aac" in command
    assert any("audio.raw" in arg for arg in command)

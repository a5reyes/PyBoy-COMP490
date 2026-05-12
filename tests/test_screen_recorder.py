#
# License: See LICENSE.md file
# GitHub: https://github.com/Baekalfen/PyBoy
#

from pyboy import PyBoy


def test_screen_recorder_defaults_to_mp4_and_captures_audio(monkeypatch, tmp_path, default_rom):
    """Verify the screen recorder defaults to MP4 and captures raw audio for FFmpeg muxing."""
    pyboy = PyBoy(
        default_rom,
        window="null",
        recording_format="mp4",
        recording_fps=30,
        recording_audio=True,
    )
    try:
        recorder = pyboy._plugin_manager.screen_recorder

        assert recorder.recording_format == "mp4"
        assert recorder.recording_audio is True

        recorder.recording = True
        recorder.add_frame(pyboy.screen.image.copy())
        recorder.audio_chunks.append(b"\x00\x01\x02\x03")

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
        assert any(recorded_path.name in arg for arg in command)
        assert "-c:v" in command
        assert "libx264" in command
        assert "-c:a" in command
        assert "aac" in command
        assert any("audio.raw" in arg for arg in command)
    finally:
        pyboy.stop()

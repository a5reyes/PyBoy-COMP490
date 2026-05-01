#
# License: See LICENSE.md file
# GitHub: https://github.com/Baekalfen/PyBoy
#

import os
import shutil  # Used to check if ffmpeg is available in PATH
import subprocess  # Used to call ffmpeg for MP4 encoding
import tempfile  # Used to create temporary directory for frame PNG files
import time

import pyboy
from pyboy.plugins.base_plugin import PyBoyPlugin
from pyboy.utils import WindowEvent

logger = pyboy.logging.get_logger(__name__)

try:
    from PIL import Image
except ImportError:
    Image = None

FPS = 60


class ScreenRecorder(PyBoyPlugin):
    # CLI arguments for configuring recording output format and frame rate.
    # Default recording format is now MP4, and audio capture can be enabled/disabled.
    argv = [
        (
            "--recording-format",
            {
                "default": "mp4",
                "type": str,
                "choices": ["gif", "mp4"],
                "help": "Set recording output format (requires ffmpeg for mp4)",
            },
        ),
        (
            "--recording-audio",
            {
                "dest": "recording_audio",
                "default": True,
                "action": "store_true",
                "help": "Enable sound recording in MP4 output (requires ffmpeg)",
            },
        ),
        (
            "--no-recording-audio",
            {
                "dest": "recording_audio",
                "action": "store_false",
                "help": "Disable sound recording in MP4 output",
            },
        ),
        (
            "--recording-fps",
            {
                "default": FPS,
                "type": int,
                "help": "Set recording output frame rate",
            },
        ),
    ]

    def __init__(self, *args):
        super().__init__(*args)

        self.recording = False
        self.frames = []
        self.audio_chunks = []  # Stores raw sound data per frame for optional FFmpeg muxing
        # Get recording format from CLI args (default: mp4)
        self.recording_format = self.pyboy_argv.get("recording_format", "mp4").lower()
        # Get recording FPS from CLI args (default: 60)
        self.recording_fps = max(1, int(self.pyboy_argv.get("recording_fps", FPS)))
        # Get recording audio flag from CLI args (default: enabled)
        self.recording_audio = self.pyboy_argv.get("recording_audio", True)

    def handle_events(self, events):
        for event in events:
            if event == WindowEvent.SCREEN_RECORDING_TOGGLE:
                self.recording ^= True
                if not self.recording:
                    self.save()
                else:
                    logger.info("ScreenRecorder started")
                break
        return events

    def post_tick(self):
        # Plugin: Screen Recorder
        if self.recording:
            self.add_frame(self.pyboy.screen.image.copy())
            self.add_audio()

    def add_frame(self, frame):
        # Pillow makes artifacts in the output, if we use 'RGB', which is PyBoy's default format
        self.frames.append(frame)

    def add_audio(self):
        # Capture raw audio from the PyBoy sound buffer for the current frame.
        if not self.recording_audio:
            return
        try:
            audio_data = self.pyboy.sound.raw_buffer[: self.pyboy.sound.raw_buffer_head].tobytes()
        except Exception:
            return
        if audio_data:
            self.audio_chunks.append(audio_data)

    def save(self, path=None, fps=None):
        """Save the recorded frames as GIF or MP4 based on recording_format setting."""
        logger.info("ScreenRecorder saving...")

        if fps is None:
            fps = self.recording_fps

        if path is None:
            directory = os.path.join(os.path.curdir, "recordings")
            if not os.path.exists(directory):
                os.makedirs(directory, mode=0o755)

            # Use .mp4 or .gif extension based on recording format
            extension = "mp4" if self.recording_format == "mp4" else "gif"
            path = os.path.join(directory, time.strftime(f"{self.pyboy.cartridge_title}-%Y.%m.%d-%H.%M.%S.{extension}"))

        if len(self.frames) > 0:
            # Choose save method: MP4 (if ffmpeg available) or GIF (default/fallback)
            if self.recording_format == "mp4" and self._ffmpeg_available():
                self._save_mp4(path, fps, audio=self.recording_audio)
            elif self.recording_format == "mp4":
                # Fallback to GIF if MP4 was requested but ffmpeg is not installed
                fallback_path = os.path.splitext(path)[0] + ".gif"
                logger.warning('Missing dependency "ffmpeg". Falling back to GIF: %s', fallback_path)
                if self.recording_audio:
                    logger.warning("Audio recording requested, but GIF cannot contain audio.")
                self._save_gif(fallback_path, fps)
            else:
                if self.recording_audio:
                    logger.warning("Audio recording requested, but GIF cannot contain audio.")
                self._save_gif(path, fps)
        else:
            logger.error("Screen recording failed: no frames")
        self.frames = []
        self.audio_chunks = []  # Clear captured audio with recorded frames

    def _save_gif(self, path, fps):
        self.frames[0].save(
            path,
            save_all=True,
            interlace=False,
            loop=0,
            optimize=True,
            append_images=self.frames[1:],
            duration=int(round(1000 / fps, -1)),
        )
        logger.info("Screen recording saved in {}".format(path))

    def _save_mp4(self, path, fps, audio=False):
        """Encode frames to MP4 using FFmpeg with H.264 video and optional AAC audio."""
        # Find ffmpeg executable in PATH
        ffmpeg_cmd = shutil.which("ffmpeg")
        if ffmpeg_cmd is None:
            raise RuntimeError("ffmpeg was not found in PATH")

        # Use temporary directory to store frame PNG files and optional raw audio
        with tempfile.TemporaryDirectory() as tmpdir:
            # Save each frame as a numbered PNG file
            for index, frame in enumerate(self.frames):
                frame.save(os.path.join(tmpdir, f"frame-{index:06d}.png"), format="PNG")

            command = [
                ffmpeg_cmd,
                "-y",  # Overwrite output file if exists
                "-framerate",
                str(fps),
                "-i",
                os.path.join(tmpdir, "frame-%06d.png"),
            ]

            if audio and self.audio_chunks:
                # Write the raw sound bytes to disk and instruct ffmpeg to mux them into the MP4.
                audio_path = os.path.join(tmpdir, "audio.raw")
                with open(audio_path, "wb") as audio_file:
                    for chunk in self.audio_chunks:
                        audio_file.write(chunk)

                sample_rate = getattr(self.pyboy.sound, "sample_rate", None)
                if sample_rate is None:
                    logger.warning("Sound sample rate is not available. Saving video without audio.")
                else:
                    command.extend(
                        [
                            "-f",
                            "s8",
                            "-ar",
                            str(sample_rate),
                            "-ac",
                            "2",
                            "-i",
                            audio_path,
                            "-c:a",
                            "aac",
                            "-b:a",
                            "192k",
                        ]
                    )
                    command.extend(["-shortest"])

            command.extend(
                [
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    path,
                ]
            )

            subprocess.run(command, check=True, capture_output=True)

        logger.info("Screen recording saved in {}".format(path))

    def _ffmpeg_available(self):
        """Check if ffmpeg is installed and available in PATH."""
        return shutil.which("ffmpeg") is not None

    def enabled(self):
        if Image is None:
            logger.warning('%s: Missing dependency "Pillow". Recording disabled', __name__)
            return False
        return True

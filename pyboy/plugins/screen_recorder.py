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
    # CLI arguments for configuring recording output format and frame rate
    argv = [
        (
            "--recording-format",
            {
                "default": "gif",
                "type": str,
                "choices": ["gif", "mp4"],
                "help": "Set recording output format (requires ffmpeg for mp4)",
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
        # Get recording format from CLI args (default: gif)
        self.recording_format = self.pyboy_argv.get("recording_format", "gif").lower()
        # Get recording FPS from CLI args (default: 60)
        self.recording_fps = max(1, int(self.pyboy_argv.get("recording_fps", FPS)))

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

    def add_frame(self, frame):
        # Pillow makes artifacts in the output, if we use 'RGB', which is PyBoy's default format
        self.frames.append(frame)

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
                self._save_mp4(path, fps)
            elif self.recording_format == "mp4":
                # Fallback to GIF if MP4 was requested but ffmpeg is not installed
                fallback_path = os.path.splitext(path)[0] + ".gif"
                logger.warning('Missing dependency "ffmpeg". Falling back to GIF: %s', fallback_path)
                self._save_gif(fallback_path, fps)
            else:
                self._save_gif(path, fps)
        else:
            logger.error("Screen recording failed: no frames")
        self.frames = []

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

    def _save_mp4(self, path, fps):
        """Encode frames to MP4 using FFmpeg with H.264 codec."""
        # Find ffmpeg executable in PATH
        ffmpeg_cmd = shutil.which("ffmpeg")
        if ffmpeg_cmd is None:
            raise RuntimeError("ffmpeg was not found in PATH")

        # Use temporary directory to store frame PNG files
        with tempfile.TemporaryDirectory() as tmpdir:
            # Save each frame as a numbered PNG file
            for index, frame in enumerate(self.frames):
                frame.save(os.path.join(tmpdir, f"frame-{index:06d}.png"), format="PNG")

            # Build ffmpeg command to encode PNG sequence to MP4
            command = [
                ffmpeg_cmd,
                "-y",  # Overwrite output file if exists
                "-framerate", str(fps),  # Input framerate
                "-i", os.path.join(tmpdir, "frame-%06d.png"),  # Input PNG sequence
                "-c:v", "libx264",  # H.264 video codec
                "-pix_fmt", "yuv420p",  # Pixel format for compatibility
                path,  # Output MP4 file
            ]
            # Run ffmpeg and capture output
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

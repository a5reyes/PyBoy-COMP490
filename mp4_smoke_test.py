from pathlib import Path
from pyboy import PyBoy
from pyboy.utils import WindowEvent

rec = Path("recordings")
rec.mkdir(exist_ok=True)
before = {p.name for p in rec.glob("*") if p.is_file()}

pyboy = PyBoy("pyboy/default_rom.gb", window="null", recording_format="mp4")
pyboy.send_input(WindowEvent.SCREEN_RECORDING_TOGGLE)
for _ in range(20):
    pyboy.tick()
pyboy.send_input(WindowEvent.SCREEN_RECORDING_TOGGLE)
for _ in range(2):
    pyboy.tick()
pyboy.stop()

after = [p.name for p in rec.glob("*") if p.is_file() and p.name not in before]
exts = sorted({p.suffix for p in rec.glob("*") if p.is_file()})
print("NEW_FILES=", after)
print("EXTENSIONS=", exts)

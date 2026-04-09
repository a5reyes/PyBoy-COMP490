from pyboy import PyBoy
import sys
import trace

# create a Trace object, telling it what to ignore, and whether to
# do tracing or line-counting or both.
tracer = trace.Trace(
    ignoredirs=[sys.prefix, sys.exec_prefix],
    trace=0,
    count=1,
    timing=True)

def bible():
    pyboy = PyBoy("./roms/bible.gb")
    pyboy.button_press("start")
    pyboy.tick(1, True)
    pyboy.button_press("start")
    pyboy.tick(1, True)
    pyboy.button_press("right")
    pyboy.tick(1, True)
    pyboy.button_press("right")
    pyboy.tick(1, True)
    pyboy.button_press("right")
    pyboy.tick(1, True)
    pyboy.button_press("start")
    pyboy.tick(1, True)
    pyboy.stop()


# run the new command using the given tracer
tracer.runfunc(bible)


# make a report, placing output in the current directory
r = tracer.results()
r.write_results(show_missing=True, coverdir=".")
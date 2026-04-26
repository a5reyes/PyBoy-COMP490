#
# License: See LICENSE.md file
# GitHub: https://github.com/Baekalfen/PyBoy
#

from pyboy.logging.logging cimport Logger
from pyboy.plugins.base_plugin cimport PyBoyPlugin


cdef Logger logger

cdef class ScreenRecorder(PyBoyPlugin):
    cdef bint recording
    cdef frames
    cdef recording_format  # Storage for selected output format (gif or mp4)
    cdef int recording_fps  # Storage for selected frame rate


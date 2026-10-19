"""Environment for external media processes launched from frozen or source builds."""
import os
import ctypes
import subprocess
import sys
from PyQt5.QtCore import QProcessEnvironment


def clean_subprocess_environment():
    environment = dict(os.environ)
    if getattr(sys, "frozen", False):
        original = os.environ.get("LD_LIBRARY_PATH_ORIG")
        if original:
            environment["LD_LIBRARY_PATH"] = original
        else:
            environment.pop("LD_LIBRARY_PATH", None)
    return environment


def clean_child_environment():
    environment = QProcessEnvironment()
    for key, value in clean_subprocess_environment().items():
        environment.insert(key, value)
    return environment


def subprocess_options():
    """Do not open a console window for each FFmpeg/FFprobe invocation."""
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


def configure_windows_dpi_awareness():
    """Request physical monitor coordinates before QApplication creates HWNDs."""
    if sys.platform != "win32":
        return
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        set_context = user32.SetProcessDpiAwarenessContext
        set_context.argtypes = [ctypes.c_void_p]
        set_context.restype = ctypes.c_int32
        if set_context(ctypes.c_void_p(-4)):
            return
        # An application manifest may already have selected per-monitor DPI.
        if ctypes.get_last_error() == 5:
            return
    except (AttributeError, OSError):
        pass
    try:
        set_awareness = ctypes.WinDLL("shcore").SetProcessDpiAwareness
        set_awareness.argtypes = [ctypes.c_int32]
        set_awareness.restype = ctypes.c_int32
        if set_awareness(2) in (0, -2147024891):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.WinDLL("user32").SetProcessDPIAware()
    except (AttributeError, OSError):
        pass

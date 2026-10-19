"""Locate application assets and media tools in source and packaged builds."""
from pathlib import Path
import shutil
import sys

RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def media_tool(name):
    """Prefer the distribution's own FFmpeg over an unrelated PATH version."""
    if name not in {"ffmpeg", "ffprobe"}:
        raise ValueError("Unknown media tool: " + name)
    filename = name + (".exe" if sys.platform == "win32" else "")
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    roots.append(RESOURCE_DIR)
    for root in roots:
        for folder in (root / "ffmpeg" / "bin", root / "bin", root):
            candidate = folder / filename
            if candidate.is_file():
                return str(candidate)
    return shutil.which(filename)

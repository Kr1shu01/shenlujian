"""Locate assets and the system-Python Wayland helper in source and frozen builds."""
from pathlib import Path
import sys

RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))

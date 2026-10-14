#!/bin/bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"
exec "$APP_DIR/.build-venv/bin/python" -m PyInstaller --clean --noconfirm \
    --onefile --windowed --name shenlujian \
    --add-data "$APP_DIR/assets:assets" \
    --add-data "$APP_DIR/wayland_capture.py:." \
    --exclude-module matplotlib --exclude-module numpy --exclude-module PIL \
    "$APP_DIR/shenlujian.py"

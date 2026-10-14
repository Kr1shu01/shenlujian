#!/bin/bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
ICON_PATH="$DATA_DIR/icons/hicolor/scalable/apps/shenlujian.svg"
APPLICATION_PATH="$DATA_DIR/applications/shenlujian.desktop"
mkdir -p "$BIN_DIR" "$(dirname "$ICON_PATH")" "$(dirname "$APPLICATION_PATH")"
install -m 755 "$APP_DIR/dist/shenlujian" "$BIN_DIR/shenlujian.tmp"
mv -f "$BIN_DIR/shenlujian.tmp" "$BIN_DIR/shenlujian"
install -m 644 "$APP_DIR/assets/shenlujian.svg" "$ICON_PATH"
python3 - "$APPLICATION_PATH" "$BIN_DIR/shenlujian" "$ICON_PATH" <<'PY'
from pathlib import Path
import sys
target,executable,icon=sys.argv[1:]
quoted=executable.replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$')
Path(target).write_text(f'''[Desktop Entry]
Version=1.0
Type=Application
Name=神录剪
Comment=随手一录，轻松一剪。
Comment[zh_CN]=随手一录，轻松一剪。
Exec="{quoted}"
Icon={icon}
Terminal=false
Categories=AudioVideo;Video;Recorder;
StartupNotify=true
StartupWMClass=shenlujian
Keywords=录屏;剪辑;倍速;删除帧;ffmpeg;video;editor;
''',encoding='utf-8')
PY
desktop-file-validate "$APPLICATION_PATH"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
if [[ -n "$DESKTOP_DIR" && -d "$DESKTOP_DIR" ]]; then
    install -m 755 "$APPLICATION_PATH" "$DESKTOP_DIR/神录剪.desktop"
    gio set "$DESKTOP_DIR/神录剪.desktop" metadata::trusted true 2>/dev/null || true
fi
update-desktop-database "$DATA_DIR/applications" 2>/dev/null || true
gtk-update-icon-cache -f -t "$DATA_DIR/icons/hicolor" 2>/dev/null || true
printf '已安装：%s\n应用图标：%s\n' "$BIN_DIR/shenlujian" "$APPLICATION_PATH"

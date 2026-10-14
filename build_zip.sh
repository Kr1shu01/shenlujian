#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="${1:-1.1.1}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
ROOT="$STAGE/shenlujian-linux-amd64"
mkdir -p "$ROOT/dist" "$ROOT/source" "$APP_DIR/releases"
install -m 755 "$APP_DIR/dist/shenlujian" "$ROOT/dist/shenlujian"
cp -r "$APP_DIR/assets" "$ROOT/assets"
cp "$APP_DIR/install_shenlujian.sh" "$ROOT/install_shenlujian.sh"
cp "$APP_DIR/"*.py "$ROOT/source/"
cp "$APP_DIR/build_shenlujian.sh" "$APP_DIR/build_deb.sh" "$APP_DIR/build_zip.sh" "$APP_DIR/install_shenlujian.sh" "$APP_DIR/README.md" "$ROOT/source/"
cp -r "$APP_DIR/assets" "$ROOT/source/assets"
if [[ -d "$APP_DIR/licenses" ]]; then cp -r "$APP_DIR/licenses" "$ROOT/licenses"; fi
if [[ -f "$APP_DIR/LICENSE" ]]; then cp "$APP_DIR/LICENSE" "$ROOT/LICENSE"; fi
cp "$APP_DIR/README.md" "$ROOT/README.md"
cat > "$ROOT/install.sh" <<'INSTALL'
#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
packages=(ffmpeg python3-dbus python3-gi gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-libav gstreamer1.0-pipewire pipewire xdg-desktop-portal x11-xserver-utils desktop-file-utils xdg-utils xdg-user-dirs)
missing=()
for package in "${packages[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q '^install ok installed$'; then missing+=("$package"); fi
done
if (( ${#missing[@]} )); then sudo apt-get update; sudo apt-get install -y "${missing[@]}"; fi
exec bash "$APP_DIR/install_shenlujian.sh"
INSTALL
chmod 755 "$ROOT/install.sh"
/usr/bin/python3 - "$STAGE" "$APP_DIR/releases/shenlujian-${VERSION}-linux-amd64.zip" <<'PY'
import sys,zipfile
from pathlib import Path
folder=Path(sys.argv[1])
with zipfile.ZipFile(sys.argv[2],'w',zipfile.ZIP_DEFLATED) as out:
 for file in sorted(folder.rglob('*')):
  if file.is_file():out.write(file,file.relative_to(folder))
PY

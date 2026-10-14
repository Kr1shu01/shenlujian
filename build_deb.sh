#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="${1:-1.1.1}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/DEBIAN" "$STAGE/opt/shenlujian" "$STAGE/usr/bin" "$STAGE/usr/share/applications" "$STAGE/usr/share/icons/hicolor/scalable/apps" "$STAGE/usr/share/doc/shenlujian" "$APP_DIR/releases"
install -m 755 "$APP_DIR/dist/shenlujian" "$STAGE/opt/shenlujian/shenlujian"
install -m 644 "$APP_DIR/assets/shenlujian.svg" "$STAGE/usr/share/icons/hicolor/scalable/apps/shenlujian.svg"
printf '#!/bin/sh\nexec /opt/shenlujian/shenlujian "$@"\n' > "$STAGE/usr/bin/shenlujian"
chmod 755 "$STAGE/usr/bin/shenlujian"
cat > "$STAGE/usr/share/applications/shenlujian.desktop" <<'DESKTOP'
[Desktop Entry]
Version=1.0
Type=Application
Name=神录剪
Comment=随手一录，轻松一剪。
Comment[zh_CN]=随手一录，轻松一剪。
Exec=/opt/shenlujian/shenlujian
Icon=shenlujian
Terminal=false
Categories=AudioVideo;Video;Recorder;
StartupNotify=true
StartupWMClass=shenlujian
DESKTOP
SIZE="$(du -sk "$STAGE" | cut -f1)"
cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: shenlujian
Version: $VERSION
Section: video
Priority: optional
Architecture: amd64
Installed-Size: $SIZE
Maintainer: Kr1shu01 <Kr1shu01@users.noreply.github.com>
Depends: ffmpeg, python3, python3-dbus, python3-gi, gir1.2-gstreamer-1.0, gir1.2-gst-plugins-base-1.0, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, gstreamer1.0-libav, gstreamer1.0-pipewire, pipewire, xdg-desktop-portal, x11-xserver-utils
Recommends: xdg-desktop-portal-gnome | xdg-desktop-portal-kde | xdg-desktop-portal-wlr
Homepage: https://github.com/Kr1shu01/shenlujian
Description: Screen recorder and basic video/audio timeline editor
 Shenlujian records X11 desktops or authorized Wayland monitor streams,
 and supports clip ordering, clip-scoped cuts, speed changes, audio mixing
 and MP4 export.
CONTROL
install -m 644 "$APP_DIR/README.md" "$STAGE/usr/share/doc/shenlujian/README.md"
install -m 644 "$APP_DIR/LICENSE" "$STAGE/usr/share/doc/shenlujian/copyright"
if [[ -d "$APP_DIR/licenses" ]]; then cp -r "$APP_DIR/licenses" "$STAGE/usr/share/doc/shenlujian/licenses"; fi
desktop-file-validate "$STAGE/usr/share/applications/shenlujian.desktop"
dpkg-deb --root-owner-group --build "$STAGE" "$APP_DIR/releases/shenlujian_${VERSION}_amd64.deb"

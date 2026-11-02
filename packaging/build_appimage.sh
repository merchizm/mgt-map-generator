#!/usr/bin/env bash
# Wraps the PyInstaller one-dir build (dist/mgt-map-gen) into an AppImage. Run from the repo root.
set -euo pipefail

rm -rf AppDir
mkdir -p AppDir/usr/bin
cp -r dist/mgt-map-gen/. AppDir/usr/bin/
cp packaging/mgt-map-gen.desktop AppDir/
cp assets/icon.png AppDir/mgt-map-gen.png
ln -s usr/bin/mgt-map-gen AppDir/AppRun

curl -fsSL -o appimagetool \
  https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x appimagetool
# --appimage-extract-and-run: CI runners have no FUSE
ARCH=x86_64 ./appimagetool --appimage-extract-and-run AppDir MGT-Map-Generator-x86_64.AppImage

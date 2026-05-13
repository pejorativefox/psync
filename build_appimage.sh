#!/bin/bash
set -e

# 1. Setup paths
APP_DIR="AppDir"
rm -rf "$APP_DIR" build dist

# 2. Build the application using the PyInstaller spec file
# This uses the local environment and the pre-configured spec file.
pyinstaller --noconfirm psync.spec

# 3. Download linuxdeploy and appimagetool if they don't exist
if [ ! -f linuxdeploy-x86_64.AppImage ]; then
    wget https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage
    chmod +x linuxdeploy-x86_64.AppImage
fi

# 4. Prepare the AppDir structure
mkdir -p "$APP_DIR/usr/bin"
cp -r dist/psync/* "$APP_DIR/usr/bin/"

# 5. Use linuxdeploy to bundle everything
# We specify the icon and the desktop file created earlier
export ARCH=x86_64
export OUTPUT="Psync-x86_64.AppImage"

./linuxdeploy-x86_64.AppImage --appdir "$APP_DIR" \
    -i assets/idle.png \
    -d psync.desktop \
    --output appimage

echo "------------------------------------------------"
echo "Build Complete: $(ls *.AppImage)"
echo "------------------------------------------------"

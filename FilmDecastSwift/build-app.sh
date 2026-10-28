#!/bin/bash
set -euo pipefail

# Build a native macOS application that can be launched from Finder.
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="${1:-$SOURCE_DIR/../NegativeMaster.app}"
if [[ "$APP_PATH" != /* ]]; then
  APP_PATH="$PWD/$APP_PATH"
fi
if [[ "$APP_PATH" != *.app ]]; then
  echo "Destination must end in .app" >&2
  exit 1
fi
if [[ -e "$APP_PATH" ]]; then
  EXISTING_ID=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP_PATH/Contents/Info.plist" 2>/dev/null || true)
  if [[ "$EXISTING_ID" != "local.NegativeMaster" ]]; then
    echo "Destination already exists and is not this application: $APP_PATH" >&2
    exit 1
  fi
fi

cd "$SOURCE_DIR"
swift build -c release --product FilmDecast
BIN_DIR="$(swift build -c release --show-bin-path)"
PROJECT_DIR="$(cd "$SOURCE_DIR/.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  python3 -m venv "$PROJECT_DIR/.venv"
fi
if ! "$PYTHON" -c 'import flask, numpy, PIL, rawpy, tifffile, imagecodecs, piexif' >/dev/null 2>&1; then
  "$PYTHON" -m pip install -r "$PROJECT_DIR/requirements.txt"
fi
mkdir -p "$APP_PATH/Contents/MacOS" "$APP_PATH/Contents/Resources/Engine/FilmDecastSwift/Support"
cp "$BIN_DIR/FilmDecast" "$APP_PATH/Contents/MacOS/NegativeMaster"
cat > "$APP_PATH/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key><string>NegativeMaster</string>
    <key>CFBundleIdentifier</key><string>local.NegativeMaster</string>
    <key>CFBundleName</key><string>NegativeMaster</string>
    <key>CFBundleDisplayName</key><string>NegativeMaster</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>2.1</string>
    <key>CFBundleVersion</key><string>7</string>
    <key>LSMinimumSystemVersion</key><string>14.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSPrincipalClass</key><string>NSApplication</string>
</dict>
</plist>
PLIST
for source in gui.py decast.py sheet_app.py contact_sheet.py film_effects.py film_reference.py platform_support.py archive_app.py film_artwork.py workflow_app.py conversion_advisor.py; do
  cp "$PROJECT_DIR/$source" "$APP_PATH/Contents/Resources/Engine/$source"
done
for folder in data static templates presets; do
  /usr/bin/ditto "$PROJECT_DIR/$folder" "$APP_PATH/Contents/Resources/Engine/$folder"
done
cp "$SOURCE_DIR/Support/native_worker.py" "$SOURCE_DIR/Support/native_preview.py" "$SOURCE_DIR/Support/sheet-defaults.json" "$APP_PATH/Contents/Resources/Engine/FilmDecastSwift/Support/"
"$PYTHON" "$SOURCE_DIR/Support/package_runtime.py" "$APP_PATH/Contents/Resources/Runtime"
"$PYTHON" - "$PROJECT_DIR" "$APP_PATH/Contents/Resources/Runtime.json" <<'PYCODE'
import json,sys
from pathlib import Path
Path(sys.argv[2]).write_text(json.dumps(dict(source=sys.argv[1])))
PYCODE
mkdir -p "$SOURCE_DIR/.build/AppIcon.iconset"
swift "$SOURCE_DIR/Support/make-icon.swift" "$SOURCE_DIR/.build/AppIcon.iconset"
/usr/bin/iconutil -c icns "$SOURCE_DIR/.build/AppIcon.iconset" -o "$APP_PATH/Contents/Resources/AppIcon.icns"
/usr/bin/plutil -lint "$APP_PATH/Contents/Info.plist"
# Finder metadata is not part of the application and prevents code signing.
# Homebrew libraries can be copied with read-only modes; make the staged bundle writable.
/bin/chmod -R u+w "$APP_PATH"
/usr/bin/xattr -cr "$APP_PATH"
/usr/bin/codesign --force --sign - "$APP_PATH"
echo "Application ready: $APP_PATH"

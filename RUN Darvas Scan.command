#!/bin/zsh
# Double-click this file in Finder to run the Darvas Phase 3 scan.
# macOS may ask you to allow it once in System Settings → Privacy & Security.

SCRIPT_DIR="/Users/jamesblond/Documents/1-Projects/AI Trade/Darvas Phase3 Scan"

cd "$SCRIPT_DIR"
python3 darvas_screener.py && python3 darvas_scan.py

echo ""
echo "Press any key to close this window..."
read -k 1

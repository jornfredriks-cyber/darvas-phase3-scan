#!/bin/zsh
SCRIPT_DIR="/Users/jamesblond/Documents/1-Projects/AI Trade/Darvas Phase3 Scan"

cd "$SCRIPT_DIR"
venv/bin/python3 darvas_screener.py && venv/bin/python3 darvas_scan_lc.py

echo ""
echo "Press any key to close this window..."
read -k 1

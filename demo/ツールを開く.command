#!/bin/sh
# macOS / Linux 用。ダブルクリック（または sh ./ツールを開く.command）で起動。
cd "$(dirname "$0")" || exit 1
PORT=8765
(sleep 1; (open "http://localhost:$PORT/" 2>/dev/null || xdg-open "http://localhost:$PORT/" 2>/dev/null)) &
python3 -m http.server $PORT

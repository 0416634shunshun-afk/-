@echo off
rem このツールをローカルのWebサーバー経由で開きます。
rem （index.htmlを直接ダブルクリックすると、ブラウザの安全上の制限で
rem   画像の保存やZIPまとめDLができないため）
cd /d "%~dp0"
set PORT=8765
where python >nul 2>&1 && (
  start "" http://localhost:%PORT%/
  python -m http.server %PORT%
) || (
  where py >nul 2>&1 && (
    start "" http://localhost:%PORT%/
    py -m http.server %PORT%
  ) || (
    echo Python が見つかりません。
    echo https://www.python.org/downloads/ からインストールするか、
    echo 社内のWebサーバーに丸ごとアップロードしてご利用ください。
    pause
  )
)

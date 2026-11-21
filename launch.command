#!/bin/bash
# シフトカレンダー登録アプリ 起動スクリプト

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

PORT=8765

echo "=========================================="
echo " 📅 シフトカレンダー登録アプリ を起動中..."
echo "=========================================="

# 既存のプロセスがあれば停止
PID=$(lsof -ti :$PORT)
if [ -n "$PID" ]; then
  kill -9 $PID 2>/dev/null
fi

# ブラウザを開く
sleep 0.5
open "http://localhost:$PORT"

echo "ブラウザでアプリを開きました: http://localhost:$PORT"
echo "※ ブラウザのタブを閉じると、このターミナルも自動的に終了します。"

# Pythonサーバーをフォアグラウンドで実行（ブラウザを閉じると自動停止）
python3 "$DIR/app.py"

# サーバー終了後、ターミナルウィンドウをダイアログなしで自動的に閉じる
(
  sleep 0.2
  osascript -e '
    tell application "Terminal"
      try
        set winList to (every window whose name contains "launch.command")
        repeat with w in winList
          close w saving no
        end repeat
      end try
    end tell
    tell application "System Events"
      try
        tell process "Terminal"
          if exists sheet 1 of front window then
            click button "終了" of sheet 1 of front window
          end if
        end tell
      end try
    end tell
  ' 2>/dev/null
) &
exit 0

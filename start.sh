#!/bin/bash
# シフトカレンダー登録アプリ 起動スクリプト

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

PORT=8765

# このターミナルウィンドウのIDを事前に取得（終了時にダイアログなしで閉じるため）
WIN_ID=$(osascript -e 'tell application "Terminal" to return id of front window' 2>/dev/null)

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

# サーバー終了後、プロセスを切り離してこのターミナルウィンドウを自動的に閉じる
# （シェルプロセスが完全終了した0.4秒後にウィンドウを閉じることで、強制終了警告ダイアログを防ぎます）
(
  sleep 0.4
  osascript -e "tell application \"Terminal\"
    try
      if \"$WIN_ID\" is not \"\" then
        close (every window whose id is $WIN_ID) saving no
      else
        close front window saving no
      end if
    end try
    if (count of (every window whose visible is true)) is 0 then
      quit
    end if
  end tell"
) >/dev/null 2>&1 &
disown
exit 0

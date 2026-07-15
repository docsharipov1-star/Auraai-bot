#!/bin/bash
set -e

mkdir -p /app/data

# Telegram-бот в фоне
python3 auraai_bot_v3.py &
BOT_PID=$!

# Веб-сервер на переднем плане (Railway требует открытый порт)
uvicorn saas.api.server:app --host 0.0.0.0 --port ${PORT:-8080} &

# Если бот упал — перезапускаем
wait $BOT_PID
echo "Bot exited, restarting..."
exec bash "$0"

#!/bin/bash
# Запускает и Telegram-бот и веб-сервер параллельно
python auraai_bot_v3.py &
uvicorn saas.api.server:app --host 0.0.0.0 --port ${PORT:-8080}

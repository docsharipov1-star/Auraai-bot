#!/bin/bash
# Автодеплой в Railway через GitHub
# Использование: ./deploy.sh "описание изменений"

MSG=${1:-"Update bot"}

echo "📦 Добавляю файлы..."
git add -A

echo "💾 Коммит: $MSG"
git commit -m "$MSG"

echo "🚀 Отправляю в GitHub..."
git push origin main

echo "✅ Готово! Railway начнёт деплой автоматически."
echo "   Следи за деплоем: https://railway.app"

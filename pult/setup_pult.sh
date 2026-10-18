#!/bin/bash
# Установка пульта клиники «Аура» на VPS (Ubuntu 22.04/24.04).
# Запуск:  bash /root/pult/setup_pult.sh
# Повторный запуск обновляет пульт и не трогает данные и настройки почты.
set -e

SRC="$(cd "$(dirname "$0")" && pwd)"
DIR=/opt/pult
PORT=8600

echo "========================================="
echo "   Установка пульта клиники «Аура»"
echo "========================================="

apt-get update -q
apt-get install -y -q python3 python3-venv curl

mkdir -p "$DIR/static" "$DIR/data" "$DIR/backups"
cp "$SRC/pult_server.py" "$DIR/"
cp "$SRC/static/index.html" "$DIR/static/"

[ -d "$DIR/venv" ] || python3 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q --upgrade pip
"$DIR/venv/bin/pip" install -q "fastapi>=0.110" "uvicorn>=0.29"

if [ ! -f "$DIR/.env" ]; then
  echo
  echo "── Настройка почты ──"
  read -r -p "Твоя почта (владелец, на неё придёт код входа): " OWNER
  read -r -p "Ящик Mail.ru, С КОТОРОГО отправлять коды: " SUSER
  read -r -s -p "Пароль для внешнего приложения этого ящика: " SPASS; echo
  SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  cat > "$DIR/.env" <<EOF
OWNER_EMAIL=$OWNER
SMTP_HOST=smtp.mail.ru
SMTP_PORT=465
SMTP_USER=$SUSER
SMTP_PASS=$SPASS
PULT_SECRET=$SECRET
PULT_DATA=$DIR/data
PULT_BACKUPS=$DIR/backups
EOF
  chmod 600 "$DIR/.env"
fi

cat > /etc/systemd/system/pult.service <<EOF
[Unit]
Description=Пульт клиники Аура
After=network.target

[Service]
WorkingDirectory=$DIR
EnvironmentFile=$DIR/.env
ExecStart=$DIR/venv/bin/uvicorn pult_server:app --host 0.0.0.0 --port $PORT --proxy-headers
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable pult >/dev/null 2>&1
systemctl restart pult

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow $PORT/tcp >/dev/null
fi

sleep 3
IP=$(curl -s -4 --max-time 5 ifconfig.me || hostname -I | awk '{print $1}')
echo
if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null; then
  echo "✅ Пульт работает:  http://$IP:$PORT"
  echo "   Войди со своей почты, затем «Настройки → Доступ администраторов»."
else
  echo "❌ Пульт не запустился. Посмотри ошибки:  journalctl -u pult -n 50 --no-pager"
fi

# ── проверка безопасности соседнего сервиса ──
if systemctl is-active --quiet vps-api 2>/dev/null; then
  if ! grep -q "^SERVER_API_SECRET=" /opt/alina/.env 2>/dev/null; then
    echo
    echo "⚠️  ВНИМАНИЕ: сервис vps-api (порт 9090) работает с паролем по умолчанию из кода бота."
    echo "   Любой, кто знает этот пароль, может управлять сервером — а здесь теперь данные пациентов."
    echo "   Задай свой пароль: допиши в /opt/alina/.env строку SERVER_API_SECRET=<длинный пароль>,"
    echo "   выполни: systemctl restart vps-api — и тот же пароль поставь боту в Railway в VPS_API_SECRET."
  fi
fi

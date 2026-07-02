#!/bin/bash
# Установка VPS API (управление сервером через Telegram)
set -e

echo "Установка VPS API..."

# Python зависимости
/opt/alina/venv/bin/pip install -q fastapi uvicorn

# Копируем файл
cp /root/vps_api.py /opt/alina/vps_api.py

# Systemd сервис
cat > /etc/systemd/system/vps-api.service << 'EOF'
[Unit]
Description=VPS API для управления через Telegram
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/alina
EnvironmentFile=/opt/alina/.env
ExecStart=/opt/alina/venv/bin/uvicorn vps_api:app --host 0.0.0.0 --port 9090
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable vps-api
systemctl restart vps-api

echo "VPS API запущен на порту 9090"
systemctl status vps-api --no-pager

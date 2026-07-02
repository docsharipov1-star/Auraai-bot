#!/bin/bash
# Установка Алины на Timeweb VPS (Ubuntu 22.04/24.04)
# Запуск: bash setup_alina.sh
set -e

echo "========================================="
echo "  Установка Алины — AI телефонный агент  "
echo "========================================="

# ── 1. Системные пакеты ───────────────────────────────────────────────────────
apt-get update -q
apt-get install -y -q \
    asterisk \
    python3 python3-pip python3-venv \
    ffmpeg sox \
    git curl wget

# ── 2. Директории ─────────────────────────────────────────────────────────────
mkdir -p /opt/alina/sounds
mkdir -p /var/spool/asterisk/recording

# ── 3. Python окружение ───────────────────────────────────────────────────────
python3 -m venv /opt/alina/venv
/opt/alina/venv/bin/pip install -q --upgrade pip
/opt/alina/venv/bin/pip install -q \
    openai \
    anthropic \
    aiohttp \
    aiofiles

# ── 4. Asterisk конфиги ───────────────────────────────────────────────────────
echo "Настройка Asterisk..."

# ari.conf
cat > /etc/asterisk/ari.conf << 'EOF'
[general]
enabled=yes
pretty=yes
allowed_origins=*

[alina]
type=user
password=alina_secret_2024
read_only=no
EOF

# pjsip.conf — Novofon SIP trunk (IP-аутентификация)
cat > /etc/asterisk/pjsip.conf << 'EOF'
[global]
type=global
endpoint_identifier_order=ip,username

[transport-udp]
type=transport
protocol=udp
bind=0.0.0.0:5060
external_media_address=REPLACE_WITH_YOUR_IP
external_signaling_address=REPLACE_WITH_YOUR_IP

; ── Novofon trunk ─────────────────────────────────────────────
[novofon-trunk]
type=endpoint
transport=transport-udp
context=from-novofon
disallow=all
allow=ulaw,alaw
direct_media=no
rtp_symmetric=yes
force_rport=yes
rewrite_contact=yes
from_domain=sip.novofon.ru
outbound_proxy=sip:sip.novofon.ru:5060

[novofon-aor]
type=aor
contact=sip:sip.novofon.ru:5060
qualify_frequency=30

[novofon-identify]
type=identify
endpoint=novofon-trunk
match=sip.novofon.ru
EOF

# extensions.conf
cat > /etc/asterisk/extensions.conf << 'EOF'
[general]
static=yes
writeprotect=no
autofallthrough=yes

; Входящие звонки от Novofon → Алина ARI
[from-novofon]
exten => _X.,1,NoOp(Звонок от ${CALLERID(num)} на ${EXTEN})
 same => n,Answer()
 same => n,Wait(0.5)
 same => n,Stasis(alina)
 same => n,Hangup()

exten => s,1,NoOp(Звонок без номера)
 same => n,Stasis(alina)
 same => n,Hangup()

; Исходящие звонки через Novofon
[outbound]
exten => _7XXXXXXXXXX,1,NoOp(Исходящий на ${EXTEN})
 same => n,Dial(PJSIP/${EXTEN}@novofon-trunk,60)
 same => n,Hangup()

exten => _+7XXXXXXXXXX,1,NoOp(Исходящий + на ${EXTEN})
 same => n,Dial(PJSIP/${EXTEN:1}@novofon-trunk,60)
 same => n,Hangup()
EOF

# http.conf — включаем ARI HTTP сервер
cat > /etc/asterisk/http.conf << 'EOF'
[general]
enabled=yes
bindaddr=127.0.0.1
bindport=8088
prefix=
EOF

# ── 5. Systemd сервис для Алины ───────────────────────────────────────────────
cat > /etc/systemd/system/alina.service << 'EOF'
[Unit]
Description=Алина AI телефонный агент
After=network.target asterisk.service
Requires=asterisk.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/alina
EnvironmentFile=/opt/alina/.env
ExecStart=/opt/alina/venv/bin/python3 /opt/alina/alina_ari.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# ── 6. .env шаблон ────────────────────────────────────────────────────────────
if [ ! -f /opt/alina/.env ]; then
cat > /opt/alina/.env << 'EOF'
OPENAI_API_KEY=sk-proj-ЗАМЕНИ_НА_СВОЙ
ANTHROPIC_API_KEY=sk-ant-ЗАМЕНИ_НА_СВОЙ
BOT_TOKEN=TELEGRAM_BOT_TOKEN
ADMIN_CHAT_ID=TELEGRAM_ADMIN_ID
ARI_USER=alina
ARI_PASS=alina_secret_2024
EOF
echo "⚠️  Заполни /opt/alina/.env своими ключами!"
fi

# ── 7. Права ─────────────────────────────────────────────────────────────────
chown -R asterisk:asterisk /var/spool/asterisk/recording 2>/dev/null || true
chmod 777 /var/spool/asterisk/recording
chmod 777 /opt/alina/sounds

# ── 8. Старт сервисов ─────────────────────────────────────────────────────────
echo "Перезапускаем Asterisk..."
systemctl enable asterisk
systemctl restart asterisk
sleep 3

echo "Включаем Алину..."
systemctl daemon-reload
systemctl enable alina

echo ""
echo "========================================="
echo "  Установка завершена!"
echo ""
echo "  Следующие шаги:"
echo "  1. Отредактируй /opt/alina/.env — вставь ключи"
echo "  2. В /etc/asterisk/pjsip.conf замени REPLACE_WITH_YOUR_IP"
echo "     на IP этого сервера ($(curl -s ifconfig.me))"
echo "  3. systemctl start alina"
echo "  4. В Novofon укажи 'Адрес терминации': $(curl -s ifconfig.me):5060"
echo "========================================="
